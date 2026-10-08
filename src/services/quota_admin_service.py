"""Administrative writes for reusable quota rules and dated model price cards."""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.quota import ModelPricingRequest, QuotaRuleRequest
from core.errors import DomainError
from database.models.agent.quota import ModelPricing, QuotaRule, StaffQuotaRuleAssignment


class QuotaAdminService:
    """Apply a rule once and map the submitted staff_ids array to that reusable rule."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_rule(self, code: str, payload: QuotaRuleRequest) -> QuotaRule:
        rule = await self._session.scalar(select(QuotaRule).where(QuotaRule.code == code))
        values = payload.model_dump(exclude={"staff_ids"})
        if rule is None:
            # Clear the previous default before setting this rule, preserving the partial unique index.
            if payload.is_default:
                values["is_default"] = False
            rule = QuotaRule(code=code, **values)
            self._session.add(rule)
            await self._session.flush()
        else:
            for field, value in values.items():
                setattr(rule, field, value)
        if payload.is_default:
            await self._session.execute(
                update(QuotaRule).where(QuotaRule.id != rule.id).values(is_default=False)
            )
            rule.is_default = True
        await self._replace_assignments(rule, payload.staff_ids)
        await self._session.commit()
        await self._session.refresh(rule)
        return rule

    async def create_pricing(self, payload: ModelPricingRequest) -> ModelPricing:
        if payload.effective_to is not None and payload.effective_to < payload.effective_from:
            raise DomainError("INVALID_PRICING_PERIOD", "effective_to must not precede effective_from", 422)
        pricing = ModelPricing(**payload.model_dump())
        self._session.add(pricing)
        await self._session.commit()
        await self._session.refresh(pricing)
        return pricing

    async def _replace_assignments(self, rule: QuotaRule, staff_ids: list[str]) -> None:
        if staff_ids:
            await self._session.execute(
                delete(StaffQuotaRuleAssignment).where(
                    StaffQuotaRuleAssignment.quota_rule_id == rule.id,
                    StaffQuotaRuleAssignment.staff_id.not_in(staff_ids),
                )
            )
        else:
            await self._session.execute(
                delete(StaffQuotaRuleAssignment).where(StaffQuotaRuleAssignment.quota_rule_id == rule.id)
            )
            return
        assignments = list(
            (
                await self._session.scalars(
                    select(StaffQuotaRuleAssignment).where(StaffQuotaRuleAssignment.staff_id.in_(staff_ids))
                )
            ).all()
        )
        by_staff_id = {assignment.staff_id: assignment for assignment in assignments}
        for staff_id in staff_ids:
            assignment = by_staff_id.get(staff_id)
            if assignment is None:
                self._session.add(StaffQuotaRuleAssignment(staff_id=staff_id, quota_rule_id=rule.id))
            else:
                assignment.quota_rule_id = rule.id
