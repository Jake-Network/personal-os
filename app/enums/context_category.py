from enum import StrEnum


class Category(StrEnum):
    FINANCIAL = "financial"
    INVESTMENT = "investment"
    CAREER = "career"
    CALENDAR = "calendar"
    HEALTH = "health"
    GOALS = "goals"
    PROFILE = "profile"


ALL_CATEGORIES: tuple[Category, ...] = tuple(Category)
