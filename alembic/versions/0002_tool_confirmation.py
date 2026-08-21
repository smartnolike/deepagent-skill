"""Persist user confirmation decisions for Agent Tool calls."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_tool_confirmation"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_agent_tool_confirmation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("display_arguments", sa.JSON(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("decided_by_staff_id", sa.String(length=255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_status", sa.String(length=20), nullable=False),
        sa.Column("result_summary", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai_agent_conversation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["ai_agent_agent_run.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_ai_agent_tool_confirmation_conversation_id",
        "ai_agent_tool_confirmation",
        ["conversation_id"],
    )
    op.create_index(
        "ix_ai_agent_tool_confirmation_agent_run_id",
        "ai_agent_tool_confirmation",
        ["agent_run_id"],
    )
    op.create_index(
        "ix_ai_agent_tool_confirmation_decision",
        "ai_agent_tool_confirmation",
        ["decision"],
    )


def downgrade() -> None:
    op.drop_table("ai_agent_tool_confirmation")
