# AI Agent 员工额度控制

本系统用 PostgreSQL 实现按 `staff_id` 的 AI 使用额度控制，不依赖 Redis。它同时支持费用、输入 Token、输出 Token、总 Token、请求次数和单次最大输出 Token 的任意组合限制。

## 规则生效顺序

1. 若 `ai_agent_staff_quota_rule_assignments` 中存在员工绑定，使用该规则。
2. 否则使用 `ai_agent_quota_rules.is_default = true` 的默认规则。
3. 若两者都不存在，额度功能不启用，以兼容灰度上线前的现有调用。

一名员工仅能有一个当前规则；一个规则可绑定多个员工。管理接口接收 `staff_ids` 数组，数据库将其规范化为多条绑定记录。

## 数据表

| 表 | 用途 |
| --- | --- |
| `ai_agent_quota_rules` | 可复用的额度规则，例如默认、标准和高级规则。所有额度字段均可为 `NULL`，表示不限制该维度。 |
| `ai_agent_staff_quota_rule_assignments` | 员工到规则的一对一当前绑定；多个员工可指向同一规则。 |
| `ai_agent_model_pricings` | 模型在不同生效期的价格卡，按 `provider + model + 生效日期` 匹配。 |
| `ai_agent_staff_monthly_usages` | 员工每月的已结算与预占聚合计数，用于快速、原子地判定额度。 |
| `ai_agent_staff_usage_events` | 每次模型调用的账本、请求幂等记录及价格快照。 |

所有价格均用整数 `micro-USD`（一美元的百万分之一）保存。模型价格字段单位是“每一百万 Token 的 micro-USD”。例如 `$0.75 / 1M Token` 保存为 `750000`。

### 表关系

```text
ai_agent_quota_rules
  ├── ai_agent_staff_quota_rule_assignments ──> staff_id
  └── ai_agent_staff_usage_events

ai_agent_model_pricings
  └── ai_agent_staff_usage_events

staff_id + period_month
  └── ai_agent_staff_monthly_usages
```

`ai_agent_quota_rules` 定义“套餐”；`ai_agent_staff_quota_rule_assignments` 决定某位员工使用哪一个套餐；月度汇总和调用账本始终按 `staff_id` 独立计算，不会让同一规则下的员工共享额度。

### `ai_agent_quota_rules`

可复用的额度规则。管理员只需创建一次“默认”“标准”或“高级”等规则，再将多个员工绑定到它。

| 字段 | 类型 | 约束/示例 | 含义 |
| --- | --- | --- | --- |
| `id` | UUID | PK | 规则主键。 |
| `code` | VARCHAR(100) | UNIQUE，例如 `default` | 面向配置和管理接口的稳定标识。 |
| `name` | VARCHAR(255) | `默认员工额度` | 前端/管理端展示名。 |
| `is_default` | BOOLEAN | 同时最多一条为 `true` | 没有员工专属绑定时使用的规则。 |
| `enabled` | BOOLEAN | 默认 `true` | 为 `false` 时命中该规则的请求返回 `403 QUOTA_DISABLED`。 |
| `request_limit` | BIGINT NULL | `1000` | 单员工单月请求上限；`NULL` 代表不限。 |
| `input_token_limit` | BIGINT NULL | `NULL` | 单员工单月输入 Token 上限。 |
| `output_token_limit` | BIGINT NULL | `NULL` | 单员工单月输出 Token 上限，含 reasoning。 |
| `total_token_limit` | BIGINT NULL | `1000000` | 单员工单月输入与输出合计 Token 上限。 |
| `cost_micro_usd_limit` | BIGINT NULL | `10000000` = `$10` | 单员工单月费用上限。 |
| `max_output_tokens` | BIGINT NULL | `4000` | 单次调用的最大可预占输出量；使用费用、总 Token 或输出 Token 限制时必须设置。 |
| `created_at` / `updated_at` | TIMESTAMPTZ | 自动维护 | 规则创建和最近修改时间。 |

### `ai_agent_staff_quota_rule_assignments`

员工和规则的当前绑定表。它是 `staff_ids` 数组落库后的规范化形式，而不是在规则表中保存 JSON 数组。

| 字段 | 类型 | 约束/示例 | 含义 |
| --- | --- | --- | --- |
| `staff_id` | VARCHAR(255) | PK，例如 `staff_001` | 员工唯一标识；作为主键意味着一名员工只能绑定一条当前规则。 |
| `quota_rule_id` | UUID | FK → `ai_agent_quota_rules.id` | 员工使用的规则。删除规则时绑定自动删除。 |
| `assigned_at` | TIMESTAMPTZ | 自动维护 | 最近绑定时间。 |
| `assigned_by` | VARCHAR(255) NULL | 管理员 staff_id | 可选审计字段。 |

例如一个规则接口请求：

```json
{"staff_ids": ["staff_001", "staff_002"]}
```

会生成两行绑定记录，但二者的 `quota_rule_id` 相同。

### `ai_agent_model_pricings`

模型价格版本表。`provider` 必须与 `agent.provider` 一致；Vertex Gemini 使用 `google_genai`。不存储 `location`，因为当前模型调用固定为 `global`。

| 字段 | 类型 | 约束/示例 | 含义 |
| --- | --- | --- | --- |
| `id` | UUID | PK | 价格版本主键。 |
| `provider` | VARCHAR(100) | 例如 `google_genai` | 模型提供方配置值。 |
| `model` | VARCHAR(255) | `gemini-3.8-flash` | 与 `agent.model` 匹配的模型名。 |
| `effective_from` | DATE | `2026-08-13` | 此价格开始生效的日期。 |
| `effective_to` | DATE NULL | `2026-12-31` | 此价格最后有效日期；`NULL` 代表持续有效。 |
| `input_micro_usd_per_mtok` | BIGINT | `750000` | 普通输入每 100 万 Token 的价格。 |
| `cached_input_micro_usd_per_mtok` | BIGINT | `75000` | 缓存命中输入每 100 万 Token 的价格。 |
| `output_micro_usd_per_mtok` | BIGINT | `3750000` | 输出每 100 万 Token 的价格，包含 reasoning。 |
| `enabled` | BOOLEAN | 默认 `true` | 是否允许本价格版本参与匹配。 |
| `created_at` | TIMESTAMPTZ | 自动维护 | 价格记录创建时间。 |

唯一约束为 `(provider, model, effective_from)`。价格变化时新增记录而非修改旧记录，例如 2027 年涨价时增加一条新的 `effective_from = 2027-01-01` 记录。

### `ai_agent_staff_monthly_usages`

月度聚合表。每位员工每个月一行，由首次模型调用自动创建；用于在调用前快速判断是否还有剩余额度。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `staff_id` | VARCHAR(255) | 员工 ID，与 `period_month` 组成复合主键。 |
| `period_month` | DATE | 当月第一天，例如 `2026-10-01`。 |
| `request_used` | BIGINT | 已完成并结算的请求数。 |
| `input_tokens_used` | BIGINT | 已结算普通/缓存输入合计 Token。 |
| `output_tokens_used` | BIGINT | 已结算输出 Token，含 reasoning。 |
| `total_tokens_used` | BIGINT | 已结算输入与输出 Token 合计。 |
| `cost_micro_usd_used` | BIGINT | 已结算成本。 |
| `request_reserved` | BIGINT | 正在执行、尚未结算的请求数。 |
| `input_tokens_reserved` | BIGINT | 为执行中请求预占的输入 Token。 |
| `output_tokens_reserved` | BIGINT | 为执行中请求按 `max_output_tokens` 预占的输出 Token。 |
| `total_tokens_reserved` | BIGINT | 当前预占 Token 合计。 |
| `cost_micro_usd_reserved` | BIGINT | 当前预占费用。 |
| `updated_at` | TIMESTAMPTZ | 最近一次预占、结算或释放时间。 |

额度判断统一使用：

```text
已结算值 + 已预占值 + 本次请求预占值 <= 规则上限
```

### `ai_agent_staff_usage_events`

调用级账本。它既用于审计和成本报表，也用 `request_id` 防止浏览器重试导致重复扣额。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id` | UUID | PK，账本事件 ID。 |
| `request_id` | VARCHAR(255) | UNIQUE，HTTP 请求幂等键。 |
| `staff_id` | VARCHAR(255) | 本次调用归属员工。 |
| `quota_rule_id` | UUID | FK → `ai_agent_quota_rules.id`，命中的规则。 |
| `model_pricing_id` | UUID | FK → `ai_agent_model_pricings.id`，命中的价格版本。 |
| `model` | VARCHAR(255) | 模型名快照。 |
| `status` | VARCHAR(20) | `reserved`、`settled`、`released` 或 `failed`。 |
| `reserved_input_tokens` | BIGINT | 请求开始时预估的输入 Token。 |
| `reserved_output_tokens` | BIGINT | 请求开始时按规则预占的最大输出 Token。 |
| `reserved_cost_micro_usd` | BIGINT | 请求开始时预占成本。 |
| `input_tokens` | BIGINT NULL | 最终实际输入 Token。 |
| `cached_input_tokens` | BIGINT NULL | 最终实际缓存输入 Token。 |
| `output_tokens` | BIGINT NULL | 最终实际输出 Token，含 reasoning。 |
| `actual_cost_micro_usd` | BIGINT NULL | 最终实际成本。 |
| `input_rate_snapshot` | BIGINT | 本次普通输入价格快照。 |
| `cached_input_rate_snapshot` | BIGINT | 本次缓存输入价格快照。 |
| `output_rate_snapshot` | BIGINT | 本次输出价格快照。 |
| `conversation_id` | UUID NULL | FK → `ai_agent_conversation.id`，关联会话。 |
| `created_at` / `settled_at` | TIMESTAMPTZ | 预占、结算或释放时间。 |
| `error_code` | VARCHAR(100) NULL | 释放/失败时的内部原因，例如 `AGENT_FAILED`。 |

## 调用与结算流程

```text
POST /messages
  → 根据 staff_id 选择规则
  → 读取当前 provider + model 的有效价格
  → 预估输入并按 max_output_tokens 预占所有已启用维度
  → 通过后才启动 SSE / 模型调用
  → 从 Vertex usage_metadata 收集输入、缓存输入、输出及 reasoning Token
  → 按实际使用量结算；未取得用量时保守地按预占值结算
```

响应中的 reasoning Token 会计入输出 Token。每次账本事件保存命中的价格快照，因此后续修改价格不会影响历史账目。

## 模型与价格配置

Vertex AI 的调用位置固定为 `global`，但额度价格表不再存储 `location` 字段。价格表的 `provider` 与 `agent.provider` 保持一致，例如 Vertex Gemini 使用 `google_genai`。切换模型时，先新增该模型的价格记录，再修改 `agent.model`；找不到当前模型有效价格时，配置了额度规则的请求会返回 `503 MODEL_PRICING_NOT_CONFIGURED`。

模型价格应新增版本，而不是覆盖历史行：使用 `effective_from` 和 `effective_to` 表示价格生效期。

## 管理接口

管理接口使用原有 Bearer Token 以及独立的 `X-Quota-Admin-Token`。需要在应用 YAML 配置中设置：

```yaml
quota_admin_token: ${QUOTA_ADMIN_TOKEN}
```

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `PUT` | `/agent/api/quotas/rules/{code}` | 创建或更新规则，并以 `staff_ids` 数组整体替换该规则的员工绑定。 |
| `POST` | `/agent/api/quotas/model-pricings` | 新增模型价格版本。 |

若未配置 `quota_admin_token`，管理接口返回 `404`，避免被普通前端调用。

## 额度拒绝结果

配额在 SSE 启动前判定。额度不足时，后端返回：

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json

{"code":"QUOTA_EXCEEDED","message":"Monthly AI usage limit has been reached"}
```

前端应对 `429` 读取该 JSON 并显示用户可理解的提示，例如“本月 AI 使用额度已用尽，请联系管理员申请额度”。

其他相关错误：

| 状态 | code | 含义 |
| --- | --- | --- |
| 403 | `QUOTA_DISABLED` | 命中的规则已禁用。 |
| 503 | `MODEL_PRICING_NOT_CONFIGURED` | 当前模型没有有效价格记录。 |
| 503 | `QUOTA_MAX_OUTPUT_NOT_CONFIGURED` | 启用了成本、总 Token 或输出 Token 限制，但规则未配置 `max_output_tokens`，无法安全预占。 |

## 上线步骤

1. 运行 Alembic `0007_ai_agent_quota` 迁移。
2. 设置 `QUOTA_ADMIN_TOKEN`。
3. 执行 [默认规则初始化 SQL](./sql/ai_agent_quota_default.sql)。
4. 按需通过管理接口创建更多规则，并提交 `staff_ids` 数组绑定员工。

> 当前应用仍从请求体接收 `staff_id`。在接入 SSO/JWT 前，这只是使用控制而不是可信身份边界；接入后应从服务端验证过的身份 claim 获取 `staff_id`。
