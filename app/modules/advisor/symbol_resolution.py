"""Qualify current-user holding inputs with public listing evidence before a write."""
import asyncio
import re

from app.modules.portfolio.symbol_directory import symbol_directory


async def resolve_command_symbol(command, query):
    if command.get('resource') != 'holdings' or command.get('operation') != 'create':
        return command
    values = command.get('values', {})
    symbol = values.get('symbol', values.get('ticker'))
    if not isinstance(symbol, str):
        return command
    symbol = symbol.upper().strip()
    bare = symbol.rsplit(':', 1)[-1]
    # An explicit exchange chosen by the user remains their choice. A model's
    # added prefix has no authority; verify that prefix against the directory.
    if ':' in symbol and re.search(r'(?<![A-Za-z0-9.:-])' + re.escape(symbol) + r'(?![A-Za-z0-9.:-])', query, re.I):
        return command
    fields = dict(values)
    fields.pop('ticker', None)
    fields['symbol'] = bare
    if values.get('currency', 'USD') != 'USD':
        return {**command, 'values': fields}
    result = await asyncio.to_thread(symbol_directory.resolve, bare, 'USD')
    resolved = result.get('symbol')
    if (result.get('status') == 'resolved' and isinstance(resolved, str) and
            resolved.rsplit(':', 1)[-1] == bare):
        fields.pop('ticker', None)
        fields['symbol'] = resolved
        fields.setdefault('currency', 'USD')
    return {**command, 'values': fields, 'symbol_resolution': result}
