"""Read-only LangGraph store over confirmed app memories and their revisions.

The request owns the session. No checkpoint or model tool can mutate a memory.
Every operation observes the current sharing policy, including document scope.
"""
from datetime import UTC, datetime

from langgraph.store.base import BaseStore, GetOp, Item, ListNamespacesOp, SearchItem, SearchOp

from app.enums.context_category import ALL_CATEGORIES
from app.modules.context.memory_selection import relevant_memories
from app.modules.context.privacy_manager import privacy_manager
from app.modules.context.source_policy import source_allowed
from app.modules.database.model import PersonalMemory


class ConfirmedMemoryStore(BaseStore):
    namespace = ("personal", "confirmed_memories")

    def __init__(self, session, *, allowed=None, document_scope=None, at=None, request_query=None):
        self.session = session
        self.allowed = frozenset(ALL_CATEGORIES) if allowed is None else frozenset(allowed)
        self.document_scope = document_scope
        self.at = at
        self.request_query = request_query

    def _items(self, query):
        excluded = privacy_manager.get_excluded(self.session) | (frozenset(ALL_CATEGORIES) - self.allowed)
        now = self.at or datetime.now(UTC)
        rows = relevant_memories(self.session, query, frozenset(ALL_CATEGORIES) - excluded, now)
        items = []
        for memory, revision in rows:
            ref = {"table": "memory_revisions" if revision else "personal_memories",
                   "id": revision.id if revision else memory.id}
            if not source_allowed(self.session, [ref], excluded, document_scope=self.document_scope):
                continue
            row = revision or memory
            items.append(Item(namespace=self.namespace, key=str(memory.id),
                value={"id": memory.id, "revision_id": revision.id if revision else None,
                    "kind": row.kind, "content": row.content, "source_reference": ref,
                    "valid_from": revision.valid_from.isoformat() if revision and revision.valid_from else None,
                    "valid_until": revision.valid_until.isoformat() if revision and revision.valid_until else None},
                created_at=row.created_at, updated_at=row.confirmed_at or row.created_at))
        return items

    def batch(self, ops):
        operations = list(ops)
        # Validate the entire batch before reading. Writes are never forwarded.
        if any(not isinstance(op, (GetOp, SearchOp, ListNamespacesOp)) for op in operations):
            raise PermissionError("Confirmed memories require user confirmation and revision checks")
        self.session.expire_all()
        results = []
        for op in operations:
            if isinstance(op, GetOp):
                if op.namespace != self.namespace or not op.key.isdecimal():
                    results.append(None)
                    continue
                memory = self.session.get(PersonalMemory, int(op.key))
                query = self.request_query if self.request_query is not None else (memory.content if memory else "")
                results.append(next((item for item in self._items(query) if item.key == op.key), None))
            elif isinstance(op, SearchOp):
                if self.namespace[:len(op.namespace_prefix)] != op.namespace_prefix:
                    results.append([])
                    continue
                items = [item for item in self._items(op.query or "")
                    if not op.filter or all(item.value.get(k) == v for k, v in op.filter.items())]
                # Mandatory constraints survive top-k retrieval. Callers budget them
                # explicitly rather than quietly losing them to a relevance limit.
                mandatory = [i for i in items if i.value["kind"] in {"constraint", "priority", "profile"}]
                optional = [i for i in items if i not in mandatory]
                chosen = mandatory + optional[op.offset:op.offset + max(op.limit, 0)]
                results.append([SearchItem(i.namespace, i.key, i.value, i.created_at, i.updated_at) for i in chosen])
            else:
                # Exposing arbitrary app namespaces would imply write authority.
                results.append([])
        return results

    async def abatch(self, ops):
        # Keep a request-owned SQLAlchemy session on its owning thread.
        return self.batch(ops)
