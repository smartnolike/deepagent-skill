"""Persist conversation-scoped workspace sessions and downloadable artifacts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_workspace_backends"
down_revision = "0002_tool_confirmation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_agent_sandbox_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("workspace_reference", sa.String(1024), nullable=False),
        sa.Column("namespace", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai_agent_conversation.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ai_agent_sandbox_sessions_conversation_id", "ai_agent_sandbox_sessions", ["conversation_id"])
    op.create_index(
        "uq_ai_agent_sandbox_sessions_active_conversation",
        "ai_agent_sandbox_sessions",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "ai_agent_sandbox_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sandbox_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sandbox_path", sa.String(1024), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai_agent_conversation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sandbox_session_id"], ["ai_agent_sandbox_sessions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ai_agent_sandbox_artifacts_conversation_id", "ai_agent_sandbox_artifacts", ["conversation_id"])
    op.create_index("ix_ai_agent_sandbox_artifacts_sandbox_session_id", "ai_agent_sandbox_artifacts", ["sandbox_session_id"])


def downgrade() -> None:
    op.drop_table("ai_agent_sandbox_artifacts")
    op.drop_table("ai_agent_sandbox_sessions")
