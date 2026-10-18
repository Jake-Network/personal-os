"""No collation mismatch is silently acknowledged or repaired at startup."""
from types import SimpleNamespace
import pytest
from app.modules.database.collation import check_collations, collation_mismatches


class FakeConnection:
    dialect = SimpleNamespace(name='postgresql')
    def __init__(self, database, explicit=()):
        self.results = iter((database, explicit))
        self.statements = []
    def execute(self, statement):
        self.statements.append(str(statement))
        rows = next(self.results)
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))


@pytest.mark.parametrize('stored,actual', [('2.36','2.41'), (None,'2.41'), ('2.41',None)])
def test_changed_or_unrecorded_provider_refused_without_reindex_or_refresh(stored, actual):
    connection = FakeConnection([{'name':'app','stored':stored,'actual':actual}])
    with pytest.raises(RuntimeError, match='Rebuild affected indexes before refreshing'):
        check_collations(connection)
    assert all(statement.lstrip().startswith('SELECT') for statement in connection.statements)


def test_explicit_used_collation_is_checked_and_stable_c_is_allowed():
    connection = FakeConnection([{'name':'app','stored':None,'actual':None}],
                                [{'name':'public.locale','stored':'old','actual':'new'}])
    assert collation_mismatches(connection)[0]['name'] == 'public.locale'
    check_collations(FakeConnection([{'name':'app','stored':None,'actual':None}]))
