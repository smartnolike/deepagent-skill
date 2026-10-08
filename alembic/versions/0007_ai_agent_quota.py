"""Add reusable staff quota rules and model usage accounting."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_ai_agent_quota"
down_revision = "0006_artifact_message_association"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_agent_quota_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("request_limit", sa.BigInteger(), nullable=True),
        sa.Column("input_token_limit", sa.BigInteger(), nullable=True),
        sa.Column("output_token_limit", sa.BigInteger(), nullable=True),
        sa.Column("total_token_limit", sa.BigInteger(), nullable=True),
        sa.Column("cost_micro_usd_limit", sa.BigInteger(), nullable=True),
        sa.Column("max_output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_agent_quota_rules_code", "ai_agent_quota_rules", ["code"])
    op.create_index("ix_ai_agent_quota_rules_is_default", "ai_agent_quota_rules", ["is_default"])
    op.create_index(
        "uq_ai_agent_quota_rules_default",
        "ai_agent_quota_rules",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.create_table(
        "ai_agent_staff_quota_rule_assignments",
        sa.Column("staff_id", sa.String(255), primary_key=True),
        sa.Column("quota_rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("assigned_by", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(["quota_rule_id"], ["ai_agent_quota_rules.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_ai_agent_staff_quota_rule_assignments_quota_rule_id",
        "ai_agent_staff_quota_rule_assignments",
        ["quota_rule_id"],
    )

    op.create_table(
        "ai_agent_model_pricings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("input_micro_usd_per_mtok", sa.BigInteger(), nullable=False),
        sa.Column("cached_input_micro_usd_per_mtok", sa.BigInteger(), nullable=False),
        sa.Column("output_micro_usd_per_mtok", sa.BigInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "model", "effective_from", name="uq_ai_agent_model_pricing_version"),
    )
    for column in ("provider", "model"):
        op.create_index(f"ix_ai_agent_model_pricings_{column}", "ai_agent_model_pricings", [column])

    op.create_table(
        "ai_agent_staff_monthly_usages",
        sa.Column("staff_id", sa.String(255), primary_key=True),
        sa.Column("period_month", sa.Date(), primary_key=True),
        sa.Column("request_used", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("input_tokens_used", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("output_tokens_used", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_tokens_used", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cost_micro_usd_used", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("request_reserved", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("input_tokens_reserved", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("output_tokens_reserved", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_tokens_reserved", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cost_micro_usd_reserved", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "ai_agent_staff_usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", sa.String(255), nullable=False, unique=True),
        sa.Column("staff_id", sa.String(255), nullable=False),
        sa.Column("quota_rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_pricing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="reserved"),
        sa.Column("reserved_input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("reserved_output_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("reserved_cost_micro_usd", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cached_input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("actual_cost_micro_usd", sa.BigInteger(), nullable=True),
        sa.Column("input_rate_snapshot", sa.BigInteger(), nullable=False),
        sa.Column("cached_input_rate_snapshot", sa.BigInteger(), nullable=False),
        sa.Column("output_rate_snapshot", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.ForeignKeyConstraint(["quota_rule_id"], ["ai_agent_quota_rules.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["model_pricing_id"], ["ai_agent_model_pricings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai_agent_conversation.id"], ondelete="SET NULL"),
    )
    for column in ("request_id", "staff_id", "quota_rule_id", "model_pricing_id", "status", "conversation_id"):
        op.create_index(f"ix_ai_agent_staff_usage_events_{column}", "ai_agent_staff_usage_events", [column])


def downgrade() -> None:
    op.drop_table("ai_agent_staff_usage_events")
    op.drop_table("ai_agent_staff_monthly_usages")
    op.drop_table("ai_agent_model_pricings")
    op.drop_table("ai_agent_staff_quota_rule_assignments")
    op.drop_table("ai_agent_quota_rules")
