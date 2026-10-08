"""Quota rule configuration keeps a single reusable rule for many staff IDs."""

import asyncio

from sqlalchemy import select

from api.schemas.quota import QuotaRuleRequest
from database.models.agent.quota import StaffQuotaRuleAssignment
from services.quota_admin_service import QuotaAdminService


def test_rule_staff_ids_are_normalized_into_assignments(client) -> None:
    async def exercise() -> None:
        async with client.app.state.session_factory() as session:
            service = QuotaAdminService(session)
            rule = await service.upsert_rule(
                "standard",
                QuotaRuleRequest(
                    name="Standard",
                    staff_ids=["staff-1", "staff-2"],
                    total_token_limit=1_000,
                    max_output_tokens=100,
                ),
            )
            assignments = list(
                (
                    await session.scalars(
                        select(StaffQuotaRuleAssignment).order_by(StaffQuotaRuleAssignment.staff_id)
                    )
                ).all()
            )
            assert [assignment.staff_id for assignment in assignments] == ["staff-1", "staff-2"]
            assert {assignment.quota_rule_id for assignment in assignments} == {rule.id}

            await service.upsert_rule(
                "standard",
                QuotaRuleRequest(name="Standard", staff_ids=["staff-2"], max_output_tokens=100),
            )
            assignments = list((await session.scalars(select(StaffQuotaRuleAssignment))).all())
            assert [assignment.staff_id for assignment in assignments] == ["staff-2"]

    asyncio.run(exercise())
