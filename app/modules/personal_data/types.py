"""Types describing the user-editable personal data resources."""

from dataclasses import dataclass

from pydantic import BaseModel

from app.modules.crud.base import BaseCRUDHandler


@dataclass(frozen=True)
class Resource:
    """One editable resource: its handler, request/response schemas and whether it is financial."""

    handler: BaseCRUDHandler
    create_schema: type[BaseModel]
    item_schema: type[BaseModel]
    financial: bool = False
