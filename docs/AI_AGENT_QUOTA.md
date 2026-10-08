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
