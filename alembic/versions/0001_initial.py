"""Create application-owned chat tables."""

# 仅创建 ai_agent_ 业务表；LangGraph checkpoint 和 Store 表由官方组件 setup 管理。

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_agent_conversation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("staff_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_agent_conversation_staff_id", "ai_agent_conversation", ["staff_id"])
    op.create_table(
        "ai_agent_message",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai_agent_conversation.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ai_agent_message_conversation_id", "ai_agent_message", ["conversation_id"])
    op.create_table(
        "ai_agent_agent_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai_agent_conversation.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ai_agent_agent_run_conversation_id", "ai_agent_agent_run", ["conversation_id"])


def downgrade() -> None:
    op.drop_table("ai_agent_agent_run")
    op.drop_table("ai_agent_message")
    op.drop_table("ai_agent_conversation")
