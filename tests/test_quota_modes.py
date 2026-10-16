"""Strict/soft quota admission and one-active-request behavior."""

import asyncio
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from core.errors import DomainError
from database.models.agent.quota import ModelPricing, QuotaRule, StaffMonthlyUsage, StaffUsageEvent
from services.quota_service import QuotaService, Usage


async def _seed(session, mode: str, total_tokens_used: int = 0) -> None:
    session.add(
        QuotaRule(
            code="default",
            name="Default",
            is_default=True,
            mode=mode,
            total_token_limit=30_000,
            max_output_tokens=4_000,
        )
    )
    session.add(
        ModelPricing(
            provider="openai",
            model="test-model",
            effective_from=date(2020, 1, 1),
            input_micro_usd_per_mtok=1_000_000,
            cached_input_micro_usd_per_mtok=100_000,
            output_micro_usd_per_mtok=2_000_000,
        )
    )
    if total_tokens_used:
        session.add(
            StaffMonthlyUsage(
                staff_id="staff-a",
                period_month=datetime.now(UTC).date().replace(day=1),
                total_tokens_used=total_tokens_used,
            )
        )
    await session.commit()


def test_soft_mode_allows_final_request_then_blocks_after_settlement(client) -> None:
    async def exercise() -> None:
        async with client.app.state.session_factory() as session:
            await _seed(session, "soft", total_tokens_used=28_067)
            service = QuotaService(session, client.app.state.settings.agent)
            event = await service.reserve("staff-a", "request-1", uuid.uuid4(), estimated_input_tokens=100)

            assert event is not None
            await service.settle(event, Usage(100, 0, 0, 2_000))
            with pytest.raises(DomainError) as error:
                await service.reserve("staff-a", "request-2", uuid.uuid4(), estimated_input_tokens=100)
            assert error.value.code == "QUOTA_EXCEEDED"
            assert error.value.status_code == 429

    asyncio.run(exercise())


def test_strict_mode_rejects_projected_overage(client) -> None:
    async def exercise() -> None:
        async with client.app.state.session_factory() as session:
            await _seed(session, "strict", total_tokens_used=28_067)
            service = QuotaService(session, client.app.state.settings.agent)

            with pytest.raises(DomainError) as error:
                await service.reserve("staff-a", "request-1", uuid.uuid4(), estimated_input_tokens=100)
            assert error.value.code == "QUOTA_EXCEEDED"
            assert error.value.status_code == 429

    asyncio.run(exercise())


def test_only_one_active_quota_request_is_allowed_per_staff(client) -> None:
    async def exercise() -> None:
        async with client.app.state.session_factory() as session:
            await _seed(session, "soft")
            service = QuotaService(session, client.app.state.settings.agent)
            first = await service.reserve("staff-a", "request-1", uuid.uuid4(), estimated_input_tokens=100)

            assert first is not None
            with pytest.raises(DomainError) as error:
                await service.reserve("staff-a", "request-2", uuid.uuid4(), estimated_input_tokens=100)
            assert error.value.code == "REQUEST_IN_PROGRESS"
            assert error.value.status_code == 409

    asyncio.run(exercise())


def test_startup_recovery_releases_reserved_events_and_counters(client) -> None:
    async def exercise() -> None:
        async with client.app.state.session_factory() as session:
            await _seed(session, "soft")
            service = QuotaService(session, client.app.state.settings.agent)
            event = await service.reserve("staff-a", "request-1", uuid.uuid4(), estimated_input_tokens=100)
            assert event is not None

        async with client.app.state.session_factory() as session:
            recovered = await QuotaService(session, client.app.state.settings.agent).recover_startup_reservations()
            assert recovered == 1

        async with client.app.state.session_factory() as session:
            event = await session.scalar(select(StaffUsageEvent).where(StaffUsageEvent.request_id == "request-1"))
            counters = await session.get(StaffMonthlyUsage, ("staff-a", datetime.now(UTC).date().replace(day=1)))
            assert event is not None
            assert counters is not None
            assert event.status == "released"
            assert event.error_code == "SERVICE_RESTART_RECOVERY"
            assert counters.request_reserved == 0
            assert counters.input_tokens_reserved == 0
            assert counters.output_tokens_reserved == 0
            assert counters.total_tokens_reserved == 0
            assert counters.cost_micro_usd_reserved == 0

    asyncio.run(exercise())
