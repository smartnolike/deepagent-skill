"""Track activity for independently expiring shared-Sandbox directories."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_conversation_workspace_retention"
down_revision = "0004_shared_gke_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_agent_conversation_workspaces",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("staff_id", sa.String(255), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai_agent_conversation.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("ai_agent_conversation_workspaces")
