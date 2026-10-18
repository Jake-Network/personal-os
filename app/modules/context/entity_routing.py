"""Route mentions of registered positions without loading balances or credentials."""
import re

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.enums.context_category import Category
from app.modules.database.model.domain import Holding
from app.modules.database.model.google_oauth import GoogleOAuthConnection
from app.modules.database.model.portfolio import PortfolioImport, PortfolioSettings


_PARTICLES = "(?:은|는|이|가|을|를|의|와|과|도|만|에|에서|에게|으로|로|보다|랑|이랑)"
_BOUNDARY = r"(?=$|[^\w]|" + _PARTICLES + r"(?=$|[^\w]))"


def _matched(query: str, terms) -> tuple[str, ...]:
    hits = []
    for term in terms:
        if not isinstance(term, str) or not term.strip():
            continue
        pattern = r"(?<!\w)" + re.escape(term.strip()) + _BOUNDARY
        match = re.search(pattern, query, re.IGNORECASE)
        if match and match.group() not in hits:
            hits.append(match.group())
    return tuple(hits)


def _sheets_terms(session: Session, spreadsheet_id: str):
    # Match the identity rules of portfolio_manager._latest, selecting no tokens.
    from app.modules.auth.google_oauth_manager import google_oauth_manager

    connection = session.execute(select(GoogleOAuthConnection.subject, GoogleOAuthConnection.status)
                                 .where(GoogleOAuthConnection.id == 1)).first()
    if connection:
        if connection.status != "connected":
            return []
        identity = f"oauth:{connection.subject or 'disconnected'}:{google_oauth_manager.settings.google_oauth_client_id}"
    else:
        identity = "adc"
    identity_filter = PortfolioImport.source_identity == identity
    if identity == "adc":
        identity_filter = or_(identity_filter, PortfolioImport.source_identity.is_(None))
    import_id = session.scalar(select(PortfolioImport.id)
                               .where(PortfolioImport.spreadsheet_id == spreadsheet_id, identity_filter)
                               .order_by(PortfolioImport.id.desc()).limit(1))
    if import_id is None:
        return []
    # Project only label/ticker inside the DB; imports can contain large financial JSON.
    if session.bind.dialect.name == "postgresql":
        statement = """SELECT item->>'ticker', item->>'label'
            FROM portfolio_imports, json_array_elements(payload->'Holdings') AS item
            WHERE portfolio_imports.id = :import_id"""
    else:
        statement = """SELECT json_extract(item.value, '$.ticker'), json_extract(item.value, '$.label')
            FROM portfolio_imports, json_each(portfolio_imports.payload, '$.Holdings') AS item
            WHERE portfolio_imports.id = :import_id"""
    return [term for row in session.execute(text(statement), {"import_id": import_id}) for term in row]


def matched_investment_terms(
    session: Session,
    query: str,
    excluded: frozenset[Category] = frozenset(),
    override: frozenset[Category] | None = None,
) -> tuple[str, ...]:
    """Return mentioned registered symbols/names, respecting the sharing allowlist."""
    if not query.strip() or Category.INVESTMENT in excluded:
        return ()
    if override is not None and Category.INVESTMENT not in override:
        return ()
    terms = [term for row in session.execute(select(Holding.symbol, Holding.name)) for term in row]
    return _matched(query, terms)
