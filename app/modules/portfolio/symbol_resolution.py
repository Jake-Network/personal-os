"""Qualify existing local positions using public listing identity only.

Like quote refresh, this operation explicitly commits before external I/O and after
its separately audited update. Call it before taking a quote-refresh/run write
fence; lookup authorization callbacks release their own locks. The separate write
authorization callback retains its fence through the symbol update and commit.
No amount, quantity, cost, account or historical observation is rewritten.
"""
from __future__ import annotations

import re

from sqlalchemy import select

from app.modules.database.model import AuditLog, Holding, LocalPosition
from app.modules.portfolio.holdings_manager import version
from app.modules.portfolio.symbol_directory import symbol_directory

_BARE = re.compile(r'[A-Z][A-Z0-9.-]{0,30}')
_QUALIFIED = re.compile(r'(?:NASDAQ|NYSE|NYSEARCA|NYSEAMERICAN):([A-Z][A-Z0-9.-]{0,30})')
_STATUSES = frozenset({'resolved', 'not_found', 'ambiguous', 'unavailable', 'unsupported'})


def _sharing_allowed(session, row, excluded, *, advisory):
    if not advisory:
        return True
    from app.modules.context.privacy_manager import privacy_manager
    from app.modules.context.source_policy import source_allowed
    categories = {str(value) for value in excluded} | {str(value) for value in privacy_manager.get_excluded(session)}
    refs = [{'table': 'holdings', 'id': row.id}]
    if row.account_id is not None:
        refs.append({'table': 'accounts', 'id': row.account_id})
    return source_allowed(session, refs, categories)


def qualify_positions(session, *, directory=None, authorization_check=None,
                      write_authorization_check=None, excluded=()) -> list[dict]:
    """Resolve unchanged USD auto-quote positions, preserving each local position.

    Directory I/O sees only public symbols through its local lookup API; its HTTP
    implementation fetches whole fixed public files. ``excluded`` is relevant to
    advisor calls; local finance refresh remains available for local-only records.
    ``write_authorization_check`` runs in the final write transaction and must not
    commit: its run fence remains held through the symbol/audit commit.
    A stale/deleted position is skipped, never merged with another account's row.
    """
    directory = directory or symbol_directory
    excluded = frozenset(str(value) for value in excluded)
    advisory = authorization_check is not None or write_authorization_check is not None or bool(excluded)
    if authorization_check:
        authorization_check()
    rows = session.execute(select(Holding, LocalPosition).join(
        LocalPosition, LocalPosition.holding_id == Holding.id
    ).where(Holding.currency == 'USD', LocalPosition.quote_mode == 'auto',
            ~Holding.symbol.contains(':')).order_by(Holding.id)).all()
    snapshots, result = [], []
    for row, mapping in rows:
        if not _BARE.fullmatch(row.symbol.strip().upper()):
            continue
        if not _sharing_allowed(session, row, excluded, advisory=advisory):
            result.append({'status': 'sharing_excluded', 'record_id': row.id, 'position_id': mapping.position_id})
            continue
        snapshots.append({'record_id': row.id, 'position_id': mapping.position_id,
            'previous_symbol': row.symbol, 'currency': row.currency, 'account_id': row.account_id,
            'holding_version': version(row), 'mapping_version': mapping.version})
    session.commit()  # Never retain caller/read/fence locks across directory HTTP.
    resolved = {}
    for snapshot in snapshots:
        if authorization_check:
            authorization_check()
            session.commit()
        key = (snapshot['previous_symbol'], snapshot['currency'])
        if key not in resolved:
            response = directory.resolve(*key)
            if not isinstance(response, dict) or response.get('status') not in _STATUSES:
                response = {'status': 'unavailable'}
            response = dict(response)
            if response['status'] == 'resolved':
                qualified = response.get('symbol')
                match = _QUALIFIED.fullmatch(qualified) if isinstance(qualified, str) else None
                if (not match or match[1] != snapshot['previous_symbol'].strip().upper()
                        or response.get('source') != 'nasdaq_trader'):
                    response = {'status': 'unavailable'}
            resolved[key] = response
    try:
        if write_authorization_check:
            write_authorization_check()
        elif authorization_check:
            authorization_check()
        session.expire_all()
        for snapshot in snapshots:
            key = (snapshot['previous_symbol'], snapshot['currency'])
            response = resolved[key]
            identity = {'record_id': snapshot['record_id'], 'position_id': snapshot['position_id']}
            current = session.execute(select(Holding, LocalPosition).join(
                LocalPosition, LocalPosition.holding_id == Holding.id
            ).where(Holding.id == snapshot['record_id'], LocalPosition.position_id == snapshot['position_id'])
                .with_for_update().execution_options(populate_existing=True)).first()
            if current is None:
                result.append({**identity, 'status': 'stale'})
                continue
            row, mapping = current
            if not _sharing_allowed(session, row, excluded, advisory=advisory):
                result.append({**identity, 'status': 'sharing_excluded'})
                continue
            if (row.account_id != snapshot['account_id'] or row.currency != snapshot['currency']
                    or row.symbol != snapshot['previous_symbol'] or mapping.quote_mode != 'auto'
                    or mapping.version != snapshot['mapping_version'] or version(row) != snapshot['holding_version']):
                result.append({**identity, 'status': 'stale'})
                continue
            receipt = {**identity, 'status': response['status'], 'previous_symbol': row.symbol,
                'symbol': response.get('symbol'), 'candidates': response.get('candidates', []),
                'source': response.get('source', 'nasdaq_trader'), 'as_of': response.get('as_of')}
            if response['status'] == 'resolved':
                row.symbol = response['symbol']
                session.flush()
                mapping.version = version(row)
                session.add(AuditLog(actor='system', action='holding.symbol.resolve', target=f'holdings:{row.id}',
                    detail={'previous_symbol': snapshot['previous_symbol'], 'symbol': row.symbol,
                            'source': response['source'], 'as_of': response.get('as_of')}))
            result.append(receipt)
        session.commit()
        return result
    except BaseException:
        session.rollback()
        raise
