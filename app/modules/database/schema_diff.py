"""Readable differences between two table/column schemas."""

from app.modules.database.types import Schema


def schema_differences(expected: Schema, actual: Schema) -> list[str]:
    out = [f"missing table {t}" for t in sorted(expected.keys() - actual.keys())]
    out += [f"unexpected table {t}" for t in sorted(actual.keys() - expected.keys())]
    for t in sorted(expected.keys() & actual.keys()):
        out += [f"{t}: missing column {c}" for c in sorted(expected[t] - actual[t])]
        out += [f"{t}: unexpected column {c}" for c in sorted(actual[t] - expected[t])]
    return out
