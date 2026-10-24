"""Allowlisted, transactional local CRUD for explicitly authorized consultation commands.

The caller validates user intent and owns commit/rollback and the runtime lease. This
module never calls a provider or commits. A user-message lock serializes its receipts
with the data changes, so replay after a checkpoint does not repeat a write.
"""
import hashlib
import json
from decimal import Decimal, InvalidOperation, localcontext

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Numeric, String, inspect, select
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


def _result(command, status, message, **fields):
    return {"operation": command.get("operation"), "resource": command.get("resource"),
            "status": status, "message": message, **fields}


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


def _matches(session, resource, selector, *, lock=False):
    model = resource.handler.model
    columns = {column.key: column for column in inspect(model).columns}
    if not isinstance(selector, dict) or set(selector) - (SELECTOR_FIELDS & set(columns)):
        raise CommandInputError("조회 대상 필드를 확인해 주세요.")
    filters = []
    for field, value in selector.items():
        if isinstance(value, (dict, list, bool)) or value is None:
            raise CommandInputError("대상은 비어 있지 않은 정확한 값으로 지정해 주세요.")
        try:
            expected = TypeAdapter(columns[field].type.python_type).validate_python(value)
        except (ValueError, TypeError):
            raise CommandInputError("조회 대상 값의 형식을 확인해 주세요.") from None
        filters.append(getattr(model, field) == expected)
    statement = select(model).where(*filters).order_by(model.id).limit(101).execution_options(populate_existing=True)
    if lock:
        statement = statement.with_for_update()
    return list(session.scalars(statement))


def _validate_values(session, name, resource, values, obj, excluded):
    if not isinstance(values, dict) or not values:
        raise CommandInputError("저장할 필드를 알려주세요.")
    values = dict(values)
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
                if updated != updated.to_integral_value() or updated < 0:
                    raise InvalidOperation
                values[field] = int(updated)
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
            HoldingInput(position_id="advisor-validation", ticker=data["symbol"], label=data.get("name") or data["symbol"],
                         currency=data["currency"], quantity=data["quantity"], avg_cost=data.get("avg_cost"))
        except ValidationError:
            raise CommandInputError("종목·거래소·통화를 확인해 주세요. 예: NASDAQ:AAPL, USD") from None
    return data, trade_date


def _execute(session, command, excluded):
    name, operation = command.get("resource"), command.get("operation")
    resource = RESOURCES.get(name)
    if resource is None or operation not in OPERATIONS or operation != "read" and name not in WRITABLE_RESOURCES:
        return _result(command, "failed", "지원하지 않는 데이터 작업입니다.")
    category = RECORD_CATEGORY.get(resource.handler.model.__tablename__, "investment")
    if category in {str(c) for c in excluded}:
        return _result(command, "failed", "이 데이터는 상담 공유에서 제외되어 있습니다.")
    selector = command.get("selector", {})
    if operation in {"update", "delete"} and not selector:
        return _result(command, "needs_input", "변경할 기록 하나를 지정해 주세요.")
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
    return _result(command, "saved", "저장했습니다.", record_id=obj.id,
                   record_ref=_reference(resource, obj), record=_serialized(resource, obj))


def execute_commands(session, *, commands, conversation_id, message_id, excluded, authorization_check=None):
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
    results = []
    target = f"advisor_messages:{message_id}"
    receipts = list(session.scalars(select(AuditLog).where(AuditLog.action == "advisor.data_command", AuditLog.target == target)))
    for index, command in enumerate(commands):
        if authorization_check:
            authorization_check()
        from app.modules.context.privacy_manager import privacy_manager
        current_excluded = set(excluded) | set(privacy_manager.get_excluded(session))
        fingerprint = hashlib.sha256(json.dumps(command, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
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
            continue
        try:
            with session.begin_nested():
                result = _execute(session, command, current_excluded)
                if result["status"] == "saved":
                    receipt = AuditLog(actor="advisor", action="advisor.data_command", target=target,
                        detail={"conversation_id": conversation_id, "index": index, "fingerprint": fingerprint, "result": result})
                    session.add(receipt)
                    receipts.append(receipt)
                    session.flush()
            results.append(result)
        except CommandInputError as exc:
            results.append(_result(command, "needs_input", str(exc)))
        except IntegrityError:
            results.append(_result(command, "failed", "연결된 기록이나 저장 조건이 변경되었습니다. 최신 내용을 확인해 주세요."))
    return results
