"""Combine independent local OS domain additions without rewriting existing data."""
revision = "0009_merge_local_os"
down_revision = ("0008_app_security", "0008_career_records", "0008_local_market_data",
                 "0008_memory_history", "0008_reviews_jobs")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
