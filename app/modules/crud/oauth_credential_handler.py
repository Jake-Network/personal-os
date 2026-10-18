from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import OAuthCredential


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


oauth_credential_handler = OAuthCredentialHandler()
