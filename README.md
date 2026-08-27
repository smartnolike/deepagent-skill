# DeepAgent Platform MVP

Copy a YAML template and provide a local static API token:

```bash
cp config/local.example.yaml config/local.yaml
export AGENT_ENV=local
```

YAML 可以引用启动环境变量，例如 `api_auth_token: ${API_AUTH_TOKEN}` 或 MCP header
`Authorization: Bearer ${DANAAN_MCP_TOKEN}`。未提供且没有默认值的引用会使启动失败。

日志由 `log_level`、`log_format` 和 `log_include_stacktrace` 控制。未预期异常会产生带 `error_id` 的脱敏
结构化日志；SSE 失败事件也会返回该 `error_id`，便于按日志定位。`log_include_stacktrace: false` 可保留异常类型与
脱敏消息，但不输出完整堆栈。

应用内自定义 Tool 位于 `src/tools/`。如启用 `tools.danaan_json_schema_url`（例如
`https://<host>/api/terraform/schemas`），服务会注册 `danaan_json_schema(resourceVersion)`；该 Tool 会对
`{base_url}/{resourceVersion}` 发起受控 GET，例如 `resourceVersion=cloudsql522` 请求
`/api/terraform/schemas/cloudsql522`。服务会复用专用的
`src/common/httpx_client.py` 中的 `HttpxClient` 并强制以 `build/root.cer` 校验外部 API TLS 证书。该证书当前必须由部署环境
提供有效 PEM/CA 内容；空文件或缺失文件会使启用外部 Tool 的应用启动失败。

Start PostgreSQL, migrate, and run the API:

```bash
docker run --name deepagent-postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=deepagent -p 5432:5432 postgres:16
alembic upgrade head
uvicorn main:app --app-dir src --reload
```

Windows 使用 psycopg3 的异步 Checkpointer 时，请通过项目启动器运行，不要直接使用 `uvicorn` CLI：

```bat
set AGENT_ENV=local
.\.venv\Scripts\python.exe src\main.py
```

项目启动器会显式指定 `asyncio:SelectorEventLoop`，因为 psycopg3 不兼容 Windows 默认的
`ProactorEventLoop`。PyCharm Run Configuration 应运行 `src/main.py`，而不是 FastAPI / Uvicorn 类型的配置。

`GET /health` 不需要认证，并在应用、PostgreSQL、Checkpointer 与 Agent 初始化完成后返回 `{"status":"ok"}`。
已启用的 MCP 在服务启动时必须完成连接、`initialize()` 与 `list_tools()`；应用仅将 YAML 白名单中的
真实 Tool Schema 注册给 DeepAgent。任一启用 MCP 不可用、或缺少白名单 Tool 时，应用启动失败。运行中 MCP
服务重启导致 Session 失效时，应用会自动建立新 Session 并使用原始参数重试该 Tool 一次；再次失败时返回受控错误。
所有 `/agent/api/*` calls require `Authorization: Bearer <api_auth_token>`。local、dev、prod 都必须配置真实
`agent.model`、PostgreSQL 与 HTTP MCP；测试中的 Agent、数据库与 MCP 替身仅在测试层注入，生产代码不提供 Mock fallback。
DeepAgent Skill 位于与 `src/` 同级的 `skill-packages/`，通过 YAML 的 `agent.enabled_skills` 启用。

## 会话工作区与 Sandbox Backend

`sandbox.provider` 支持三种模式：`filesystem` 仅只读加载 Skill，适合最快的本地指令测试；
`local_shell` 为每个会话创建独立本机工作区并暴露原生 `execute`，适合集成测试；`gke_backend`
为每个会话创建或重连一个 GKE Agent Sandbox，供 dev/prod 使用。GKE 客户端固定为
`k8s-agent-sandbox==0.4.6`，以匹配当前托管控制器的 `v1alpha1` API。

Skill 源码目录不改名，仍为 `skill-packages/`。Sandbox runtime 镜像将它复制到只读的
`/workspace/skill-packages`；脚本的中间文件放 `/workspace/work`，供后续脚本继续读取；最终文件写入
`/workspace/output`（也可用短路径 `/work`、`/output`）。Agent 调用 `publish_artifact` 后，前端从当前
Sandbox 实时下载文件；没有 GCS 或其他对象存储兜底，因此 Sandbox 到期后下载接口返回 `410`。

`sandbox.execute_requires_confirmation` 默认为 `true`，会让 DeepAgents 原生 `execute` 进入 HITL 审批。
GKE 环境可显式改为 `false`；`local_shell` 开启执行能力时强制保留审批，防止本地误执行。完整配置、
生命周期和镜像约定见 [工作区 Backend 设计](docs/WORKSPACE_SANDBOX_BACKENDS.md)。

`danaan-cloud-resource` 的 `danaan-base-context` 表单提交后，会自动保存
`resourceOnboardRegion`、`applicationName`、`eimId`、`envName` 与 `useCaseShortName` 到 LangGraph
PostgreSQL Store 的 `danaan-cloud-resource:base-context` key。下一次 Danaan 申请会精确读取该 key，并要求
用户确认沿用或重新填写；完整模板和工单 payload 不会保存。

## 用户确认型 MCP Tool

对会产生副作用的 MCP Tool，在对应 server 配置 `confirmation_required_tools`；例如示例中的
`external_resource_add`。Agent 准备调用该 Tool 时会暂停、持久化 `ai_agent_tool_confirmation` 记录并通过 SSE 返回
`confirmation_required`，而不会执行 Tool。SSE 包含 `confirmation_id`、脱敏后的 `display_arguments` 与当前状态；页面刷新后可用
`GET /agent/api/conversations/{conversation_id}/tool-confirmations?staff_id=...` 恢复待审批卡片。

仅会话所属的 `staff_id` 可通过以下接口继续该运行：

```text
POST /agent/api/conversations/{conversation_id}/tool-confirmations/{confirmation_id}
{"staff_id":"...", "action":"approve"}  # 执行 Tool
{"staff_id":"...", "action":"reject"}   # 取消当前 Tool，不执行
```

审批记录只允许从 `pending` 决定一次，重复点击不会再次恢复或执行 Tool。确认与取消都使用相同的
`conversation_id` / LangGraph `thread_id` 恢复状态；用户离开页面后可以继续确认。
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

`danaan__external_resource_add` 的 `creator` 不由模型或前端填写。MCP 配置会从当前运行时的 `staff_id`
强制注入该字段，并固定注入空的 `creatorName` / `creatorEmail`；这些内部字段不会出现在 Tool schema、表单或确认摘要中。

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
    service_account_name: ${SERVICE_ACCOUNT_NAME}
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
    service_account_name: ${SERVICE_ACCOUNT_NAME}
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

Translator 响应不提供过期时间，因此 Token 生命周期由配置中的 `token_ttl_seconds` 明确声明，默认 30 秒。
Token 会在进程内缓存至距离过期 5 秒；下一条模型请求再触发刷新。并发请求共用同一把锁，避免同时请求
Token 服务。`refresh_before_expiry_seconds` 必须小于 `token_ttl_seconds`。默认 Token 接口约定如下：

```json
// request
{
  "input_token_state": {
    "token_type": "CREDENTIAL",
    "username": "...",
    "password": "..."
  },
  "output_token_state": {"token_type": "JWT"}
}

// response
{"issued_token": "..."}
```

若响应字段不同，可用 `agent.token_auth.token_field` 指定。Token、密码、请求 body 和响应 body 均不会进入
日志。配置内部动态 Token 模型时，Translator 与 ChatOpenAI 都复用 `tools.root_ca_path` 指定的根证书。

## Langfuse 可选观测

Langfuse 使用 `agent_env` 自动标记 Trace 的 `environment`（`local`、`dev` 或 `prod`），无需额外配置环境名。
`release` 是可选的发布版本标签，建议在 CI/CD 设置为 Git SHA 或镜像 tag。

local 可通过环境变量或未提交的 `config/local.yaml` 直接提供 Key：

```yaml
langfuse:
  enabled: ${LANGFUSE_ENABLED:-false}
  public_key: ${LANGFUSE_PUBLIC_KEY:-}
  secret_key: ${LANGFUSE_SECRET_KEY:-}
  base_url: ${LANGFUSE_BASE_URL:-https://cloud.langfuse.com}
  release: ${RELEASE_VERSION:-}
```

dev / prod 启用时只接受 Google Secret Manager 的完整 Secret Version resource name：

```yaml
langfuse:
  enabled: ${LANGFUSE_ENABLED:-false}
  public_key_secret: ${LANGFUSE_PUBLIC_KEY_SECRET:-}
  secret_key_secret: ${LANGFUSE_SECRET_KEY_SECRET:-}
  base_url: ${LANGFUSE_BASE_URL:-https://cloud.langfuse.com}
  release: ${RELEASE_VERSION:-}
```

服务启动时读取两个 Secret 一次并只保存在进程内；之后每次 Agent 调用复用内存 Key，不会重复访问 Secret
Manager。启用时会采集 LangGraph、模型和 Tool 调用，并以 `conversation_id`、`agent_run_id` 与 `staff_id`
关联 Trace。`password`、`secret`、`token` 与 `authorization` 等字段在导出前会脱敏。Langfuse 不属于
`/health` readiness 依赖；其上报故障不应阻断聊天服务。

## 添加自定义 Tool

参考 `src/tools/echo.py`：用 `@tool` 定义一个无运行时依赖的函数，然后在
`src/tools/registry.py` 的 `build()` 中把它加入 `tools` 列表。复杂 Tool（HTTP、数据库等）保持
函数本身只处理业务逻辑，由 Registry 在应用启动后注入已初始化的客户端。
