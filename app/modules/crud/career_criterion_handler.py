from sqlalchemy.orm import Session

from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import CareerCriterion


class CareerCriterionHandler(BaseCRUDHandler[CareerCriterion]):
    def __init__(self):
        super().__init__(CareerCriterion)

    def get_by_weight(self, session: Session) -> list[CareerCriterion]:
        return self.get_multiple_with_filters(session, order_by=[CareerCriterion.weight.desc(), CareerCriterion.id])


career_criterion_handler = CareerCriterionHandler()
