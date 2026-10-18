from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import OtherAsset


class OtherAssetHandler(BaseCRUDHandler[OtherAsset]):
    def __init__(self):
        super().__init__(OtherAsset)

    def get_all(self, session: Session) -> list[OtherAsset]:
        return self.get_multiple_with_filters(session, order_by=[OtherAsset.id])


other_asset_handler = OtherAssetHandler()
