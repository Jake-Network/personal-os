"""Exact decimal text for financial quantities."""

from decimal import Decimal


def quantity_text(value):
    text = format(Decimal(value), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text
