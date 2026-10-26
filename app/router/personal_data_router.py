"""CRUD endpoints for personal data, one set per resource in RESOURCES."""

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.modules.database import get_session
from app.modules.finance.value_history import tracks
from app.modules.finance.value_history_manager import value_history_manager
from app.modules.personal_data.personal_data_manager import RESOURCES, Resource, personal_data_manager
from app.schema import domain_schema as s

router = APIRouter(prefix="/api/data", tags=["personal-data"])


def _check_sheet_ownership(session: Session, name: str) -> None:
    # Google supplies public quotes only; personal data remains locally editable.
    return


def _register(name: str, res: Resource) -> None:
    Create, Item = res.create_schema, res.item_schema

    def _get(session: Session, item_id: int):
        try:
            return personal_data_manager.get(session, res, item_id)
        except LookupError as exc:
            raise HTTPException(404, f"{name}:{item_id} not found") from exc

    @router.get(f"/{name}", response_model=list[Item], operation_id=f"list_{name}")
    def list_items(session: Session = Depends(get_session)):
        return personal_data_manager.list(session, res)

    if name == "cashflow-entries":
        @router.get(f"/{name}/{{item_id}}", response_model=Item, operation_id=f"get_{name}")
        def get_item(item_id: int, session: Session = Depends(get_session)):
            return _get(session, item_id)

    @router.post(f"/{name}", response_model=Item, status_code=201, operation_id=f"create_{name}")
    def create_item(body: Create = Body(...), session: Session = Depends(get_session)):  # type: ignore[valid-type]
        _check_sheet_ownership(session, name)
        try:
            return personal_data_manager.create(session, name, res, body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.put(f"/{name}/{{item_id}}", response_model=Item, operation_id=f"update_{name}")
    def update_item(item_id: int, body: Create = Body(...), session: Session = Depends(get_session)):  # type: ignore[valid-type]
        _check_sheet_ownership(session, name)
        _get(session, item_id)
        try:
            return personal_data_manager.update(session, name, res, item_id, body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    if name in {"accounts", "liabilities", "other-assets"}:
        @router.post(f"/{name}/{{item_id}}/confirm-value", response_model=Item,
                     operation_id=f"confirm_value_{name}")
        def confirm_value(item_id: int, body: s.ConfirmValueInput, session: Session = Depends(get_session)):
            _get(session, item_id)
            try:
                return personal_data_manager.confirm_value(session, name, res, item_id, body.expected_version)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc

    if tracks(name):
        @router.get(f"/{name}/{{item_id}}/history", response_model=list[s.ValueChangeItem],
                    operation_id=f"history_{name}")
        def item_history(item_id: int, session: Session = Depends(get_session)):
            """Append-only manual edit history; kept even after the record itself is deleted."""
            return value_history_manager.list(session, name, item_id)

    @router.delete(f"/{name}/{{item_id}}", status_code=204, operation_id=f"delete_{name}")
    def delete_item(item_id: int, session: Session = Depends(get_session)):
        _check_sheet_ownership(session, name)
        _get(session, item_id)
        personal_data_manager.delete(session, name, res, item_id)


for _name, _res in RESOURCES.items():
    _register(_name, _res)
