"""Persist downloadable Skill-script artifacts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "0003_script_artifacts"
down_revision = "0002_tool_confirmation"
branch_labels = None
depends_on = None
def upgrade() -> None:
    op.create_table("ai_agent_script_artifacts", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("skill_id", sa.String(255), nullable=False), sa.Column("script_name", sa.String(255), nullable=False), sa.Column("object_key", sa.String(1024), nullable=False, unique=True), sa.Column("filename", sa.String(255), nullable=False), sa.Column("content_type", sa.String(100), nullable=False), sa.Column("size_bytes", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.ForeignKeyConstraint(["conversation_id"], ["ai_agent_conversation.id"], ondelete="CASCADE"))
    op.create_index("ix_ai_agent_script_artifacts_conversation_id", "ai_agent_script_artifacts", ["conversation_id"])
def downgrade() -> None: op.drop_table("ai_agent_script_artifacts")
