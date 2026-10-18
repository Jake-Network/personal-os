from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import OAuthConnection


class OAuthConnectionHandler(BaseCRUDHandler[OAuthConnection]):
    def __init__(self):
        super().__init__(OAuthConnection)

    def get_active(self, session: Session, provider: str = "chatgpt") -> OAuthConnection | None:
        return self.get_first_with_filters(
            session,
            [OAuthConnection.provider == provider, OAuthConnection.status != "disconnected"],
            [OAuthConnection.id.desc()],
        )

    def get_latest(self, session: Session, provider: str = "chatgpt") -> OAuthConnection | None:
        """Most recent connection in any status; its issued client_id is reused on re-login."""
        return self.get_first_with_filters(session, [OAuthConnection.provider == provider],
                                           [OAuthConnection.id.desc()])


oauth_connection_handler = OAuthConnectionHandler()
