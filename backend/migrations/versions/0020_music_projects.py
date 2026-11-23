"""Add the music project namespace alongside existing studio projects."""

from alembic import op

revision = "0020_music_projects"
down_revision = "0019_list_sort_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS music_projects (
            id TEXT PRIMARY KEY,
            updated_at TEXT NOT NULL,
            document TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_music_projects_updated ON music_projects(updated_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS music_projects")
