"""User-requested undo of one saved consultation write, identified by its receipt.

Only a record that nobody changed since the consultation saved it is undone: a created
record is deleted, an updated one gets its previous values back. Both go through the same
value history (append-only) and audit log as a direct edit, and the receipt is marked so
the undo cannot run twice. Deletions are not undone here; they are restored by re-entering.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.crud import audit_log_handler
from app.modules.database.model import AuditLog, LocalPosition
from app.modules.database.model.base import utcnow
from app.modules.finance.clock import local_today
from app.modules.finance.value_history import capture, split_history_fields, tracks
from app.modules.finance.value_history_manager import value_history_manager
from app.modules.personal_data.personal_data_manager import RESOURCES


def undo(session: Session, receipt_id: int) -> dict:
    receipt = session.scalar(select(AuditLog).where(AuditLog.id == receipt_id).with_for_update())
    if receipt is None or receipt.action != "advisor.data_command":
        raise LookupError("되돌릴 상담 기록을 찾을 수 없습니다")
    detail = receipt.detail or {}
    if detail.get("undone_at"):
        raise RuntimeError("이미 되돌린 기록입니다")
    result = detail.get("result") or {}
    name, operation = result.get("resource"), result.get("operation")
    resource = RESOURCES.get(name)
    if resource is None or operation not in {"create", "update"} or result.get("status") != "saved":
        raise ValueError("이 작업은 되돌릴 수 없습니다")
    model = resource.handler.model
    obj = session.scalar(select(model).where(model.id == result.get("record_id")).with_for_update())
    if obj is None:
        raise RuntimeError("이미 삭제된 기록입니다")
    saved_version = (result.get("record") or {}).get("version")
    if saved_version is None or obj.updated_at is None or obj.updated_at.isoformat() != saved_version:
        raise RuntimeError("상담에서 저장한 뒤 다시 바뀐 기록이라 되돌리지 않습니다. 관리 화면에서 직접 고쳐 주세요")

    if operation == "create":
        if tracks(name):
            value_history_manager.record(session, name, obj, capture(name, obj), "delete", today=local_today())
        resource.handler.delete(session, obj)
    else:
        previous = detail.get("previous")
        if not previous:
            raise ValueError("이전 값이 기록되지 않은 작업이라 되돌릴 수 없습니다")
        fields = resource.create_schema.model_fields
        body = resource.create_schema.model_validate({key: previous[key] for key in fields if key in previous})
        data, _ = split_history_fields(name, body)
        before = capture(name, obj) if tracks(name) else None
        resource.handler.update(session, obj, data)
        if before is not None:
            value_history_manager.record(session, name, obj, before, "update", today=local_today())
        if name == "holdings":
            from app.modules.portfolio.holdings_manager import version
            mapping = session.scalar(select(LocalPosition).where(LocalPosition.holding_id == obj.id).with_for_update())
            if mapping is not None:
                mapping.version = version(obj)
    receipt.detail = {**detail, "undone_at": utcnow().isoformat()}
    audit_log_handler.record(session, "user", "advisor.data_command_undo", f"audit_log:{receipt.id}",
                             {"financial": resource.financial, "operation": operation, "resource": name})
    session.commit()
    return {"receipt_id": receipt.id, "operation": operation, "resource": name, "record_id": result["record_id"]}


def undone_receipts(session: Session, receipt_ids: set[int]) -> set[int]:
    if not receipt_ids:
        return set()
    rows = session.scalars(select(AuditLog).where(AuditLog.id.in_(receipt_ids), AuditLog.action == "advisor.data_command"))
    return {row.id for row in rows if (row.detail or {}).get("undone_at")}
