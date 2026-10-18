from sqlalchemy import update
from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import ProposedAction


class ProposedActionHandler(BaseCRUDHandler[ProposedAction]):
    def __init__(self):
        super().__init__(ProposedAction)

    def get_by_status(self, session: Session, status: str) -> list[ProposedAction]:
        return self.get_multiple_with_filters(session, [ProposedAction.status == status], [ProposedAction.id])

    def transition(self, session: Session, proposal_id: int, from_status: str, to_status: str,
                   values: dict | None = None) -> bool:
        """Compare-and-set the status in one UPDATE; True only for the request that won."""
        result = session.execute(
            update(ProposedAction)
            .where(ProposedAction.id == proposal_id, ProposedAction.status == from_status)
            .values(status=to_status, **(values or {}))
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            # Refresh the identity-map copy so the caller sees the new status.
            proposal = session.get(ProposedAction, proposal_id)
            if proposal is not None:
                session.refresh(proposal)
        return result.rowcount == 1


proposed_action_handler = ProposedActionHandler()
