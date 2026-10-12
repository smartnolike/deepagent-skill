"""Current quota endpoint tests."""

import asyncio
from datetime import UTC, datetime

from database.models.agent.quota import QuotaRule, StaffMonthlyUsage
from test_values import TEST_AUTH_TOKEN


def test_current_quota_reports_unconfigured_when_no_rule_exists(client) -> None:
    response = client.get(
        "/agent/api/quotas/current",
        headers={"Authorization": f"Bearer {TEST_AUTH_TOKEN}"},
        params={"staff_id": "staff-a"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "staff_id": "staff-a",
        "period_month": datetime.now(UTC).date().replace(day=1).isoformat(),
        "quota_configured": False,
        "quota_enabled": False,
        "rule": None,
        "limits": None,
        "last_updated_at": None,
    }


def test_current_quota_includes_used_and_reserved_amounts(client) -> None:
    async def configure() -> None:
        async with client.app.state.session_factory() as session:
            session.add(
                QuotaRule(
                    code="default",
                    name="Default quota",
                    is_default=True,
                    request_limit=100,
                    input_token_limit=None,
                    output_token_limit=5_000,
                    total_token_limit=50_000,
                    cost_micro_usd_limit=1_000_000,
                )
            )
            session.add(
                StaffMonthlyUsage(
                    staff_id="staff-a",
                    period_month=datetime.now(UTC).date().replace(day=1),
                    request_used=10,
                    request_reserved=1,
                    input_tokens_used=1_000,
                    input_tokens_reserved=200,
                    output_tokens_used=800,
                    output_tokens_reserved=400,
                    total_tokens_used=1_800,
                    total_tokens_reserved=600,
                    cost_micro_usd_used=20_000,
                    cost_micro_usd_reserved=3_000,
                )
            )
            await session.commit()

    asyncio.run(configure())
    response = client.get(
        "/agent/api/quotas/current",
        headers={"Authorization": f"Bearer {TEST_AUTH_TOKEN}"},
        params={"staff_id": "staff-a"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["quota_configured"] is True
    assert body["quota_enabled"] is True
    assert body["rule"] == {
        "code": "default",
        "name": "Default quota",
        "is_default": True,
        "enabled": True,
        "mode": "soft",
    }
    assert body["limits"]["requests"] == {
        "limit": 100,
        "used": 10,
        "reserved": 1,
        "consumed": 11,
        "remaining": 89,
    }
    assert body["limits"]["input_tokens"]["limit"] is None
    assert body["limits"]["input_tokens"]["remaining"] is None
    assert body["limits"]["output_tokens"]["remaining"] == 3_800
    assert body["limits"]["total_tokens"]["remaining"] == 47_600
    assert body["limits"]["cost"] == {
        "limit": 1_000_000,
        "used": 20_000,
        "reserved": 3_000,
        "consumed": 23_000,
        "remaining": 977_000,
        "unit": "micro_usd",
    }


def test_current_quota_does_not_require_quota_admin_token(client) -> None:
    response = client.get(
        "/agent/api/quotas/current",
        headers={"Authorization": f"Bearer {TEST_AUTH_TOKEN}"},
        params={"staff_id": "staff-a"},
    )

    assert response.status_code == 200
