"""Join the document retrieval branch and the manual value history branch into one head.

Both branches start at 0004_portfolio_identity and touch disjoint tables, so this revision
only records the merge; it changes no schema.
"""

revision = "0006_merge_docs_value_history"
down_revision = ("25ae62365383", "0005_manual_value_history")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
