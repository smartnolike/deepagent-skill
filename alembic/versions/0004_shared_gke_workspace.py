"""Remove the retired local-shell workspace/session schema."""

from alembic import op
import sqlalchemy as sa


revision = "0004_shared_gke_workspace"
down_revision = "0003_workspace_backends"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ai_agent_sandbox_artifacts_sandbox_session_id_fkey",
        "ai_agent_sandbox_artifacts",
        type_="foreignkey",
    )
    op.drop_index("ix_ai_agent_sandbox_artifacts_sandbox_session_id", table_name="ai_agent_sandbox_artifacts")
    op.drop_column("ai_agent_sandbox_artifacts", "sandbox_session_id")
    op.drop_table("ai_agent_sandbox_sessions")


def downgrade() -> None:
    op.create_table(
        "ai_agent_sandbox_sessions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("workspace_reference", sa.String(1024), nullable=False),
        sa.Column("namespace", sa.String(255)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column("ai_agent_sandbox_artifacts", sa.Column("sandbox_session_id", sa.UUID(), nullable=True))
    op.create_index("ix_ai_agent_sandbox_artifacts_sandbox_session_id", "ai_agent_sandbox_artifacts", ["sandbox_session_id"])
    op.create_foreign_key(
        "ai_agent_sandbox_artifacts_sandbox_session_id_fkey",
        "ai_agent_sandbox_artifacts",
        "ai_agent_sandbox_sessions",
        ["sandbox_session_id"],
        ["id"],
        ondelete="CASCADE",
    )
