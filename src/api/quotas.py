"""Browser-facing quota reads and restricted quota configuration endpoints."""

from fastapi import APIRouter, Depends, Query, Request

from api.schemas.quota import ModelPricingRequest, QuotaRuleRequest
from core.auth import require_api_token, require_quota_admin_token
from database.session import get_db_session
from services.quota_admin_service import QuotaAdminService
from services.quota_service import QuotaService

router = APIRouter(
    prefix="/api/quotas",
    dependencies=[Depends(require_api_token)],
)


def _service(session=Depends(get_db_session)) -> QuotaAdminService:
    return QuotaAdminService(session)


def _quota_service(request: Request, session=Depends(get_db_session)) -> QuotaService:
    return QuotaService(session, request.app.state.settings.agent)


@router.get("/current")
async def get_current_quota(
    staff_id: str = Query(min_length=1, max_length=255),
    service: QuotaService = Depends(_quota_service),
) -> dict[str, object]:
    """Return the caller-requested staff member's current month quota counters."""
    return await service.current_summary(staff_id)


@router.put("/rules/{code}", dependencies=[Depends(require_quota_admin_token)])
async def upsert_rule(code: str, payload: QuotaRuleRequest, service: QuotaAdminService = Depends(_service)) -> dict:
    rule = await service.upsert_rule(code, payload)
    return {"id": str(rule.id), "code": rule.code, "name": rule.name}


@router.post("/model-pricings", dependencies=[Depends(require_quota_admin_token)])
async def create_pricing(payload: ModelPricingRequest, service: QuotaAdminService = Depends(_service)) -> dict:
    pricing = await service.create_pricing(payload)
    return {"id": str(pricing.id), "model": pricing.model}
