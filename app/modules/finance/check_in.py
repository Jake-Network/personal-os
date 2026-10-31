"""Several account balances in one go, each saved or refused on its own.

Each item carries the version the user saw. A balance changed elsewhere since then is
refused for that account only; the others still save. Every change goes through the
append-only value history like a single edit.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.crud import audit_log_handler
from app.modules.database.model import Account
from app.modules.database.model.base import utcnow
from app.modules.finance.clock import local_today
from app.modules.finance.value_history import capture
from app.modules.finance.value_history_manager import value_history_manager
from app.schema.cashflow_import_schema import BalanceCheckInInput


def check_in(session: Session, body: BalanceCheckInInput) -> list[dict]:
    if len({item.account_id for item in body.items}) != len(body.items):
        raise ValueError("같은 계좌가 두 번 들어 있습니다")
    today = local_today()
    results = []
    for item in body.items:
        with session.begin_nested():
            account = session.scalar(select(Account).where(Account.id == item.account_id).with_for_update())
            if account is None:
                results.append({"account_id": item.account_id, "status": "not_found", "message": "계좌를 찾을 수 없습니다"})
                continue
            if account.updated_at != item.expected_version:
                results.append({"account_id": item.account_id, "status": "conflict",
                                "message": "다른 화면에서 바뀐 계좌입니다. 최신 값을 확인한 뒤 다시 입력하세요"})
                continue
            before = capture("accounts", account)
            changed = item.balance is not None and item.balance != account.balance
            if changed:
                account.balance = item.balance
            account.balance_as_of = today
            account.updated_at = utcnow()
            session.flush()
            value_history_manager.record(session, "accounts", account, before, "update", today=today)
            audit_log_handler.record(session, "user", "data.update" if changed else "data.confirm_value",
                                     f"accounts:{account.id}", {"financial": True, "source": "balance_check_in"})
            results.append({"account_id": account.id, "status": "updated" if changed else "confirmed",
                            "message": "잔액을 저장했습니다" if changed else "오늘 기준으로 확인했습니다"})
    session.commit()
    return results
