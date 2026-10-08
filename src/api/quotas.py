"""Restricted quota configuration endpoints."""

from fastapi import APIRouter, Depends

from api.schemas.quota import ModelPricingRequest, QuotaRuleRequest
from core.auth import require_api_token, require_quota_admin_token
from database.session import get_db_session
from services.quota_admin_service import QuotaAdminService

router = APIRouter(
    prefix="/api/quotas",
    dependencies=[Depends(require_api_token), Depends(require_quota_admin_token)],
)


def _service(session=Depends(get_db_session)) -> QuotaAdminService:
    return QuotaAdminService(session)


@router.put("/rules/{code}")
async def upsert_rule(code: str, payload: QuotaRuleRequest, service: QuotaAdminService = Depends(_service)) -> dict:
    rule = await service.upsert_rule(code, payload)
    return {"id": str(rule.id), "code": rule.code, "name": rule.name}


@router.post("/model-pricings")
async def create_pricing(payload: ModelPricingRequest, service: QuotaAdminService = Depends(_service)) -> dict:
    pricing = await service.create_pricing(payload)
    return {"id": str(pricing.id), "model": pricing.model}
