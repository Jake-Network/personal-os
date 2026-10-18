"""Types passed between migration planning and applying, and the schema shape they compare."""

from dataclasses import dataclass, field

Schema = dict[str, frozenset[str]]  # table -> column names


@dataclass
class MigrationPlan:
    """What `migration_manager` will do to a database, decided before anything changes."""

    current: str | None
    head: str
    stamp: str | None = None  # legacy create_all database: revision its schema matches
    differences: list[str] = field(default_factory=list)  # legacy database without an exact match

    @property
    def action(self) -> str:
        if self.differences:
            return "refuse"
        if self.stamp:
            return "stamp"
        return "none" if self.current == self.head else "upgrade"

    def describe(self) -> str:
        if self.action == "refuse":
            return ("No migration revision matches this database's schema, so nothing will be changed.\n  "
                    + "\n  ".join(self.differences))
        if self.action == "none":
            return f"Already at {self.head}; nothing to do."
        steps = [f"stamp {self.stamp} (schema verified), add missing append-only triggers"] if self.stamp else []
        if self.stamp != self.head:
            steps.append(f"upgrade {self.stamp or self.current or 'empty database'} → {self.head}")
        return "Plan: " + "; ".join(steps)
