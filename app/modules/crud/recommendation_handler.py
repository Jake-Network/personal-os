from app.modules.crud.base import BaseCRUDHandler
from app.modules.database.model import AdvisorRecommendation


class RecommendationHandler(BaseCRUDHandler[AdvisorRecommendation]):
    def __init__(self):
        super().__init__(AdvisorRecommendation)


recommendation_handler = RecommendationHandler()
