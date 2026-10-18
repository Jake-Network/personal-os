"""Scenario arithmetic; missing inputs stay unavailable and assumptions stay labelled."""
from decimal import Decimal, InvalidOperation
from copy import deepcopy
import hashlib
import json

from app.modules.finance.financial_calculator import financial_calculator

CALCULATION_VERSION = 'scenario-decimal-v1'


def _dependency_hash(inputs):
    return hashlib.sha256(json.dumps({'calculation_version': CALCULATION_VERSION, 'inputs': inputs},
                                    sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _reuse(previous, component, inputs):
    digest = _dependency_hash(inputs)
    old = previous.get(component)
    if isinstance(old, dict) and old.get('dependency_hash') == digest and old.get('calculation_version') == CALCULATION_VERSION:
        return {**deepcopy(old), 'reused': True}, digest
    return None, digest


def _decimal(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def calculate_scenario(assumptions, baseline, previous_results=None):
    output = {}
    previous = previous_results or {}
    previous = previous.get('server_calculations', previous)
    financial = assumptions.get('financial')
    if isinstance(financial, dict):
        data = baseline.get('data') or {}
        accounts = data.get('get_accounts_summary') or {}
        worth = (accounts.get('computed') or {}).get('net_worth') or {}
        dependencies = {'spendable_liquidity': worth.get('spendable_liquidity'),
            'spendable_liquidity_complete': worth.get('spendable_liquidity_complete', True),
            'currency': worth.get('currency'),
            'monthly_expense': financial.get('monthly_expense'), 'monthly_income': financial.get('monthly_income')}
        reused, digest = _reuse(previous, 'financial', dependencies)
        cash = _decimal(worth.get('spendable_liquidity'))
        expense = _decimal(financial.get('monthly_expense'))
        income = _decimal(financial.get('monthly_income'))
        if reused is not None:
            output['financial'] = reused
        elif cash is None or expense is None or income is None or expense < 0 or income < 0:
            output['financial'] = {'available': False, 'reason': 'spendable_liquidity_or_explicit_assumption_missing'}
        else:
            output['financial'] = {'available': True, **financial_calculator.runway(cash, expense, income),
                'basis': 'current_spendable_liquidity_and_scenario_assumptions', 'computed_by': 'FinancialCalculator',
                'currency': worth.get('currency'),
                'understated': not worth.get('spendable_liquidity_complete', True)}
        output['financial'].update(dependency_hash=digest, calculation_version=CALCULATION_VERSION,
                                   reused=reused is not None, dependencies=dependencies)
    time = assumptions.get('time')
    if isinstance(time, dict):
        values = {key: _decimal(time.get(key)) for key in
                  ('work_hours_per_week', 'rest_hours_per_week', 'committed_hours_per_week', 'required_hours_per_week')}
        dependencies = {key: time.get(key) for key in values}
        reused, digest = _reuse(previous, 'time', dependencies)
        if reused is not None:
            output['time'] = reused
        elif any(value is None or value < 0 for value in values.values()):
            output['time'] = {'available': False, 'reason': 'work_rest_commitment_or_required_hours_missing'}
        else:
            available = Decimal(168) - values['work_hours_per_week'] - values['rest_hours_per_week'] - values['committed_hours_per_week']
            output['time'] = {'available': True, 'available_hours_per_week': str(available),
                'required_hours_per_week': str(values['required_hours_per_week']),
                'margin_hours_per_week': str(available - values['required_hours_per_week']),
                'feasible_under_assumptions': available >= values['required_hours_per_week'],
                'basis': 'explicit_scenario_assumptions', 'computed_by': 'backend_decimal_time_constraints'}
        output['time'].update(dependency_hash=digest, calculation_version=CALCULATION_VERSION,
                              reused=reused is not None, dependencies=dependencies)
    return output
