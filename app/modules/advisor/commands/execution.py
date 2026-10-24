"""Allowlisted, transactional local CRUD for explicitly authorized consultation commands.

The caller validates user intent and owns commit/rollback and the runtime lease. This
module never calls a provider or commits. A user-message lock serializes its receipts
with the data changes, so replay after a checkpoint does not repeat a write.
"""
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation, localcontext

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Numeric, String, inspect, or_, select
from sqlalchemy.exc import IntegrityError

from app.modules.context.record_privacy import RECORD_CATEGORY
from app.modules.context.source_policy import source_allowed
from app.modules.database.model import AdvisorMessage, AuditLog, Base, LocalPosition
from app.modules.finance.clock import local_today
from app.modules.finance.value_history import capture, split_history_fields, tracks
from app.modules.finance.value_history_manager import value_history_manager
from app.modules.personal_data.personal_data_manager import RESOURCES

OPERATIONS = frozenset({"create", "read", "update", "delete"})
WRITABLE_RESOURCES = frozenset(RESOURCES) - {"fx-rates"}
SELECTOR_FIELDS = frozenset({"id", "name", "title", "symbol", "company", "role", "kind", "status",
    "performed_on", "occurred_on", "due_on", "starts_at", "account_id", "application_id", "goal_id",
    "base", "quote", "stage", "activity", "category", "currency", "institution"})
PRICE_FIELDS = frozenset({"last_price", "price_as_of"})
DELTA_FIELDS = {"accounts": "balance", "liabilities": "balance", "other-assets": "value", "holdings": "quantity"}


class CommandInputError(ValueError):
    pass


def separate_position_authorized(query):
    """Only the user's own separate-position request can bypass a ticker duplicate."""
    from app.modules.advisor.commands.intent import factual_write_authorized, instruction_text, operation_authorized
    if not isinstance(query, str):
        return False
    text = instruction_text(query)
    return bool(operation_authorized(text, "create") and factual_write_authorized(text, "holdings") and re.search(
        r'(?:다른|별도(?:의)?|새(?:로운)?)\s*계좌|계좌(?:가|는)?\s*(?:서로\s*)?(?:다르|다른|달라)|'
        r'별도(?:의)?\s*보유분|새(?:로운)?\s*(?:포지션|보유분)', text))


def command_target_label(command):
    for group in (command.get('values', {}), command.get('selector', {})):
        for key in ('symbol', 'ticker', 'name', 'title', 'activity'):
            label = group.get(key)
            if isinstance(label, str) and label.strip():
                return label.strip()[:120]
    return None


def _result(command, status, message, **fields):
    return {"operation": command.get("operation"), "resource": command.get("resource"),
            "status": status, "message": message, "target_label": command_target_label(command), **fields}


def _reference(resource, obj):
    return {"table": resource.handler.model.__tablename__, "id": obj.id,
            "updated_at": obj.updated_at.isoformat() if getattr(obj, "updated_at", None) else None,
            "category": RECORD_CATEGORY.get(resource.handler.model.__tablename__, "investment")}


def _visible(session, resource, obj, excluded):
    table = resource.handler.model.__tablename__
    if RECORD_CATEGORY.get(table) in {str(c) for c in excluded}:
        return False
    # FX rows are public observations and are not in the personal provenance table allowlist.
    if table == "fx_rates":
        return "investment" not in {str(c) for c in excluded}
    if not source_allowed(session, [{"table": table, "id": obj.id}], excluded):
        return False
    for column in inspect(type(obj)).columns:
        value = getattr(obj, column.key)
        for foreign in column.foreign_keys:
            if value is not None and not source_allowed(session, [{"table": foreign.column.table.name, "id": value}], excluded):
                return False
    return True


def _serialized(resource, obj):
    result = resource.item_schema.model_validate(obj).model_dump(mode="json")
    if getattr(obj, "updated_at", None) is not None:
        result["version"] = obj.updated_at.isoformat()
    shortened = [key for key, value in result.items() if isinstance(value, str) and len(value) > 2000]
    for key in shortened:
        result[key] = result[key][:2000]
    if shortened:
        result["_truncated_fields"] = shortened
    return result


def _holding_fields(values):
    if not isinstance(values, dict):
        raise CommandInputError("종목 입력 형식을 확인해 주세요.")
    fields = dict(values)
    for alias, canonical in (("ticker", "symbol"), ("label", "name")):
        if alias in fields:
            if canonical in fields and fields[canonical] != fields[alias]:
                raise CommandInputError("서로 다른 종목 입력이 있습니다. 종목과 이름을 확인해 주세요.")
            fields[canonical] = fields.pop(alias)
    if isinstance(fields.get("symbol"), str):
        fields["symbol"] = fields["symbol"].strip().upper()
    if isinstance(fields.get("currency"), str):
        fields["currency"] = fields["currency"].strip().upper()
    return fields


def _matches(session, resource, selector, *, lock=False, limit=101):
    model = resource.handler.model
    if model.__tablename__ == "holdings":
        selector = _holding_fields(selector)
    columns = {column.key: column for column in inspect(model).columns}
    if not isinstance(selector, dict) or set(selector) - (SELECTOR_FIELDS & set(columns)):
        raise CommandInputError("조회 대상 필드를 확인해 주세요.")
    if limit is None and (model.__tablename__ != "holdings" or not selector.get("symbol")):
        raise CommandInputError("보유 종목의 정확한 티커가 필요합니다.")
    filters = []
    for field, value in selector.items():
        if isinstance(value, (dict, list, bool)) or value is None:
            raise CommandInputError("대상은 비어 있지 않은 정확한 값으로 지정해 주세요.")
        try:
            expected = TypeAdapter(columns[field].type.python_type).validate_python(value)
        except (ValueError, TypeError):
            raise CommandInputError("조회 대상 값의 형식을 확인해 주세요.") from None
        if model.__tablename__ == "holdings" and field == "symbol" and ":" not in expected:
            # A bare ticker identifies a local position only when all supplied
            # conditions leave one row. Never guess its exchange from a model.
            filters.append(or_(model.symbol == expected, model.symbol.endswith(":" + expected, autoescape=True)))
        else:
            filters.append(getattr(model, field) == expected)
    statement = select(model).where(*filters).order_by(model.id).limit(limit).execution_options(populate_existing=True)
    if lock:
        statement = statement.with_for_update()
    return list(session.scalars(statement))


def _holding_values(session, resource, values, obj, excluded):
    values = _holding_fields(values)
    symbol = values.get("symbol")
    if not isinstance(symbol, str) or ":" in symbol:
        return values
    if obj is not None and obj.symbol.rsplit(":", 1)[-1] == symbol:
        values["symbol"] = obj.symbol
        return values
    identity = {key: values[key] for key in ("symbol", "currency") if values.get(key) is not None}
    # Hidden matches must not consume the lookup budget before sharing is checked.
    # This lookup is scoped to one explicit ticker; ordinary reads remain bounded.
    rows = _matches(session, resource, identity, limit=None)
    identities = {(row.symbol, row.currency) for row in rows if _visible(session, resource, row, excluded)}
    if len(identities) == 1:
        known_symbol, known_currency = next(iter(identities))
        values["symbol"] = known_symbol
        values.setdefault("currency", known_currency)
    return values


def _separate_position_key(session, command, excluded):
    """Cosmetic extraction fields cannot turn one requested lot into two writes."""
    try:
        values = _holding_values(session, RESOURCES["holdings"], command.get("values", {}), None, excluded)
        identity = {field: values.get(field) for field in ("symbol", "currency", "account_id", "quantity", "avg_cost")}
        if identity["account_id"] is not None:
            if isinstance(identity["account_id"], bool):
                return None
            identity["account_id"] = TypeAdapter(int).validate_python(identity["account_id"])
        for field in ("quantity", "avg_cost"):
            if identity[field] is not None:
                number = Decimal(str(identity[field]))
                if not number.is_finite():
                    return None
                with localcontext() as context:
                    context.prec = max(100, len(number.as_tuple().digits))
                    identity[field] = str(number.normalize()) if number else "0"
        return json.dumps(identity, sort_keys=True, ensure_ascii=False)
    except (CommandInputError, InvalidOperation, TypeError, ValueError):
        return None


def confirmed_holding_addition(session, command: dict, *, original_query: str,
                               original_command: dict | None, clarification: str, excluded: set) -> dict:
    """Recover an approved total as its original addition, never a model-derived set.

    The caller binds the pending request and the current affirmative response. This
    helper only accepts a unique, currently shared position whose locked quantity
    plus the original input equals the proposed total named in the prior question.
    """
    values = command.get("values", {})
    if (command.get("resource") != "holdings" or command.get("operation") != "update"
            or not isinstance(values, dict) or "quantity" not in values or "delta" in values
            or original_command is not None and original_command.get("resource") != "holdings"
            or not re.search(r"추가|더\s*(?:있|샀|매수|보유|갖)", original_query)):
        return command

    def quantity(value):
        if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
            raise ValueError("not an exact quantity")
        result = Decimal(str(value).replace(",", ""))
        if not result.is_finite() or result <= 0 or result >= Decimal("1e20") or result != result.to_integral_value():
            raise ValueError("not a positive whole quantity")
        return Decimal(int(result))

    def symbol_pattern(symbol):
        return re.compile(r"(?<![A-Za-z0-9.:-])(?:[A-Za-z][A-Za-z0-9]*:)?" + re.escape(symbol) + r"(?![A-Za-z0-9.:-])", re.I)

    def other_symbol(text, symbol, currency):
        from app.modules.portfolio.quotes_sheet import EXCHANGES
        allowed = EXCHANGES | {symbol, currency, "USD", "KRW", "EUR", "JPY", "TOTAL"}
        return any(token.rsplit(":", 1)[-1].upper() not in allowed
                   for token in re.findall(r"(?<![A-Z0-9.:-])[A-Z][A-Z0-9.:-]*(?![A-Z0-9.:-])", text))

    try:
        total = quantity(values["quantity"])
        resource = RESOURCES["holdings"]
        selector = command.get("selector", {})
        if not selector:
            return command
        rows = _matches(session, resource, selector, lock=True)
        if len(rows) != 1 or not _visible(session, resource, rows[0], excluded):
            return command
        row = rows[0]
        symbol = row.symbol.rsplit(":", 1)[-1].upper()
        pattern = symbol_pattern(symbol)
        original_values = _holding_fields((original_command or {}).get("values", {}))
        original_selector = _holding_fields((original_command or {}).get("selector", {}))
        original_symbol = original_values.get("symbol") or original_selector.get("symbol")
        if original_symbol and (original_symbol != row.symbol if ":" in original_symbol else original_symbol != symbol):
            return command
        if original_values.get("currency", row.currency) != row.currency:
            return command
        if original_selector.get("id") is not None and str(original_selector["id"]) != str(row.id):
            return command
        if original_values.get("account_id", row.account_id) != row.account_id:
            return command
        added = quantity(original_values["quantity"]) if "quantity" in original_values else None
        parsed = []
        for line in re.split(r"[\n;]", original_query):
            for match in pattern.finditer(line):
                if ":" in match.group() and ":" in row.symbol and match.group().upper() != row.symbol.upper():
                    return command
                tail = line[match.end():]
                amount = re.search(r"(?<![\d,.+−–-])([\d,]+(?:\.\d+)?)\s*주", tail)
                if amount and not other_symbol(tail[:amount.start()], symbol, row.currency):
                    if re.search(r"팔|매도|차감|감소", tail[:amount.end()]):
                        return command
                    parsed.append(quantity(amount.group(1)))
        if parsed:
            if len(set(parsed)) != 1 or added is not None and added != parsed[0]:
                return command
            added = parsed[0]
        with localcontext() as context:
            context.prec = 100
            if added is None or Decimal(row.quantity) + added != total:
                return command
        total_pattern = re.compile(r"(?<![\d,.+−–-])([\d,]+(?:\.\d+)?)\s*주")
        confirmed = False
        for clause in re.split(r"[\n;!?。]|(?<=\.)\s+", clarification):
            for match in pattern.finditer(clause):
                if ":" in match.group() and ":" in row.symbol and match.group().upper() != row.symbol.upper():
                    continue
                tail = clause[match.end():]
                for amount in total_pattern.finditer(tail):
                    if quantity(amount.group(1)) == total and not other_symbol(tail[:amount.start()], symbol, row.currency):
                        confirmed = True
        if not confirmed:
            return command
        resolved = dict(values)
        resolved.pop("quantity")
        resolved["delta"] = format(added, "f")
        return {**command, "values": resolved}
    except (CommandInputError, InvalidOperation, TypeError, ValueError):
        return command


def _validate_values(session, name, resource, values, obj, excluded):
    if not isinstance(values, dict) or not values:
        raise CommandInputError("저장할 필드를 알려주세요.")
    values = dict(values)
    fractional_delta_quantity = None
    if name == "holdings":
        values = _holding_values(session, resource, values, obj, excluded)
    if "delta" in values:
        field = DELTA_FIELDS.get(name)
        if obj is None or field is None or field in values:
            raise CommandInputError("증감은 기존 금액·보유 수량 하나에만 적용할 수 있습니다.")
        delta = values.pop("delta")
        try:
            if not isinstance(delta, (str, int)) or isinstance(delta, bool):
                raise InvalidOperation
            number = Decimal(delta)
            if not number.is_finite() or number.adjusted() > 32:
                raise InvalidOperation
            with localcontext() as context:
                context.prec = 100
                scale = inspect(resource.handler.model).columns[field].type.scale or 0
                if number != number.quantize(Decimal(1).scaleb(-scale)):
                    raise InvalidOperation
                updated = Decimal(str(getattr(obj, field))) + number
            if field == "quantity":
                if number != number.to_integral_value() or updated < 0:
                    raise InvalidOperation
                if updated == updated.to_integral_value():
                    values[field] = int(updated)
                else:
                    # An integer trade preserves the existing legacy fraction.
                    # Validate other input fields with an integer placeholder;
                    # the exact server-calculated total is checked against the
                    # ORM Numeric scale/range below, before it can be written.
                    fractional_delta_quantity = updated
                    values[field] = 0
            else:
                values[field] = str(updated)
        except (InvalidOperation, ValueError):
            raise CommandInputError("증감할 금액·수량의 형식과 범위를 확인해 주세요.") from None
    schema = resource.create_schema
    if set(values) - set(schema.model_fields):
        raise CommandInputError("허용되지 않은 저장 필드가 있습니다.")
    columns = {column.key: column for column in inspect(resource.handler.model).columns}
    if any(isinstance(columns[field].type, Numeric) and isinstance(value, (float, bool))
           for field, value in values.items() if field in columns):
        raise CommandInputError("금액·수량은 정밀도를 보존하는 숫자 문자열로 입력해 주세요.")
    if obj is None and "currency" in schema.model_fields and "currency" not in values:
        raise CommandInputError("통화를 함께 알려주세요. 예: 원화 또는 미국 달러")
    if name == "holdings" and set(values) & PRICE_FIELDS:
        raise CommandInputError("상담에서는 보유 수량과 원가만 기록합니다. 시세는 시세 연결에서 갱신해 주세요.")
    if name == "holdings" and values.get("avg_cost") is not None:
        try:
            cost = Decimal(str(values["avg_cost"]))
            if not cost.is_finite() or cost < 0:
                raise InvalidOperation
        except InvalidOperation:
            raise CommandInputError("평균 매입원가는 0 이상의 유효한 금액이어야 합니다.") from None
    existing = {key: getattr(obj, key) for key in schema.model_fields if obj is not None and hasattr(obj, key)}
    # A quantity-only edit of an existing fractional legacy holding must not round it.
    if name == "holdings" and obj is not None and "quantity" not in values:
        existing.pop("quantity", None)
    body_values = {**existing, **values}
    legacy_quantity = name == "holdings" and obj is not None and "quantity" not in values
    if legacy_quantity:
        body_values["quantity"] = 0
    try:
        body = schema.model_validate(body_values)
    except ValidationError as exc:
        fields = ", ".join(sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]}))
        raise CommandInputError(f"필수 정보 또는 입력 형식을 확인해 주세요: {fields}") from None
    data, trade_date = split_history_fields(name, body)
    if legacy_quantity:
        data["quantity"] = obj.quantity
    if fractional_delta_quantity is not None:
        data["quantity"] = fractional_delta_quantity
    for field, value in data.items():
        column = columns[field]
        if value is None:
            continue
        if isinstance(column.type, Numeric):
            try:
                number = Decimal(str(value))
                if not number.is_finite() or isinstance(value, bool):
                    raise InvalidOperation
                with localcontext() as context:
                    context.prec = 100
                    if column.type.scale is not None and number != number.quantize(Decimal(1).scaleb(-column.type.scale)):
                        raise InvalidOperation
                    if column.type.precision is not None and abs(number) >= Decimal(10) ** (column.type.precision - (column.type.scale or 0)):
                        raise InvalidOperation
            except InvalidOperation:
                raise CommandInputError("금액·수량의 범위와 소수 자릿수를 확인해 주세요.") from None
        if isinstance(column.type, String) and column.type.length and len(str(value)) > column.type.length:
            raise CommandInputError("입력 내용이 저장 가능한 길이를 초과했습니다.")
        for foreign in column.foreign_keys:
            table = foreign.column.table.name
            model = next((mapper.class_ for mapper in Base.registry.mappers if mapper.local_table.name == table), None)
            if model is None or session.get(model, value) is None or not source_allowed(session, [{"table": table, "id": value}], excluded):
                raise CommandInputError("연결할 기록을 찾을 수 없거나 상담 공유가 허용되지 않았습니다.")
    if name == "cashflow-entries" and data["currency"] != "KRW":
        raise CommandInputError("새 가계부 기록은 원화로 입력하세요.")
    if "currency" in data and (len(data["currency"]) != 3 or not data["currency"].isalpha() or data["currency"] != data["currency"].upper()):
        raise CommandInputError("통화는 대문자 세 글자로 입력해 주세요.")
    if name in {"calendar-events", "interviews"} and data.get("ends_at") and data["ends_at"] <= data["starts_at"]:
        raise CommandInputError("종료 시각은 시작 시각보다 늦어야 합니다.")
    if name == "holdings" and (obj is None or data["symbol"] != obj.symbol):
        from app.schema.holdings_schema import HoldingInput
        try:
            # Recording a holding does not require setting up automatic quotes.
            # Reuse the public symbol syntax without inventing an exchange or a
            # manual market price just to satisfy the separate quote-input form.
            TypeAdapter(HoldingInput.model_fields["ticker"].rebuild_annotation()).validate_python(data["symbol"])
        except ValidationError:
            raise CommandInputError("종목 코드 형식을 확인해 주세요. 예: AAPL 또는 NASDAQ:AAPL") from None
    return data, trade_date


def _execute(session, command, excluded, *, separate_authority=False):
    name, operation = command.get("resource"), command.get("operation")
    resource = RESOURCES.get(name)
    if resource is None or operation not in OPERATIONS or operation != "read" and name not in WRITABLE_RESOURCES:
        return _result(command, "failed", "지원하지 않는 데이터 작업입니다.")
    category = RECORD_CATEGORY.get(resource.handler.model.__tablename__, "investment")
    if category in {str(c) for c in excluded}:
        return _result(command, "failed", "이 데이터는 상담 공유에서 제외되어 있습니다.")
    selector = command.get("selector", {})
    separate = name == "holdings" and separate_authority
    if separate and operation == "update":
        return _result(command, "needs_input", "다른 계좌의 보유분은 기존 기록을 수정하지 않고 새 보유 기록으로 저장해야 합니다.")
    if operation in {"update", "delete"} and not selector:
        return _result(command, "needs_input", "변경할 기록 하나를 지정해 주세요.")
    if name == "holdings" and operation == "create":
        values = _holding_values(session, resource, command.get("values", {}), None, excluded)
        command = {**command, "values": values}
        if values.get("symbol"):
            identity = {key: values[key] for key in ("symbol", "currency", "account_id") if values.get(key) is not None}
            matches = _matches(session, resource, identity, lock=True, limit=None)
            visible_matches = [row for row in matches if _visible(session, resource, row, excluded)]
            if visible_matches and not (separate and values.get("account_id") is None):
                return _result(command, "needs_input", "기존 보유 기록이 있습니다. 같은 계좌의 추가 수량인지, 다른 계좌의 별도 보유분인지 알려주세요.",
                    candidates=[{"id": row.id, "label": row.name or row.symbol, "symbol": row.symbol,
                                 "currency": row.currency, "quantity": _serialized(resource, row)["quantity"]}
                                for row in visible_matches[:10]])
        if separate and values.get("account_id") is None and not values.get("name"):
            command = {**command, "values": {**values, "name": str(values.get("symbol", ""))[:104] + " (별도 계좌)"}}
    rows = _matches(session, resource, selector, lock=operation != "read") if operation != "create" else []
    visible = [row for row in rows if _visible(session, resource, row, excluded)]
    if operation == "read":
        records, refs, size = [], [], 0
        for row in visible[:40]:
            record = _serialized(resource, row)
            encoded_size = len(json.dumps(record, ensure_ascii=False))
            if size + encoded_size > 20000:
                break
            records.append(record)
            refs.append(_reference(resource, row))
            size += encoded_size
        truncated = len(rows) > 100 or len(records) < len(visible) or any(record.get("_truncated_fields") for record in records)
        return _result(command, "read", "공유가 허용된 기록 중 일부 또는 긴 내용을 생략했습니다. 조회 범위를 좁혀주세요." if truncated else "상담 공유가 허용된 기록을 조회했습니다.",
                       records=records, record_refs=refs, truncated=truncated, scope="shared_records")
    if operation in {"update", "delete"} and len(rows) != 1:
        return _result(command, "needs_input", "일치하는 기록이 없거나 여러 개입니다. 대상을 구체적으로 알려주세요.",
                       candidates=[{"id": row.id, "label": next((str(getattr(row, field)) for field in ("name", "title", "company", "activity", "symbol") if getattr(row, field, None)), str(row.id))} for row in visible[:10]])
    obj = rows[0] if rows else None
    if obj is not None and obj not in visible:
        return _result(command, "failed", "이 기록은 상담 공유에서 제외되어 있습니다.")
    if operation == "delete":
        # Cascades/SET NULL can silently change other records. Ask the user to resolve
        # links first rather than letting a single-record request delete a collection.
        table = resource.handler.model.__tablename__
        for mapper in Base.registry.mappers:
            if mapper.class_ is LocalPosition:
                continue
            for column in mapper.columns:
                if any(foreign.column.table.name == table for foreign in column.foreign_keys):
                    if session.scalar(select(mapper.class_).where(getattr(mapper.class_, column.key) == obj.id).limit(1)) is not None:
                        return _result(command, "needs_input", "다른 기록에서 참조 중입니다. 연결된 기록을 먼저 정리해 주세요.")
        record = _serialized(resource, obj)
        reference = _reference(resource, obj)
        if tracks(name):
            value_history_manager.record(session, name, obj, capture(name, obj), "delete", today=local_today())
        resource.handler.delete(session, obj)
        return _result(command, "saved", "삭제했습니다.", record_id=record["id"], record_ref=reference, record={"id": record["id"]})
    data, trade_date = _validate_values(session, name, resource, command.get("values", {}), obj, excluded)
    before = capture(name, obj) if obj is not None and tracks(name) else None
    symbol_changed = name == "holdings" and obj is not None and (obj.symbol != data["symbol"] or obj.currency != data["currency"])
    if symbol_changed:
        data["last_price"], data["price_as_of"] = None, None
    obj = resource.handler.create(session, data) if obj is None else resource.handler.update(session, obj, data)
    if tracks(name):
        value_history_manager.record(session, name, obj, before, "create" if operation == "create" else "update",
                                     today=local_today(), trade_date=trade_date)
    if name == "holdings":
        from app.modules.portfolio.holdings_manager import version
        mapping = session.scalar(select(LocalPosition).where(LocalPosition.holding_id == obj.id).with_for_update())
        if mapping is None:
            mapping = LocalPosition(position_id=f"advisor-{obj.id}", holding_id=obj.id, quote_mode="auto", version=version(obj))
            session.add(mapping)
        mapping.version = version(obj)
        if symbol_changed:
            mapping.quote_mode = "auto"
    session.flush()
    fields = {}
    message = "저장했습니다."
    if name == "holdings":
        from app.modules.portfolio.quotes_sheet import quote_rows
        needs_exchange = mapping.quote_mode == "auto" and not quote_rows([obj.symbol])
        fields = {"quote_status": "ready" if obj.last_price is not None else "pending", "quote_needs_exchange": needs_exchange}
        if needs_exchange:
            message = "보유 기록을 저장했습니다. 거래소를 확인하면 자동 시세를 연결할 수 있습니다."
        if separate and operation == "create":
            fields.update(separate_position=True,
                          account_status="assigned" if obj.account_id is not None else "unspecified")
            message = ("기존 보유 기록과 분리해 별도 계좌의 보유분을 저장했습니다. "
                       "계좌 이름은 나중에 연결할 수 있습니다." if obj.account_id is None else
                       "선택한 계좌의 별도 보유분을 저장했습니다.")
            if needs_exchange:
                message += " 거래소를 확인하면 자동 시세를 연결할 수 있습니다."
    return _result(command, "saved", message, record_id=obj.id,
                   record_ref=_reference(resource, obj), record=_serialized(resource, obj), **fields)


def execute_commands(session, *, commands, conversation_id, message_id, excluded, authorization_check=None,
                     authorized_query=None):
    """Execute a bounded batch. Each command uses a savepoint; the caller commits it.

    Failed/ambiguous commands never write. Successful writes and their receipts are
    atomic, and successful siblings can be committed even when another needs input.
    """
    if not isinstance(commands, list) or len(commands) > 12:
        raise ValueError("상담 데이터 작업은 한 번에 12개까지 실행할 수 있습니다.")
    source = session.scalar(select(AdvisorMessage).where(AdvisorMessage.id == message_id,
        AdvisorMessage.conversation_id == conversation_id, AdvisorMessage.role == "user").with_for_update())
    if source is None:
        raise ValueError("작업을 요청한 사용자 메시지를 찾을 수 없습니다.")
    separate_authority = separate_position_authorized(authorized_query if authorized_query is not None else source.content)
    separate_results = {}
    results = []
    target = f"advisor_messages:{message_id}"
    receipts = list(session.scalars(select(AuditLog).where(AuditLog.action == "advisor.data_command", AuditLog.target == target)))
    for index, command in enumerate(commands):
        if authorization_check:
            authorization_check()
        from app.modules.context.privacy_manager import privacy_manager
        current_excluded = set(excluded) | set(privacy_manager.get_excluded(session))
        fingerprint = hashlib.sha256(json.dumps(command, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
        separate_key = None
        if (separate_authority and command.get("resource") == "holdings" and command.get("operation") == "create"):
            separate_key = _separate_position_key(session, command, current_excluded)
        existing = next((receipt for receipt in receipts if receipt.detail.get("index") == index), None)
        if existing:
            if existing.detail.get("fingerprint") != fingerprint:
                results.append(_result(command, "failed", "같은 메시지의 작업 내용이 달라졌습니다. 새 메시지로 요청해 주세요."))
            else:
                prior = existing.detail["result"]
                resource = RESOURCES.get(prior.get("resource"))
                row = resource.handler.get(session, prior["record_id"]) if resource and prior.get("record_id") else None
                # Never replay cached private values after sharing changes or deletion.
                blocked_category = resource and RECORD_CATEGORY.get(resource.handler.model.__tablename__, "investment") in {str(c) for c in current_excluded}
                if blocked_category or prior.get("operation") != "delete" and (row is None or not _visible(session, resource, row, current_excluded)):
                    results.append(_result(command, "saved", "이 작업은 이미 반영되었습니다. 현재 기록은 삭제되었거나 공유에서 제외되었습니다."))
                else:
                    current = {"record": _serialized(resource, row), "record_ref": _reference(resource, row)} if row is not None and prior.get("operation") != "delete" else {}
                    results.append({**prior, **current, "replayed": True})
            if separate_key is not None and results[-1]["status"] == "saved":
                separate_results[separate_key] = results[-1]
            continue
        if separate_key is not None and separate_key in separate_results:
            results.append({**separate_results[separate_key], "replayed": True})
            continue
        try:
            with session.begin_nested():
                result = _execute(session, command, current_excluded, separate_authority=separate_authority)
                if result["status"] == "saved":
                    receipt = AuditLog(actor="advisor", action="advisor.data_command", target=target,
                        detail={"conversation_id": conversation_id, "index": index, "fingerprint": fingerprint, "result": result})
                    session.add(receipt)
                    receipts.append(receipt)
                    session.flush()
            results.append(result)
            if separate_key is not None and result["status"] == "saved":
                separate_results[separate_key] = result
        except CommandInputError as exc:
            results.append(_result(command, "needs_input", str(exc)))
        except IntegrityError:
            results.append(_result(command, "failed", "연결된 기록이나 저장 조건이 변경되었습니다. 최신 내용을 확인해 주세요."))
    return results
