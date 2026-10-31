"""Household ledger import from any bank or card CSV, always through a preview.

The user maps CSV columns to ledger fields. Each row gets a source identity from the
source ID and its own values, so re-importing an overlapping export never duplicates an
entry, and an entry the user deleted is not brought back. Category rules only suggest a
category for new rows; stored entries are never rewritten.
"""

import csv
import hashlib
import io
import json
from calendar import monthrange
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.crud import app_setting_handler, audit_log_handler
from app.modules.database.model import CashflowCategoryRule, CashflowEntry, FinanceImportMapping
from app.schema.cashflow_import_schema import (
    CashflowCategoryRuleCreate,
    CashflowImportInput,
    CashflowImportPresets,
)

MAX_ROWS = 10_000
TABLE = "cashflow_entries"
PRESETS_KEY = "finance.cashflow_import_presets"
# Money(20, 4): at most 16 integer digits and 4 decimal places.
AMOUNT_LIMIT = Decimal("1e16")
DATE_FORMATS = ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y%m%d")
CURRENCY = "KRW"  # new ledger entries are KRW only, as in manual entry


def _amount(raw: str | None) -> Decimal | None:
    """Signed amount from a bank-formatted cell; None when empty. Raises ValueError when unreadable."""
    text = (raw or "").strip()
    for token in (",", " ", "원", "₩", "KRW", " "):
        text = text.replace(token, "")
    if not text:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    if text.endswith("-"):
        negative, text = True, text[:-1]
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("금액을 읽을 수 없습니다") from exc
    if not value.is_finite():
        raise ValueError("금액을 읽을 수 없습니다")
    if value.as_tuple().exponent < -4:
        raise ValueError("금액은 소수 넷째 자리까지만 저장합니다")
    if abs(value) >= AMOUNT_LIMIT:
        raise ValueError("금액이 저장 한도를 넘습니다")
    return -value if negative else value


def _date(raw: str | None) -> date:
    text = (raw or "").strip().split(" ")[0].split("T")[0].rstrip(".")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError("날짜를 읽을 수 없습니다")


def _read(body: CashflowImportInput) -> list[dict[str, str]]:
    stream = io.StringIO(body.csv_text.lstrip("﻿"))
    for _ in range(body.skip_rows):
        stream.readline()
    start = stream.tell()
    header = stream.readline()
    if not header.strip():
        raise ValueError("CSV 머리글 행이 없습니다")
    try:
        delimiter = csv.Sniffer().sniff(header, delimiters=",\t;").delimiter
    except csv.Error:
        delimiter = ","
    stream.seek(start)
    reader = csv.DictReader(stream, delimiter=delimiter)
    fields = [f.strip() for f in reader.fieldnames or []]
    if len(fields) != len(set(fields)):
        raise ValueError("CSV 머리글에 같은 이름의 열이 있습니다")
    reader.fieldnames = fields
    mapped = [c for c in body.mapping.model_dump().values() if c]
    missing = [c for c in mapped if c not in fields]
    if missing:
        raise ValueError(f"CSV에 없는 열입니다: {', '.join(missing)}")
    rows = []
    for index, row in enumerate(reader):
        if index >= MAX_ROWS:
            raise ValueError(f"한 번에 {MAX_ROWS}행까지 가져올 수 있습니다")
        if not any((value or "").strip() for key, value in row.items() if key is not None):
            continue  # blank line
        rows.append(row)
    return rows


def _rules(session: Session) -> list[CashflowCategoryRule]:
    return list(session.scalars(select(CashflowCategoryRule).order_by(CashflowCategoryRule.id)))


def suggest_category(rules: list[CashflowCategoryRule], description: str | None) -> str | None:
    """Exact description match first, then the longest contained text (earliest rule on a tie)."""
    key = (description or "").strip().casefold()
    if not key:
        return None
    for rule in rules:
        if rule.match_kind == "equals" and rule.match_text == key:
            return rule.category
    contained = [r for r in rules if r.match_kind == "contains" and r.match_text in key]
    return max(contained, key=lambda r: (len(r.match_text), -r.id)).category if contained else None


def _source_ref(source_id: str, occurred_on: date, kind: str, amount: Decimal, description: str | None,
                occurrence: int) -> str:
    identity = [source_id, occurred_on.isoformat(), kind, format(amount.normalize(), "f"), description or "", occurrence]
    return "cashflow_csv:" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


def _coverage(dates: list[date]) -> dict:
    if not dates:
        return {"first_date": None, "last_date": None, "partial_months": []}
    first, last = min(dates), max(dates)
    partial = []
    if first.day != 1:
        partial.append(first.strftime("%Y-%m"))
    if last.day != monthrange(last.year, last.month)[1] and last.strftime("%Y-%m") not in partial:
        partial.append(last.strftime("%Y-%m"))
    return {"first_date": first, "last_date": last, "partial_months": partial}


def _parse_row(body: CashflowImportInput, raw: dict[str, str]) -> tuple[dict, list[str]]:
    m = body.mapping
    issues: list[str] = []
    parsed: dict = {"occurred_on": None, "kind": None, "amount": None, "description": None, "csv_category": None}
    try:
        parsed["occurred_on"] = _date(raw.get(m.date))
    except ValueError as exc:
        issues.append(str(exc))
    try:
        if m.amount:
            value = _amount(raw.get(m.amount))
            if not value:
                issues.append("금액이 없거나 0입니다")
            else:
                expense = value < 0 if body.amount_sign == "negative_is_expense" else value > 0
                parsed.update(kind="expense" if expense else "income", amount=abs(value))
        else:
            debit = _amount(raw.get(m.debit)) if m.debit else None
            credit = _amount(raw.get(m.credit)) if m.credit else None
            debit, credit = debit or None, credit or None  # a 0 cell means the other side applies
            if (debit is not None and debit < 0) or (credit is not None and credit < 0):
                issues.append("출금·입금 열의 음수는 지원하지 않습니다")
            elif debit is not None and credit is not None:
                issues.append("출금과 입금이 한 행에 함께 있습니다")
            elif debit is None and credit is None:
                issues.append("금액이 없거나 0입니다")
            else:
                parsed.update(kind="expense" if debit is not None else "income", amount=debit if debit is not None else credit)
    except ValueError as exc:
        issues.append(str(exc))
    description = (raw.get(m.description) or "").strip() if m.description else ""
    if len(description) > 200:
        issues.append("적요는 200자까지 저장합니다")
    parsed["description"] = description or None
    category = (raw.get(m.category) or "").strip() if m.category else ""
    if len(category) > 64:
        issues.append("분류는 64자까지 저장합니다")
    parsed["csv_category"] = category or None
    return parsed, issues


def preview(session: Session, body: CashflowImportInput) -> dict:
    rules = _rules(session)
    excluded = set(body.exclude_rows)
    parsed_rows = []
    for number, raw in enumerate(_read(body), start=1):
        parsed, issues = _parse_row(body, raw)
        override = body.category_overrides.get(number)
        if override is not None:
            override = override.strip()
            if len(override) > 64:
                issues.append("분류는 64자까지 저장합니다")
        if override:
            category, source = override, "override"
        elif override == "":
            category, source = None, "override"  # explicitly uncategorised
        elif parsed["csv_category"]:
            category, source = parsed["csv_category"], "csv"
        else:
            category = suggest_category(rules, parsed["description"])
            source = "rule" if category else None
        parsed_rows.append({"row": number, "parsed": parsed, "issues": issues, "category": category, "source": source})

    # Identities count repeats in the whole file, excluded rows included, so excluding a row
    # never shifts the identity of another.
    seen: Counter = Counter()
    for item in parsed_rows:
        p = item["parsed"]
        item["ref"] = None
        if not item["issues"]:
            key = (p["occurred_on"], p["kind"], p["amount"], p["description"])
            item["ref"] = _source_ref(body.source_id, *key, seen[key])
            seen[key] += 1

    refs = [item["ref"] for item in parsed_rows if item["ref"]]
    mappings = {m.source_ref: m.record_id for m in session.scalars(
        select(FinanceImportMapping).where(FinanceImportMapping.source_ref.in_(refs)))} if refs else {}
    alive = set(session.scalars(select(CashflowEntry.id).where(CashflowEntry.id.in_(mappings.values())))) if mappings else set()

    valid_dates = [i["parsed"]["occurred_on"] for i in parsed_rows if i["ref"]]
    stored: Counter = Counter()
    if valid_dates:
        for entry in session.scalars(select(CashflowEntry).where(
                CashflowEntry.occurred_on >= min(valid_dates), CashflowEntry.occurred_on <= max(valid_dates))):
            stored[(entry.occurred_on, entry.kind, entry.amount)] += 1

    rows = []
    for item in parsed_rows:
        p, ref = item["parsed"], item["ref"]
        if item["row"] in excluded:
            status = "excluded"
        elif ref in mappings:
            status = "existing" if mappings[ref] in alive else "deleted"
        else:
            status = "new"
        if status == "existing":
            stored[(p["occurred_on"], p["kind"], p["amount"])] -= 1
        rows.append({**item, "status": status})
    for item in rows:
        p = item["parsed"]
        key = (p["occurred_on"], p["kind"], p["amount"])
        item["possible_duplicate"] = item["status"] == "new" and item["ref"] is not None and stored[key] > 0
        if item["possible_duplicate"]:
            stored[key] -= 1

    result_rows = [{
        "row": item["row"], "occurred_on": item["parsed"]["occurred_on"], "kind": item["parsed"]["kind"],
        "amount": item["parsed"]["amount"], "currency": CURRENCY, "description": item["parsed"]["description"],
        "category": item["category"], "category_source": item["source"], "status": item["status"],
        "possible_duplicate": item["possible_duplicate"], "issues": item["issues"], "_ref": item["ref"],
    } for item in rows]
    counts = Counter(r["status"] for r in result_rows)
    counts["issues"] = sum(1 for r in result_rows if r["issues"] and r["status"] != "excluded")
    counts["possible_duplicate"] = sum(1 for r in result_rows if r["possible_duplicate"])
    coverage = _coverage([r["occurred_on"] for r in result_rows if r["status"] != "excluded" and r["_ref"]])
    return {"rows": result_rows, "coverage": coverage, "counts": dict(counts)}


def public_preview(session: Session, body: CashflowImportInput) -> dict:
    result = preview(session, body)
    for row in result["rows"]:
        row.pop("_ref")
    return result


def _remember(session: Session, description: str, category: str) -> bool:
    key = description.strip().casefold()[:200]
    rule = session.scalar(select(CashflowCategoryRule).where(
        CashflowCategoryRule.match_kind == "equals", CashflowCategoryRule.match_text == key))
    if rule is None:
        session.add(CashflowCategoryRule(match_text=key, match_kind="equals", category=category))
        return True
    rule.category = category
    return False


def commit(session: Session, body: CashflowImportInput) -> dict:
    result = preview(session, body)
    rows = result["rows"]
    if any(r["issues"] for r in rows if r["status"] != "excluded"):
        raise ValueError("문제가 있는 행을 고치거나 제외한 뒤 가져오세요")
    imported = rules_created = 0
    remember = set(body.remember_rows)
    try:
        for row in rows:
            if row["status"] == "new":
                entry = CashflowEntry(occurred_on=row["occurred_on"], kind=row["kind"], amount=row["amount"],
                                      currency=CURRENCY, category=row["category"], description=row["description"])
                session.add(entry)
                session.flush()
                session.add(FinanceImportMapping(source_ref=row["_ref"], table_name=TABLE, record_id=entry.id))
                imported += 1
            if (row["row"] in remember and row["status"] != "excluded" and row["description"]
                    and row["category_source"] == "override" and row["category"]):
                rules_created += _remember(session, row["description"], row["category"])
        counts = result["counts"]
        audit_log_handler.record(session, "user", "data.import", f"cashflow-entries:csv:{body.source_id}"[:80],
                                 {"financial": True, "imported": imported, "existing": counts.get("existing", 0),
                                  "excluded": counts.get("excluded", 0)})
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise RuntimeError("같은 파일을 동시에 가져오고 있습니다. 다시 미리보기 하세요") from exc
    counts = result["counts"]
    return {"imported": imported, "existing": counts.get("existing", 0), "deleted": counts.get("deleted", 0),
            "excluded": counts.get("excluded", 0), "rules_created": rules_created, "coverage": result["coverage"]}


def get_presets(session: Session) -> dict:
    stored = app_setting_handler.get_value(session, PRESETS_KEY) or {}
    return CashflowImportPresets.model_validate(stored).model_dump(mode="json")


def save_presets(session: Session, body: CashflowImportPresets) -> dict:
    names = [p.name for p in body.presets]
    if len(names) != len(set(names)):
        raise ValueError("같은 이름의 형식이 있습니다")
    app_setting_handler.set_value(session, PRESETS_KEY, body.model_dump(mode="json"))
    session.commit()
    return body.model_dump(mode="json")


def list_rules(session: Session) -> list[CashflowCategoryRule]:
    return list(session.scalars(select(CashflowCategoryRule).order_by(CashflowCategoryRule.match_text)))


def create_rule(session: Session, body: CashflowCategoryRuleCreate) -> CashflowCategoryRule:
    key = body.match_text.strip().casefold()
    if not key:
        raise ValueError("규칙 문구가 비어 있습니다")
    rule = session.scalar(select(CashflowCategoryRule).where(
        CashflowCategoryRule.match_kind == body.match_kind, CashflowCategoryRule.match_text == key))
    if rule is None:
        rule = CashflowCategoryRule(match_text=key, match_kind=body.match_kind, category=body.category.strip())
        session.add(rule)
    else:
        rule.category = body.category.strip()
    session.commit()
    return rule


def delete_rule(session: Session, rule_id: int) -> None:
    rule = session.get(CashflowCategoryRule, rule_id)
    if rule is None:
        raise LookupError("규칙을 찾을 수 없습니다")
    session.delete(rule)
    session.commit()
