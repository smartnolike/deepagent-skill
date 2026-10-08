"""Validated payloads for restricted quota administration APIs."""

from datetime import date

from pydantic import BaseModel, Field, field_validator


class QuotaRuleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    staff_ids: list[str] = Field(default_factory=list)
    is_default: bool = False
    enabled: bool = True
    request_limit: int | None = Field(default=None, ge=0)
    input_token_limit: int | None = Field(default=None, ge=0)
    output_token_limit: int | None = Field(default=None, ge=0)
    total_token_limit: int | None = Field(default=None, ge=0)
    cost_micro_usd_limit: int | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=1)

    @field_validator("staff_ids")
    @classmethod
    def normalize_staff_ids(cls, value: list[str]) -> list[str]:
        normalized = [staff_id.strip() for staff_id in value if staff_id.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("staff_ids must not contain duplicates")
        return normalized


class ModelPricingRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=255)
    effective_from: date
    effective_to: date | None = None
    input_micro_usd_per_mtok: int = Field(ge=0)
    cached_input_micro_usd_per_mtok: int = Field(ge=0)
    output_micro_usd_per_mtok: int = Field(ge=0)
    enabled: bool = True
