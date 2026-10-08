-- AI Agent 默认额度规则初始化（PostgreSQL）
-- 前提：已执行 Alembic 0007_ai_agent_quota 迁移。
-- 本脚本不会绑定任何 staff_id；所有未单独绑定规则的员工命中默认规则。
-- 如不使用 Gemini 3.8 Flash，请按实际 provider / model / 单价修改价格记录。

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 当前全局 Gemini 3.8 Flash 价格版本：
-- 输入 $0.75 / 1M Token，缓存输入 $0.075 / 1M Token，输出（含 reasoning）$3.75 / 1M Token。
-- 价格用 micro-USD / 1M Token 保存，故分别为 750000、75000、3750000。
INSERT INTO ai_agent_model_pricings (
    id,
    provider,
    model,
    effective_from,
    effective_to,
    input_micro_usd_per_mtok,
    cached_input_micro_usd_per_mtok,
    output_micro_usd_per_mtok,
    enabled
)
VALUES (
    gen_random_uuid(),
    'google_genai',
    'gemini-3.8-flash',
    DATE '2026-08-13',
    DATE '2026-12-31',
    750000,
    75000,
    3750000,
    TRUE
)
ON CONFLICT (provider, model, effective_from)
DO UPDATE SET
    effective_to = EXCLUDED.effective_to,
    input_micro_usd_per_mtok = EXCLUDED.input_micro_usd_per_mtok,
    cached_input_micro_usd_per_mtok = EXCLUDED.cached_input_micro_usd_per_mtok,
    output_micro_usd_per_mtok = EXCLUDED.output_micro_usd_per_mtok,
    enabled = EXCLUDED.enabled;

-- 默认规则：每员工每月最多 1,000 次请求、1,000,000 总 Token、$10；单次最多 4,000 输出 Token。
-- 将任一额度字段设为 NULL，即不限制该维度。
INSERT INTO ai_agent_quota_rules (
    id,
    code,
    name,
    is_default,
    enabled,
    request_limit,
    input_token_limit,
    output_token_limit,
    total_token_limit,
    cost_micro_usd_limit,
    max_output_tokens
)
VALUES (
    gen_random_uuid(),
    'default',
    '默认员工额度',
    TRUE,
    TRUE,
    1000,
    NULL,
    NULL,
    1000000,
    10000000,
    4000
)
ON CONFLICT (code)
DO UPDATE SET
    name = EXCLUDED.name,
    is_default = EXCLUDED.is_default,
    enabled = EXCLUDED.enabled,
    request_limit = EXCLUDED.request_limit,
    input_token_limit = EXCLUDED.input_token_limit,
    output_token_limit = EXCLUDED.output_token_limit,
    total_token_limit = EXCLUDED.total_token_limit,
    cost_micro_usd_limit = EXCLUDED.cost_micro_usd_limit,
    max_output_tokens = EXCLUDED.max_output_tokens,
    updated_at = now();

-- 不需要插入 ai_agent_staff_quota_rule_assignments：未被单独分配的员工自动使用上面的默认规则。
-- ai_agent_staff_monthly_usages 和 ai_agent_staff_usage_events 会在员工首次调用时自动创建。
