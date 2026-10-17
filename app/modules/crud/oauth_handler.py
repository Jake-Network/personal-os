from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import OAuthConnection, OAuthCredential


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


class OAuthCredentialHandler(BaseCRUDHandler[OAuthCredential]):
    def __init__(self):
        super().__init__(OAuthCredential)

    def upsert(self, session: Session, connection_id: int, ciphertext: bytes) -> None:
        cred = self.get(session, connection_id)
        if cred is None:
            session.add(OAuthCredential(connection_id=connection_id, ciphertext=ciphertext))
        else:
            cred.ciphertext = ciphertext
        session.flush()


oauth_connection_handler = OAuthConnectionHandler()
oauth_credential_handler = OAuthCredentialHandler()
