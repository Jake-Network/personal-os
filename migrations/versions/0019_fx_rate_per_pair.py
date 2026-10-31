"""Keep one current FX rate per currency pair instead of an ever-growing list.

Valuation and advisor context only ever read the newest rate per pair; snapshots copy the
rate they used and raw quotes stay in market_observations, so older rows are dropped.
"""

from alembic import op

revision = "0019_fx_rate_per_pair"
down_revision = "0018_merge_advisor_records"
branch_labels = None
depends_on = None


def upgrade():
    # Keep the row valuation uses today: newest non-future valid rate, else the newest row.
    op.execute("""
        DELETE FROM fx_rates WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY base, quote
                    ORDER BY (rate > 0 AND as_of <= now()) DESC, as_of DESC, id DESC
                ) AS position
                FROM fx_rates
            ) ranked
            WHERE position > 1
        )
    """)
    op.create_unique_constraint("uq_fx_rates_pair", "fx_rates", ["base", "quote"])


def downgrade():
    # Removed history is not restorable; the older schema simply accepts one row per pair.
    op.drop_constraint("uq_fx_rates_pair", "fx_rates", type_="unique")
