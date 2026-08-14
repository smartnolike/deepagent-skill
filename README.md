# DeepAgent Platform MVP

Copy a YAML template and provide a local static API token:

```bash
cp config/local.example.yaml config/local.yaml
export AGENT_ENV=local
```

YAML 可以引用启动环境变量，例如 `api_auth_token: ${API_AUTH_TOKEN}` 或 MCP header
`Authorization: Bearer ${TICKETING_MCP_TOKEN}`。未提供且没有默认值的引用会使启动失败。

应用内自定义 Tool 位于 `src/tools/`。如启用 `tools.external_status_url`，服务会复用专用的
`src/common/httpx_client.py` 中的 `HttpxClient` 并强制以 `build/root.cer` 校验外部 API TLS 证书。该证书当前必须由部署环境
提供有效 PEM/CA 内容；空文件或缺失文件会使启用外部 Tool 的应用启动失败。

Start PostgreSQL, migrate, and run the API:

```bash
docker run --name deepagent-postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=deepagent -p 5432:5432 postgres:16
alembic upgrade head
uvicorn src.main:app --reload
```

`GET /health` 不需要认证，并仅在模型、PostgreSQL 与全部 MCP 已就绪后返回 `{"status":"ok"}`。
所有 `/agent/api/*` calls require `Authorization: Bearer <api_auth_token>`。local、dev、prod 都必须配置真实
`agent.model`、PostgreSQL 与 HTTP MCP；Mock harness、SQLite 和 InMemoryStore 仅能通过测试注入使用。
DeepAgent Skill 位于与 `src/` 同级的 `skill-packages/`，通过 YAML 的 `agent.enabled_skills` 启用。

`danaan-cloud-resource` 的 `danaan-base-context` 表单提交后，会自动保存
`resourceOnboardRegion`、`applicationName`、`eimId`、`envName` 与 `useCaseShortName` 到 LangGraph
PostgreSQL Store 的 `danaan-cloud-resource:base-context` key。下一次 Danaan 申请会精确读取该 key，并要求
用户确认沿用或重新填写；完整模板和工单 payload 不会保存。

## 用户确认型 MCP Tool

对会产生副作用的 MCP Tool，在对应 server 配置 `confirmation_required_tools`；例如示例中的
`create_ticket`。Agent 准备调用该 Tool 时会暂停并通过 SSE 返回 `confirmation_required`，而不会执行 Tool。
仅会话所属的 `staff_id` 可通过以下接口继续该运行：

```text
POST /agent/api/conversations/{conversation_id}/tool-confirmations
{"staff_id":"...", "action":"approve"}  # 执行 Tool
{"staff_id":"...", "action":"reject"}   # 取消当前 Tool，不执行
```

确认与取消都使用相同的 `conversation_id` / LangGraph `thread_id` 恢复状态；用户离开页面后可以继续确认。
当前 MVP 每次暂停只处理一个需确认的 Tool 调用。

## Danaan Cloud Resource Skill

`danaan-cloud-resource` 已包含在示例环境的 `agent.enabled_skills` 中。它先让用户确认或重新选择
`resourceOnboardRegion`、`applicationName`、`eimId`、`envName` 和 `useCaseShortName`，再处理 Cloud Storage、BigQuery 或 Cloud SQL
申请。前端收到 `form_required` SSE 后，通过同一确认接口提交结构化表单结果：

```json
{"staff_id":"...", "action":"respond", "response":{"envName":"dev"}}
```

`danaan_get_resource_template` 是应用内只读 Tool，使用独立的 Danaan SQLAlchemy Model 按收集到的 `resourceName` 查询：
`public.cloud_resource_template_info.cloud_resource_name`，以 `req_time DESC NULLS LAST,
res_template_id DESC` 取最新 `template_content`。该表由 Danaan 管理，不会由本项目迁移创建；运行账号
需要对此表的 `SELECT` 权限。最终 `danaan__external_resource_add` 仍需用户 `approve` 才会执行。

## 模型 Provider：内部动态 Token、OpenAI 或 OpenAI-compatible 外部模型

通过 `agent.provider` 选择模型来源：`internal`、`openai` 或 `openai_compatible`。认证方式互斥：

```yaml
# 公司内部 OpenAI-compatible 模型
agent:
  provider: internal
  model: internal-model-name
  base_url: ${MODEL_BASE_URL}
  token_auth:
    translator_url: ${TRANSLATOR_URL}
    service_account: ${SERVICE_ACCOUNT}
    # local：环境变量中的直接密码
    service_account_password: ${SERVICE_ACCOUNT_PASSWORD}
```

dev / prod 使用 Google Secret Manager 的**完整 Secret Version resource name**，与直接密码二选一：

```yaml
agent:
  provider: internal
  model: internal-model-name
  base_url: ${MODEL_BASE_URL}
  token_auth:
    translator_url: ${TRANSLATOR_URL}
    service_account: ${SERVICE_ACCOUNT}
    service_account_password_secret: >-
      projects/${GOOGLE_CLOUD_PROJECT}/secrets/model-translator-password/versions/3
```

服务在 FastAPI lifespan 启动期通过 ADC / GKE Workload Identity 读取该 Secret 一次，并以 `SecretStr` 驻留
在进程内；之后每次 30 秒 Token 刷新只读取内存中的密码，**不会再次调用 Secret Manager**。读取失败会使
服务启动失败而不会错误地进入 ready 状态。运行身份仅需目标 Secret 的
`roles/secretmanager.secretAccessor` 权限。生产环境应指定版本号；密码轮换时更新 Secret Version 引用并滚动
重启 Deployment，避免使用 `versions/latest`。

```yaml
# OpenAI 官方外部模型
agent:
  provider: openai
  model: gpt-4.1-mini
  api_key: ${OPENAI_API_KEY}
```

```yaml
# DeepSeek 等 OpenAI-compatible 外部模型
agent:
  provider: openai_compatible
  model: deepseek-v4-flash
  base_url: https://api.deepseek.com
  api_key: ${DEEPSEEK_API_KEY}
```

`openai` Provider 不接受 `base_url` 或 `token_auth`，并且必须提供固定 `api_key`；它不会调用公司内部
Translator 服务。`openai_compatible` 必须同时提供固定 `api_key` 和 `base_url`；`internal` Provider 必须提供
`base_url` 与 `token_auth`。

内部模型网关使用 OpenAI 协议但需要动态 Token 时，在 `agent` 下配置 `base_url` 和 `token_auth`；示例 YAML
已包含对应字段。服务会在**建立一条新的模型 HTTP 请求前**调用 `translator_url`，并把返回的 Token
作为 `ChatOpenAI` 的 `api_key`。已建立的流式响应不再刷新或校验 Token，因此 30 秒有效期不会中断该流。

Token 会在进程内缓存至距离过期 5 秒；下一条模型请求再触发刷新。并发请求共用同一把锁，避免同时请求
Token 服务。默认 Token 接口约定如下：

```json
// request
{"service_account": "...", "service_account_password": "..."}

// response
{"access_token": "...", "expires_in": 30}
```

若响应字段不同，可用 `agent.token_auth.token_field` 和 `expires_in_field` 指定。Token、密码、请求 body
和响应 body 均不会进入日志。配置动态 Token 时同样复用 `tools.root_ca_path` 指定的根证书。

## 添加自定义 Tool

参考 `src/tools/echo.py`：用 `@tool` 定义一个无运行时依赖的函数，然后在
`src/tools/registry.py` 的 `build()` 中把它加入 `tools` 列表。复杂 Tool（HTTP、数据库等）保持
函数本身只处理业务逻辑，由 Registry 在应用启动后注入已初始化的客户端。
