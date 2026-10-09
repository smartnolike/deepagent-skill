"""Database-backed quota reservations and settlements for model invocations."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.agent_settings import AgentSettings
from core.errors import DomainError
from database.models.agent.quota import (
    ModelPricing,
    QuotaRule,
    StaffMonthlyUsage,
    StaffQuotaRuleAssignment,
    StaffUsageEvent,
)

_MICRO_USD_PER_MILLION = 1_000_000


@dataclass(frozen=True)
class Usage:
    """Normalized provider usage; output must include reasoning tokens when supplied separately."""

    input_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    output_tokens: int


class QuotaService:
    """Reserve policy limits before a run and settle them after actual model usage is known."""

    def __init__(self, session: AsyncSession, agent_settings: AgentSettings) -> None:
        self._session = session
        self._agent_settings = agent_settings

    async def reserve(
        self,
        staff_id: str,
        request_id: str,
        conversation_id: uuid.UUID,
        estimated_input_tokens: int,
    ) -> StaffUsageEvent | None:
        """Reserve one run. No configured policy means quotas are intentionally disabled."""
        rule = await self._rule_for_staff(staff_id)
        if rule is None:
            return None
        if not rule.enabled:
            raise DomainError("QUOTA_DISABLED", "AI access is disabled for this account", 403)

        existing = await self._session.scalar(
            select(StaffUsageEvent).where(StaffUsageEvent.request_id == request_id)
        )
        if existing is not None:
            return existing

        pricing = await self._current_pricing()
        reserved_output = int(rule.max_output_tokens or 0)
        if reserved_output == 0 and any(
            limit is not None
            for limit in (rule.output_token_limit, rule.total_token_limit, rule.cost_micro_usd_limit)
        ):
            raise DomainError(
                "QUOTA_MAX_OUTPUT_NOT_CONFIGURED",
                "An output, total-token, or cost limit requires max_output_tokens",
                503,
            )
        reserved_cache_write = estimated_input_tokens if pricing.cache_write_micro_usd_per_mtok is not None else 0
        reserved_cost = _cost_micro_usd(
            estimated_input_tokens, 0, reserved_cache_write, reserved_output, pricing
        )
        month = _period_month(datetime.now(UTC).date())
        usage = await self._session.scalar(
            select(StaffMonthlyUsage)
            .where(StaffMonthlyUsage.staff_id == staff_id, StaffMonthlyUsage.period_month == month)
            .with_for_update()
        )
        if usage is None:
            usage = StaffMonthlyUsage(staff_id=staff_id, period_month=month)
            self._session.add(usage)
            await self._session.flush()

        _ensure_within_limits(rule, usage, estimated_input_tokens, reserved_output, reserved_cost)
        usage.request_reserved += 1
        usage.input_tokens_reserved += estimated_input_tokens
        usage.output_tokens_reserved += reserved_output
        usage.total_tokens_reserved += estimated_input_tokens + reserved_output
        usage.cost_micro_usd_reserved += reserved_cost
        event = StaffUsageEvent(
            request_id=request_id,
            staff_id=staff_id,
            quota_rule_id=rule.id,
            model_pricing_id=pricing.id,
            model=pricing.model,
            reserved_input_tokens=estimated_input_tokens,
            reserved_cache_write_tokens=reserved_cache_write,
            reserved_output_tokens=reserved_output,
            reserved_cost_micro_usd=reserved_cost,
            input_rate_snapshot=pricing.input_micro_usd_per_mtok,
            cached_input_rate_snapshot=pricing.cached_input_micro_usd_per_mtok,
            cache_write_rate_snapshot=(
                pricing.cache_write_micro_usd_per_mtok or pricing.input_micro_usd_per_mtok
            ),
            output_rate_snapshot=pricing.output_micro_usd_per_mtok,
            conversation_id=conversation_id,
        )
        self._session.add(event)
        await self._session.commit()
        await self._session.refresh(event)
        return event

    async def settle(self, event: StaffUsageEvent | None, actual: Usage | None) -> None:
        """Move a reservation into used counters; unknown provider usage conservatively keeps the reservation."""
        if event is None or event.status != "reserved":
            return
        event = await self._session.scalar(
            select(StaffUsageEvent).where(StaffUsageEvent.id == event.id).with_for_update()
        )
        if event is None or event.status != "reserved":
            return
        month = _period_month(event.created_at.date() if event.created_at else datetime.now(UTC).date())
        counters = await self._session.scalar(
            select(StaffMonthlyUsage)
            .where(StaffMonthlyUsage.staff_id == event.staff_id, StaffMonthlyUsage.period_month == month)
            .with_for_update()
        )
        if counters is None:
            raise RuntimeError("Quota counters missing for a reserved usage event")
        actual = actual or Usage(
            event.reserved_input_tokens,
            0,
            event.reserved_cache_write_tokens,
            event.reserved_output_tokens,
        )
        actual_cost = _cost_micro_usd_from_snapshots(actual, event)
        counters.request_reserved -= 1
        counters.input_tokens_reserved -= event.reserved_input_tokens
        counters.output_tokens_reserved -= event.reserved_output_tokens
        counters.total_tokens_reserved -= event.reserved_input_tokens + event.reserved_output_tokens
        counters.cost_micro_usd_reserved -= event.reserved_cost_micro_usd
        counters.request_used += 1
        counters.input_tokens_used += actual.input_tokens
        counters.output_tokens_used += actual.output_tokens
        counters.total_tokens_used += actual.input_tokens + actual.output_tokens
        counters.cost_micro_usd_used += actual_cost
        event.status = "settled"
        event.input_tokens = actual.input_tokens
        event.cached_input_tokens = actual.cached_input_tokens
        event.cache_write_tokens = actual.cache_write_tokens
        event.output_tokens = actual.output_tokens
        event.actual_cost_micro_usd = actual_cost
        event.settled_at = datetime.now(UTC)
        await self._session.commit()

    async def release(self, event: StaffUsageEvent | None, error_code: str) -> None:
        """Release an invocation that did not reach a billable model response."""
        if event is None or event.status != "reserved":
            return
        event = await self._session.scalar(
            select(StaffUsageEvent).where(StaffUsageEvent.id == event.id).with_for_update()
        )
        if event is None or event.status != "reserved":
            return
        month = _period_month(event.created_at.date() if event.created_at else datetime.now(UTC).date())
        counters = await self._session.scalar(
            select(StaffMonthlyUsage)
            .where(StaffMonthlyUsage.staff_id == event.staff_id, StaffMonthlyUsage.period_month == month)
            .with_for_update()
        )
        if counters is not None:
            counters.request_reserved -= 1
            counters.input_tokens_reserved -= event.reserved_input_tokens
            counters.output_tokens_reserved -= event.reserved_output_tokens
            counters.total_tokens_reserved -= event.reserved_input_tokens + event.reserved_output_tokens
            counters.cost_micro_usd_reserved -= event.reserved_cost_micro_usd
        event.status = "released"
        event.error_code = error_code[:100]
        event.settled_at = datetime.now(UTC)
        await self._session.commit()

    async def _rule_for_staff(self, staff_id: str) -> QuotaRule | None:
        rule = await self._session.scalar(
            select(QuotaRule)
            .join(StaffQuotaRuleAssignment, StaffQuotaRuleAssignment.quota_rule_id == QuotaRule.id)
            .where(StaffQuotaRuleAssignment.staff_id == staff_id)
        )
        if rule is not None:
            return rule
        return await self._session.scalar(
            select(QuotaRule).where(QuotaRule.is_default.is_(True)).order_by(QuotaRule.created_at.desc())
        )

    async def _current_pricing(self) -> ModelPricing:
        provider = self._agent_settings.provider
        model = self._agent_settings.model
        if not model:
            raise DomainError("MODEL_PRICING_NOT_CONFIGURED", "The configured model has no pricing record", 503)
        today = datetime.now(UTC).date()
        pricing = await self._session.scalar(
            select(ModelPricing)
            .where(
                ModelPricing.provider == provider,
                ModelPricing.model == model,
                ModelPricing.enabled.is_(True),
                ModelPricing.effective_from <= today,
                or_(ModelPricing.effective_to.is_(None), ModelPricing.effective_to >= today),
            )
            .order_by(ModelPricing.effective_from.desc())
        )
        if pricing is None:
            raise DomainError("MODEL_PRICING_NOT_CONFIGURED", "The configured model has no active pricing record", 503)
        return pricing


def estimate_input_tokens(content: str) -> int:
    """Conservative lightweight preflight estimate; final billing always uses provider metadata."""
    return max(1, math.ceil(len(content.encode("utf-8")) / 3))


def normalize_usage(payload: dict[str, object]) -> Usage:
    """Accept the usage shapes emitted by LangChain/Vertex without exposing SDK types to services."""
    details = payload.get("input_token_details")
    details = details if isinstance(details, dict) else {}
    cached = details.get("cache_read") or details.get("cached_tokens") or payload.get("cached_input_tokens") or 0
    cache_write = (
        details.get("cache_creation")
        or details.get("cache_write_tokens")
        or payload.get("cache_write_tokens")
        or 0
    )
    input_tokens = max(0, int(payload.get("input_tokens", payload.get("prompt_token_count", 0)) or 0))
    response_tokens = int(payload.get("output_tokens", payload.get("candidates_token_count", 0)) or 0)
    # Vertex reports hidden reasoning separately. It is billable and belongs in the output bucket.
    thoughts_tokens = int(payload.get("thoughts_token_count", payload.get("thoughts_tokens", 0)) or 0)
    cached_input_tokens = min(input_tokens, max(0, int(cached or 0)))
    cache_write_tokens = min(input_tokens - cached_input_tokens, max(0, int(cache_write or 0)))
    return Usage(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_write_tokens=cache_write_tokens,
        output_tokens=max(0, response_tokens + thoughts_tokens),
    )


def _period_month(value: date) -> date:
    return value.replace(day=1)


def _cost_micro_usd(
    input_tokens: int,
    cached_tokens: int,
    cache_write_tokens: int,
    output_tokens: int,
    pricing: ModelPricing,
) -> int:
    normal_input_tokens = input_tokens - cached_tokens - cache_write_tokens
    cache_write_rate = pricing.cache_write_micro_usd_per_mtok or pricing.input_micro_usd_per_mtok
    return math.ceil(
        (
            normal_input_tokens * pricing.input_micro_usd_per_mtok
            + cached_tokens * pricing.cached_input_micro_usd_per_mtok
            + cache_write_tokens * cache_write_rate
            + output_tokens * pricing.output_micro_usd_per_mtok
        )
        / _MICRO_USD_PER_MILLION
    )


def _cost_micro_usd_from_snapshots(actual: Usage, event: StaffUsageEvent) -> int:
    return math.ceil(
        (
            (actual.input_tokens - actual.cached_input_tokens - actual.cache_write_tokens) * event.input_rate_snapshot
            + actual.cached_input_tokens * event.cached_input_rate_snapshot
            + actual.cache_write_tokens * event.cache_write_rate_snapshot
            + actual.output_tokens * event.output_rate_snapshot
        )
        / _MICRO_USD_PER_MILLION
    )


def _ensure_within_limits(
    rule: QuotaRule,
    usage: StaffMonthlyUsage,
    input_tokens: int,
    output_tokens: int,
    cost_micro_usd: int,
) -> None:
    checks = (
        (rule.request_limit, usage.request_used + usage.request_reserved + 1),
        (rule.input_token_limit, usage.input_tokens_used + usage.input_tokens_reserved + input_tokens),
        (rule.output_token_limit, usage.output_tokens_used + usage.output_tokens_reserved + output_tokens),
        (rule.total_token_limit, usage.total_tokens_used + usage.total_tokens_reserved + input_tokens + output_tokens),
        (rule.cost_micro_usd_limit, usage.cost_micro_usd_used + usage.cost_micro_usd_reserved + cost_micro_usd),
    )
    if any(limit is not None and value > limit for limit, value in checks):
        raise DomainError("QUOTA_EXCEEDED", "Monthly AI usage limit has been reached", 429)
