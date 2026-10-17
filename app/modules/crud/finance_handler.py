from datetime import date

from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import (
    Account,
    CashflowEntry,
    FxRate,
    Holding,
    Liability,
    OtherAsset,
    PlannedExpense,
)


class AccountHandler(BaseCRUDHandler[Account]):
    def __init__(self):
        super().__init__(Account)

    def get_all(self, session: Session) -> list[Account]:
        return self.get_multiple_with_filters(session, order_by=[Account.id])


class OtherAssetHandler(BaseCRUDHandler[OtherAsset]):
    def __init__(self):
        super().__init__(OtherAsset)

    def get_all(self, session: Session) -> list[OtherAsset]:
        return self.get_multiple_with_filters(session, order_by=[OtherAsset.id])


class LiabilityHandler(BaseCRUDHandler[Liability]):
    def __init__(self):
        super().__init__(Liability)

    def get_all(self, session: Session) -> list[Liability]:
        return self.get_multiple_with_filters(session, order_by=[Liability.id])


class HoldingHandler(BaseCRUDHandler[Holding]):
    def __init__(self):
        super().__init__(Holding)

    def get_all(self, session: Session) -> list[Holding]:
        return self.get_multiple_with_filters(session, order_by=[Holding.id])

    def get_priced(self, session: Session) -> list[Holding]:
        return self.get_multiple_with_filters(session, [Holding.last_price.is_not(None)], [Holding.id])


class FxRateHandler(BaseCRUDHandler[FxRate]):
    def __init__(self):
        super().__init__(FxRate)

    def get_latest_first(self, session: Session) -> list[FxRate]:
        return self.get_multiple_with_filters(session, order_by=[FxRate.as_of.desc()])


class CashflowEntryHandler(BaseCRUDHandler[CashflowEntry]):
    def __init__(self):
        super().__init__(CashflowEntry)

    def get_since(self, session: Session, since: date) -> list[CashflowEntry]:
        return self.get_multiple_with_filters(session, [CashflowEntry.occurred_on >= since],
                                              [CashflowEntry.occurred_on])


class PlannedExpenseHandler(BaseCRUDHandler[PlannedExpense]):
    def __init__(self):
        super().__init__(PlannedExpense)

    def get_upcoming(self, session: Session, today: date) -> list[PlannedExpense]:
        return self.get_multiple_with_filters(session, [PlannedExpense.due_on >= today], [PlannedExpense.due_on])


account_handler = AccountHandler()
other_asset_handler = OtherAssetHandler()
liability_handler = LiabilityHandler()
holding_handler = HoldingHandler()
fx_rate_handler = FxRateHandler()
cashflow_entry_handler = CashflowEntryHandler()
planned_expense_handler = PlannedExpenseHandler()
