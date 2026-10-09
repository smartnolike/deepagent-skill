"""Persistent quota policy, pricing, and per-staff usage ledger models."""

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class QuotaRule(Base):
    """A reusable monthly quota policy; null limits mean that dimension is unlimited."""

    __tablename__ = "ai_agent_quota_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    request_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    input_token_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_token_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_token_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cost_micro_usd_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StaffQuotaRuleAssignment(Base):
    """Current quota rule for a staff member. The primary key permits one active rule only."""

    __tablename__ = "ai_agent_staff_quota_rule_assignments"

    staff_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    quota_rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_agent_quota_rules.id", ondelete="CASCADE"), index=True
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    assigned_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ModelPricing(Base):
    """A dated price card. Rates are integer micro-USD per one million tokens."""

    __tablename__ = "ai_agent_model_pricings"
    __table_args__ = (
        UniqueConstraint("provider", "model", "effective_from", name="uq_ai_agent_model_pricing_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(100), index=True)
    model: Mapped[str] = mapped_column(String(255), index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    input_micro_usd_per_mtok: Mapped[int] = mapped_column(BigInteger)
    cached_input_micro_usd_per_mtok: Mapped[int] = mapped_column(BigInteger)
    cache_write_micro_usd_per_mtok: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_micro_usd_per_mtok: Mapped[int] = mapped_column(BigInteger)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StaffMonthlyUsage(Base):
    """Fast, lockable monthly counters. Reservations prevent concurrent overspending."""

    __tablename__ = "ai_agent_staff_monthly_usages"

    staff_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    period_month: Mapped[date] = mapped_column(Date, primary_key=True)
    request_used: Mapped[int] = mapped_column(BigInteger, default=0)
    input_tokens_used: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens_used: Mapped[int] = mapped_column(BigInteger, default=0)
    total_tokens_used: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_micro_usd_used: Mapped[int] = mapped_column(BigInteger, default=0)
    request_reserved: Mapped[int] = mapped_column(BigInteger, default=0)
    input_tokens_reserved: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens_reserved: Mapped[int] = mapped_column(BigInteger, default=0)
    total_tokens_reserved: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_micro_usd_reserved: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StaffUsageEvent(Base):
    """Idempotent per-invocation ledger record and historical price snapshot."""

    __tablename__ = "ai_agent_staff_usage_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    staff_id: Mapped[str] = mapped_column(String(255), index=True)
    quota_rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_agent_quota_rules.id", ondelete="RESTRICT"), index=True
    )
    model_pricing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_agent_model_pricings.id", ondelete="RESTRICT"), index=True
    )
    model: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="reserved", index=True)
    reserved_input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_cache_write_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_cost_micro_usd: Mapped[int] = mapped_column(BigInteger, default=0)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cached_input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actual_cost_micro_usd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    input_rate_snapshot: Mapped[int] = mapped_column(BigInteger)
    cached_input_rate_snapshot: Mapped[int] = mapped_column(BigInteger)
    cache_write_rate_snapshot: Mapped[int] = mapped_column(BigInteger)
    output_rate_snapshot: Mapped[int] = mapped_column(BigInteger)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_agent_conversation.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
