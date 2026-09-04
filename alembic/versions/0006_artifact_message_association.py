"""Associate published artifacts with their completed assistant messages."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_artifact_message_association"
down_revision = "0005_conversation_workspace_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_agent_sandbox_artifacts", sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("ai_agent_sandbox_artifacts", sa.Column("assistant_message_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_ai_agent_sandbox_artifacts_agent_run_id", "ai_agent_sandbox_artifacts", ["agent_run_id"])
    op.create_index(
        "ix_ai_agent_sandbox_artifacts_assistant_message_id",
        "ai_agent_sandbox_artifacts",
        ["assistant_message_id"],
    )
    op.create_foreign_key(
        "ai_agent_sandbox_artifacts_agent_run_id_fkey",
        "ai_agent_sandbox_artifacts",
        "ai_agent_agent_run",
        ["agent_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "ai_agent_sandbox_artifacts_assistant_message_id_fkey",
        "ai_agent_sandbox_artifacts",
        "ai_agent_message",
        ["assistant_message_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ai_agent_sandbox_artifacts_assistant_message_id_fkey", "ai_agent_sandbox_artifacts", type_="foreignkey")
    op.drop_constraint("ai_agent_sandbox_artifacts_agent_run_id_fkey", "ai_agent_sandbox_artifacts", type_="foreignkey")
    op.drop_index("ix_ai_agent_sandbox_artifacts_assistant_message_id", table_name="ai_agent_sandbox_artifacts")
    op.drop_index("ix_ai_agent_sandbox_artifacts_agent_run_id", table_name="ai_agent_sandbox_artifacts")
    op.drop_column("ai_agent_sandbox_artifacts", "assistant_message_id")
    op.drop_column("ai_agent_sandbox_artifacts", "agent_run_id")
