"""Bind delta direction to the command's own user-cited target and action."""
import re

from app.modules.advisor.commands.intent import instruction_text

_DECREASE = re.compile(r'팔|매도|출금|줄여|줄어|감소|차감|빼')
_INCREASE = re.compile(r'매수|매입|샀|입금|늘려|늘어|증가|추가|더\s*(?:있|보유|갖)')


def _direction(text):
    decrease, increase = bool(_DECREASE.search(text)), bool(_INCREASE.search(text))
    return (-1 if decrease else 1) if decrease != increase else None


def _clauses(text):
    return re.split(r'하고|그리고|[,;\n!?。]|\.(?=\s|$)', text)


def bind_visible_delta_target(session, command, excluded):
    """Resolve opaque selectors without revealing hidden/missing record identity.

    The caller uses this copy only for validation, and retains the canonical
    identity in the final write selector only after validation succeeds.
    """
    from app.modules.advisor.commands.execution import _matches, _visible, CommandInputError, DELTA_FIELDS
    from app.modules.personal_data.personal_data_manager import RESOURCES
    name = command.get('resource')
    resource = RESOURCES.get(name)
    if name not in DELTA_FIELDS or resource is None or command.get('operation') != 'update':
        return None
    try:
        rows = _matches(session, resource, command.get('selector', {}))
    except CommandInputError:
        return None
    visible = [row for row in rows if _visible(session, resource, row, excluded)]
    if not visible:
        return None
    field = 'symbol' if name == 'holdings' else 'name'
    identities = {getattr(row, field, None) for row in visible}
    if len(identities) != 1:
        # A named ambiguous target remains a service clarification; an opaque ID
        # cannot provide any target authority by itself.
        return command if command.get('selector', {}).get(field) else None
    identity = next(iter(identities))
    if not isinstance(identity, str) or not identity:
        return None
    return {**command, 'selector': {**command.get('selector', {}), field: identity}}


def delta_direction(command, source_quote, *, original_query=None, followup=False):
    """Reject target mismatch and ambiguous mixed actions; never waive sign checks."""
    quote = instruction_text(source_quote)
    original = instruction_text(original_query or '')
    selector, values = command.get('selector', {}), command.get('values', {})
    identity = selector.get('symbol', selector.get('ticker', values.get('symbol', values.get('ticker'))))
    if not identity:
        identity = selector.get('name', values.get('name'))
    if not isinstance(identity, str) or not identity:
        return None
    bare = identity.rsplit(':', 1)[-1]
    pattern = re.compile(r'(?<![A-Za-z0-9_.:-])(?:(?P<exchange>[A-Za-z][A-Za-z0-9]*):)?' + re.escape(bare)
                         + r'(?=$|[^A-Za-z0-9_.:-]|\d+(?:\.\d+)?\s*주)', re.I)
    own = [clause for clause in _clauses(quote) if pattern.search(clause)]
    prior = [clause for clause in _clauses(original) if pattern.search(clause)]
    quoted_action = bool(_DECREASE.search(quote) or _INCREASE.search(quote))
    if quoted_action:
        # A short citation may omit its subject, but must occur inside this exact
        # target's original clause. Another named ticker's excerpt never binds.
        located = [clause for clause in prior if quote.strip() in clause.strip()]
        if len(own) == 1 and _direction(own[0]) is not None:
            scope = own[0]
        elif len(located) == 1:
            scope = located[0]
        elif len(own) == 1:
            scope = own[0]
        else:
            return None
    elif followup and len(prior) == 1:
        scope = prior[0]
    elif len(own) == 1:
        scope = own[0]
    else:
        return None
    namespace_scopes = [scope, *(located if quoted_action else [])]
    exchanges = {match['exchange'].upper() for text in namespace_scopes
                 for match in pattern.finditer(text) if match['exchange']}
    requested = identity.rsplit(':', 1)[0].upper() if ':' in identity else None
    if requested and exchanges and exchanges != {requested}:
        return None
    if _DECREASE.search(scope) and _INCREASE.search(scope):
        return None
    own_direction = _direction(scope)
    if own_direction is not None:
        return own_direction
    # Common list-wide "이것도 추가로 저장해줘" can qualify a row without
    # its own verb only if no other named trade/account supplies that direction.
    all_text = original if followup else quote
    for clause in _clauses(all_text):
        if clause == scope or _direction(clause) is None:
            continue
        symbols = set(re.findall(r'(?<![A-Za-z0-9_.:-])(?:[A-Z][A-Z0-9]*:)?[A-Z][A-Z0-9_.-]*', clause))
        if symbols - {'USD', 'KRW', 'EUR', 'JPY'} or re.search(r'계좌|통장', clause):
            return None
    return _direction(all_text)
