# DeepAgent Platform MVP 初始化说明

本文件是当前仓库的初始化需求说明。目标是在后续实现阶段构建一个可运行的 DeepAgent Platform MVP，类似 ChatGPT / Copilot 聊天平台，支持多轮聊天、Conversation / Message 持久化、单一 DeepAgent、多 Skill、MCP Tool、动态 JSON Schema 参数收集、PostgreSQL、LangGraph PostgreSQL Checkpointer、Local / Dev / Prod 环境以及 Streaming Chat API。

优先保证架构简单、清晰、可维护；不要引入 Supervisor、多 Agent、复杂 Workflow Engine 或额外 Parameter Engine。前端暂不实现，只提供适合 Vue / React Chat UI 的 REST 与 Streaming API。

## 1. 技术栈

后端使用 Python 3.12、FastAPI、Pydantic v2、pydantic-settings、PyYAML、SQLAlchemy 2.x Async、asyncpg、PostgreSQL、Alembic、DeepAgents、LangGraph、langgraph-checkpoint-postgres、psycopg3、MCP Python SDK 与 httpx。

数据库访问分为两套、但访问同一个 PostgreSQL：

```text
业务数据库：SQLAlchemy Async → asyncpg → PostgreSQL
Checkpointer：AsyncPostgresSaver → psycopg3 → PostgreSQL
```

## 2. 环境与数据库连接

所有运行配置均使用 YAML 管理，不再使用 `.env` 作为配置来源。`AGENT_ENV=local | dev | prod` 选择配置文件；YAML 值可用 `${ENV_VAR}` 或 `${ENV_VAR:-default}` 引用环境变量，适合注入密码与 token。除 `AGENT_ENV` 和 YAML 显式引用的变量外，应用不得读取其他环境变量。数据库环境差异只能存在于配置层或 database factory；业务代码不得出现 `if env == "dev"` 一类判断。

### local

使用普通用户名密码，配置位于未提交的 `config/local.yaml`：

```yaml
agent_env: local
database:
  host: localhost
  port: 5432
  name: deepagent
  user: postgres
  password: postgres
api_auth_token: change-me
log_level: INFO
log_format: json
```

对应连接为 `postgresql://postgres:postgres@localhost:5432/deepagent`。

### dev / prod

应用通过 Cloud SQL Auth Proxy 连接 Cloud SQL PostgreSQL。Python 仍连接 `127.0.0.1:5432`，不集成 Cloud SQL Python Connector。Proxy 负责 Cloud SQL connectivity、TLS 与 IAM authentication；`config/dev.yaml` 与 `config/prod.yaml` 不设置数据库 password：

```yaml
agent_env: dev
database:
  host: 127.0.0.1
  port: 5432
  name: deepagent
  user: <IAM_DATABASE_USER>
api_auth_token: <STATIC_API_TOKEN>
log_level: INFO
log_format: json
```

## 3. 总体架构

```text
Client → FastAPI
           ├─ ConversationService → SQLAlchemy Async → asyncpg ─┐
           ├─ DeepAgent → Skills / MCP Tools                     ├→ PostgreSQL
           └─ Streaming      AsyncPostgresSaver → psycopg3 ─────┘
```

Conversation 数据和 Agent Checkpoint 必须分离：`ai_agent_conversation` / `ai_agent_message` 用于用户可见聊天历史，LangGraph Checkpointer 用于 Agent 状态恢复。二者以 `conversation_id == thread_id` 关联。

## 4. 目标目录

优先使用以下结构；可因 DeepAgents 最新 API 小幅调整，但不得破坏分层：

```text
src/
├── main.py
├── api/{router.py,conversations.py}
├── core/{auth.py,logging.py,request_context.py}
├── config/settings.py
├── database/{base.py,engine.py,session.py,models/}
│   └── models/{conversation.py,message.py,agent_run.py}
├── repositories/{conversation_repository.py,message_repository.py}
├── services/conversation_service.py
├── agent/{factory.py,checkpointer.py,service.py}
├── mcp/{client.py,manager.py,tools.py}
skill-packages/
└── ticket-request/SKILL.md
alembic/
config/{local,dev,prod}.example.yaml
tests/
pyproject.toml
README.md
```

## 5. Settings

使用 `pydantic_settings.BaseSettings` 加自定义 YAML settings source，并以 `AGENT_ENV` 选择 `config/{AGENT_ENV}.yaml`。运行时只读取这一份 YAML，不读取 `.env` 或其他环境变量。实际 `config/{local,dev,prod}.yaml` 均不得提交；仓库只提交对应的 `*.example.yaml`，实际文件从 example 复制并填写。`.gitignore` 必须忽略 `config/*.yaml`，但保留 `config/*.example.yaml`。

配置 YAML 使用嵌套结构；Settings 将其映射为强类型配置模型。遵守“一文件一个 class”规则，`Settings`、数据库配置模型和 MCP server 配置模型必须分别放在独立模块中。Settings 至少等价包含：

```python
from pydantic import SecretStr

class Settings(BaseSettings):
    agent_env: Literal["local", "dev", "prod"]
    database: DatabaseSettings
    mcp_servers: dict[str, McpServerSettings]
    api_auth_token: SecretStr
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
```

`database.password` 在 `local` 必填，`dev` 与 `prod` 可以为空。所有环境 YAML 必须设置 `api_auth_token`，它是 MVP 阶段用于 API 访问控制的静态 token。`log_level` 控制最低日志级别，`log_format` 仅允许 `json` 或 `text`，默认 JSON。提供 `settings.async_sqlalchemy_url` 与 `settings.psycopg_url`，正确进行密码拼接与 URL encoding，且日志中绝不打印密码或 API token。

## 6. SQLAlchemy 与事务

必须使用 `create_async_engine()`、`async_sessionmaker()`、`AsyncSession`，并设置 `pool_pre_ping=True`、`expire_on_commit=False`。实现 FastAPI dependency：

```python
async def get_db_session() -> AsyncIterator[AsyncSession]:
    ...
```

正确管理 transaction 与 close；Repository 不得自行创建 Engine。不得在 Agent 推理或 MCP 调用期间持有 SQLAlchemy transaction：保存用户消息后 commit，调用 Agent，保存 assistant 消息后再次 commit。

## 7. 持久化模型与迁移

使用 PostgreSQL UUID 类型并提供 Alembic migration。除 LangGraph `AsyncPostgresSaver` 自动维护的 checkpointer 内部表外，所有业务表名必须以 `ai_agent_` 开头：

| 表 | 字段 |
| --- | --- |
| `ai_agent_conversation` | `id` UUID PK、`staff_id` string、`title` nullable、`created_at` timestamptz、`updated_at` timestamptz |
| `ai_agent_message` | `id` UUID PK、`conversation_id` UUID FK、`role`、`content` text、`created_at` timestamptz |
| `ai_agent_agent_run` | `id` UUID PK、`conversation_id` UUID FK、`user_message_id` nullable UUID、`status`、`error_message` nullable、`created_at`、`updated_at` |

`message.role` 至少支持 `user`、`assistant`、`tool`、`system`。`agent_run.status` 为 `running`、`completed` 或 `failed`。

## 8. Conversation API

实现以下接口：

```text
POST   /agent/api/conversations
GET    /agent/api/conversations?staff_id={staff_id}&page=1&page_size=20
GET    /agent/api/conversations/{conversation_id}
DELETE /agent/api/conversations/{conversation_id}
GET    /agent/api/conversations/{conversation_id}/messages
POST   /agent/api/conversations/{conversation_id}/messages
```

所有 `/agent/api/*` 端点都必须通过 `src/core/auth.py` 中名为 `require_api_token` 的 Auth dependency 鉴权。MVP 的 Auth 方法从 `Authorization: Bearer <token>` 读取 token，并以 `secrets.compare_digest` 与 `Settings.api_auth_token.get_secret_value()` 做常量时间比较；缺失或不匹配时返回统一的 `401` API error。该静态 token 只负责访问控制，不作为用户身份来源。

会话归属使用调用方显式提供的 `staff_id`：创建会话和发送消息请求体必须含 `staff_id`；列表、读取、删除和读取消息接口以必填 query parameter `staff_id` 接收它。列表接口还必须支持 `page`（默认 `1`，最小 `1`）与 `page_size`（默认 `20`，范围 `1`–`100`），并返回 `{items, page, page_size, total}`。所有接口均须校验其与 conversation 中保存的 `staff_id` 一致，不一致时返回 `403`。创建会话至少返回：

```json
{"id":"...","title":null,"created_at":"..."}
```

获取 conversation 返回基础信息；API 使用 Pydantic schema，不直接暴露 ORM Model。

## 9. 消息处理流程

`POST /agent/api/conversations/{conversation_id}/messages` 收到例如 `{"staff_id":"staff-123","content":"我要申请一个 bucket"}` 后必须：

1. 通过静态 token 鉴权，并校验 conversation 存在且归属该 `staff_id`；
2. 保存 user message；
3. 创建状态为 `running` 的 `agent_run`；
4. 使用 `thread_id = str(conversation_id)`，并将 `staff_id` 作为每次 Agent invoke / stream 的显式上下文参数调用 DeepAgent；
5. 从该 conversation 对应 checkpoint 恢复上下文并取得最终回复；
6. 保存 assistant message，更新 `agent_run` 为 `completed`；
7. 返回或 stream 给客户端。

异常时将 `agent_run.status` 更新为 `failed`，保存已脱敏的错误信息，不得写入数据库密码、token 等敏感信息。

## 10. Streaming

聊天入口优先以 SSE 响应：`Content-Type: text/event-stream`。对前端公开稳定事件格式，不直接暴露 DeepAgents / LangGraph 内部事件对象：

```text
event: token
data: {"content":"你"}

event: tool_start
data: {"name":"get_resource_schema"}

event: tool_end
data: {"name":"get_resource_schema"}

event: done
data: {...}
```

至少支持 `token`、`tool_start`、`tool_end`、`done`、`error`。前端可拼接 token、展示工具执行状态并在 done 结束生成。

## 11. 日志架构

使用 Python 标准库 `logging`，不为 MVP 引入额外日志 SDK。应用启动时在 `src/core/logging.py` 调用一次 `configure_logging(settings)`，统一配置 stdout handler、`LOG_LEVEL` 与 `LOG_FORMAT`；业务模块只能通过 `logging.getLogger(__name__)` 获取 logger，不得自行添加 handler、改变全局日志级别或直接 `print`。

`json` 格式必须输出单行 JSON，至少包含 `timestamp`、`level`、`logger`、`message`、`request_id`；`text` 格式仅供本地开发阅读，字段保持等价。`log_include_stacktrace` 控制异常 stack trace 是否输出；无论该值如何，异常日志都必须保留经脱敏的 `error.type` 和 `error.message`。`src/core/request_context.py` 使用 `contextvars` 保存当前请求上下文，HTTP middleware 为每个请求生成或接受 `X-Request-ID`，在响应中回传该 ID，并将其绑定到本请求派生的 Agent、MCP 与数据库日志。SSE generator 必须重新绑定 request context，避免流式响应生命周期丢失 request ID。不得把 request context 保存到全局可变对象。

记录以下结构化事件及必要字段：

- HTTP 请求结束：`method`、`path`、`status_code`、`duration_ms`、`request_id`；不记录 Authorization header、请求 body 或 SSE token 内容。
- Conversation / Agent run：`conversation_id`、`staff_id`、`agent_run_id`、`status`、`duration_ms`；不记录用户消息或模型回复正文。
- MCP 调用：`tool_name`、`outcome`、`duration_ms`、`request_id`；不记录未脱敏参数或完整 tool 返回。
- 异常：使用 `logger.exception` 记录 stack trace，并仅记录经脱敏的错误摘要；不得记录密码、API token、Authorization header、完整 message 内容或敏感 MCP 参数。SSE 异常必须生成 `error_id`，写入日志并以稳定 `event: error` 返回客户端；客户端断连记录为 cancelled，不得误报为 Agent failed。

日志只写 stdout，由 local / dev / prod 的运行平台负责采集；不创建业务日志表，也不将日志写入 PostgreSQL。`staff_id`、`conversation_id` 等标识如属于敏感数据，应遵循部署环境的日志访问控制与保留策略。

### Langfuse 可选观测

Langfuse 为可选观测组件，不参与 `/health` readiness。新增 `langfuse` YAML 配置：`enabled`、`base_url`、可选
`release` 以及认证来源。Trace 的 Langfuse `environment` 必须直接使用 `settings.agent_env`，禁止再配置一套独立
environment 值。`release` 用于 Git SHA、镜像 tag 等发布版本标记，可为空。

local 在 `enabled=true` 时必须使用 `public_key` 与 `secret_key` 的直接值（通常由 YAML 的环境变量引用提供）；
dev / prod 在 `enabled=true` 时必须使用 `public_key_secret` 与 `secret_key_secret` 的 Google
Secret Manager 完整 Version resource name。每个 Key 只能使用一个来源。`enabled=false` 时不读取 Key 或 Secret
Manager。Key 均使用 `SecretStr`，启动期读取一次后仅存入 RuntimeSecrets，运行期不得重复读取 Secret Manager。

FastAPI lifespan 在启用时初始化 Langfuse Client；每个 Graph `astream` 调用创建独立 LangChain Callback Handler，
并携带 `conversation_id`、`agent_run_id`、`staff_id` 和 `agent_env` metadata。Langfuse 导出前必须递归脱敏键名包含
`password`、`secret`、`token`、`authorization` 的值。shutdown 使用有界异步方式 flush / shutdown，不得阻塞事件
循环；Langfuse 上报失败只记录脱敏 warning，不得使 Agent Run 或服务 readiness 失败。

## 12. DeepAgent 与 Checkpointer

创建 Agent Factory，通过 `create_deep_agent(...)` 创建一个主 DeepAgent。Agent 从 `agent.skills_dir` 加载 `agent.enabled_skills` 所列 Skill 目录，支持 MCP Tools、使用 PostgreSQL Checkpointer、以 conversation ID 作为 thread ID、支持 async invoke / stream。Agent 自主根据用户问题选择并遵循适用 Skill；新增 Skill 只需新增 `SKILL.md` 并在 YAML 启用，不得改 API Router 或硬编码意图路由。每次调用 Agent 必须在输入或运行时 context 中显式携带 `staff_id`，以便 Skill 和 MCP Tool 在后续实现中取得当前员工上下文；不得从静态 API token 推导或伪造 staff ID。禁用 DeepAgents 默认 general-purpose subagent；不得创建 Supervisor、多个 Agent、独立 Planner 或 Parameter Engine。

使用官方 `AsyncPostgresSaver` 与 psycopg3，连接地址来自 `settings.psycopg_url`。连接池生命周期绑定 FastAPI lifespan：启动时初始化 SQLAlchemy engine、sessionmaker、psycopg pool、AsyncPostgresSaver、DeepAgent；关闭时关闭 MCP 资源、checkpointer pool 并 dispose SQLAlchemy engine。首次启动调用 checkpointer 所需 setup/migration，但不得手工创建或修改其内部表。

继续会话时固定使用：

```python
config = {"configurable": {"thread_id": str(conversation_id)}}
```

页面重开通过 `GET /agent/api/conversations/{id}/messages` 恢复可见历史；再次发消息则由 checkpoint 恢复 Agent 上下文。

## 13. Ticket Request Skill

创建 `skill-packages/ticket-request/SKILL.md`，用于资源申请：

```text
用户提出资源申请
→ 识别 resource_type
→ MCP get_resource_schema
→ 按动态 JSON Schema 收集参数
→ 缺参数时自然语言继续询问
→ validate_ticket_params
→ 无效时按错误继续询问
→ 有效后 create_ticket
→ 返回 ticket id
```

Skill 必须明确：

1. 不得猜测 required 参数；resource type 确定后必须调用 `get_resource_schema`。
2. 依据 JSON Schema 收集参数；一次用户输入可提供多个字段，用户可修改先前字段，始终以最新值为准。
3. 创建前必须调用 `validate_ticket_params`；失败后继续自然语言追问。
4. 只有 validation 成功才调用 `create_ticket`。
5. 不将原始 JSON Schema 直接发给用户，而是转换成自然语言。

## 14. MCP 抽象与 Mock

支持多个 MCP Server。`mcp_servers` 是以稳定 server ID 为 key 的 YAML map；每个 server 定义 `transport`（`http`、`stdio` 或 `mock`）、连接地址或 command、可选 args、headers、timeout、重连策略与允许暴露给 Agent 的 `tools`。headers 支持 YAML 环境变量引用，用于服务端 Bearer Token 等凭据，且不得写入日志。示例：

```yaml
mcp_servers:
  ticketing:
    transport: http
    url: https://mcp.example.internal/ticketing
    headers:
      Authorization: Bearer ${TICKETING_MCP_TOKEN}
    timeout_seconds: 15
    reconnect_initial_delay_seconds: 1
    reconnect_max_delay_seconds: 30
    tools:
      - get_resource_schema
      - validate_ticket_params
      - create_ticket
  knowledge:
    transport: stdio
    command: python
    args: ["-m", "knowledge_mcp"]
    timeout_seconds: 10
    tools: [search_knowledge]
  demo_ticketing:
    transport: mock
    tools:
      - get_resource_schema
      - validate_ticket_params
      - create_ticket
```

`src/mcp/manager.py` 负责根据配置创建、保存并关闭每个 MCP client 的连接资源；FastAPI lifespan 启动时仅校验配置并初始化每个 server 的锁，首次需要该 server 的 Tool 调用时才建立连接，关闭时释放已建立的 client。单个 server 首次连接失败时，应用应记录该 server ID 并按配置将其标为不可用；不应阻止其他 MCP Server、非依赖该 server 的聊天请求或整个应用启动。调用失败必须映射为受控 MCP error，包含 server ID 与工具名但不包含敏感参数。

MCP 服务在应用启动后重启或断连时必须支持恢复：连接异常、transport 异常或连续超时都将对应 server 标记为 disconnected，并关闭失效 client。下一次需要该 server 的 Tool 调用前，Manager 使用每个 server 独立的 async lock 确保仅一个协程执行 reconnect；按 `reconnect_initial_delay_seconds` 到 `reconnect_max_delay_seconds` 做指数退避，并在连接成功后重置退避。重连期间，依赖该 server 的调用快速返回受控 `MCP_UNAVAILABLE` error，其他 server 继续可用。成功或失败的连接、断开与重连事件必须记录 `server_id`、`attempt`、`outcome` 与 `duration_ms`，不记录连接凭据。

对因断连导致的 in-flight Tool 调用，不透明地重放请求：只读 MCP Tool 可在 client 重连成功后重试一次；写 Tool（包括 `create_ticket`）不得自动重试，除非 MCP 的明确幂等契约和 idempotency key 已配置。用户可在错误提示后重新发起请求。

工具在 Agent registry 中必须使用 `server_id__tool_name` 作为唯一名称，例如 `ticketing__get_resource_schema` 与 `knowledge__search_knowledge`，以避免跨 server 重名。Skill 通过配置的稳定 server ID 调用所需工具；Ticket Request Skill 固定使用 `ticketing__get_resource_schema`、`ticketing__validate_ticket_params` 与 `ticketing__create_ticket`。`tools` 白名单以外的 MCP Tool 不得注册给 Agent。

提供可替换的 client 层，使后续接入真实 server 时无需修改 Agent Service。Ticketing MCP Server 预期工具：

```text
get_resource_schema(resource_type)
validate_ticket_params(resource_type, parameters)
create_ticket(resource_type, parameters)
```

`get_resource_schema({"resource_type":"bucket"})` 示例返回：

```json
{
  "type":"object",
  "properties":{
    "region":{"type":"string","enum":["us-east1","us-west1"]},
    "storage_class":{"type":"string","enum":["STANDARD","NEARLINE"]},
    "retention_days":{"type":"integer","minimum":1}
  },
  "required":["region","storage_class"]
}
```

`validate_ticket_params` 返回 `valid`、`missing`、`errors`；`create_ticket` 只能在 validation 成功后调用，示例返回 `{"ticket_id":"REQ-10001","status":"created"}`。`mock` transport 用于 local 与测试，可为一个或多个 server 提供独立的 Fake implementation；测试不得依赖真实 MCP Server。

### 用户确认型 MCP Tool

有副作用的 Tool 可在所属 `McpServerSettings.confirmation_required_tools` 中声明，且必须同时存在于该 server 的
`tools` allowlist。例如 `confirmation_required_tools: [create_ticket]` 会生成 `ticketing__create_ticket` 的
DeepAgents `interrupt_on` 规则。Agent 在调用前暂停，Tool 尚未实际执行，API SSE 返回：

```text
event: confirmation_required
data: {"tool_name":"ticketing__create_ticket", "description":"Confirm ticket creation"}
```

只有 conversation 所属的 `staff_id` 可以调用
`POST /agent/api/conversations/{conversation_id}/tool-confirmations`。`action: approve` 用同一
`thread_id = conversation_id` 恢复 checkpoint 并执行 Tool；`action: reject` 用 LangGraph HITL reject 决策恢复，
Tool 不执行，Agent 自然回复已取消。用户关闭页面时运行状态保持 `awaiting_confirmation`，之后可继续操作。
这不是多人审批：不引入审批人、转交或审批流；当前 MVP 每次只允许一个等待确认的 Tool 调用。

### Danaan Cloud Resource

`skill-packages/danaan-cloud-resource/SKILL.md` 负责 Danaan Cloud Storage、BigQuery 和 Cloud SQL 创建申请。它读取 staff scoped memory 中的
`danaan-cloud-resource:base-context`，但必须先通过 `request_user_form` 让用户确认沿用或重新选择
`resourceOnboardRegion`、`applicationName`、`eimId`、`envName`、`useCaseShortName`；长期记忆绝不能静默
覆盖本轮用户输入。`request_user_form` 使用 HITL `respond` 决策暂停，并映射为：

```text
event: form_required
data: {"form_name":"...", "title":"...", "fields":[...], "prefilled_values":{...}}
```

前端以 `POST /agent/api/conversations/{conversation_id}/tool-confirmations`、`action: respond` 与 JSON object
`response` 恢复同一线程。表单 Tool 只传递 UI 定义，不承担参数校验或记忆写入。

模板读取由应用内 `danaan_get_resource_template(resource_name)` 完成，而非 MCP。它为每次 Tool 调用新建
独立 SQLAlchemy Session，并通过独立的 `CloudResourceTemplateInfo` SQLAlchemy Model 查询 Danaan 管理的
`public.cloud_resource_template_info`：按 `cloud_resource_name = :resource_name` 过滤，并按
`req_time DESC NULLS LAST, res_template_id DESC` 取最新 `template_content`。该外部表不能写入 ORM model 或
Alembic migration；部署数据库账号需要最小化的 `SELECT` 权限。查询无结果时 Skill 必须停止创建流程并告知用户。
最终申请调用 `danaan__external_resource_add`，它必须配置为 confirmation-required，只有用户 `approve` 后执行。

## Harness 与 Skill 扩展

生产路径只有一个 root DeepAgent：Agent Factory 从 YAML `agent.model`、`agent.skills_dir` 和 `agent.enabled_skills` 创建它，注册全部 MCP allowlisted tools，并使用 PostgreSQL checkpointer。每个 Skill 都是独立目录中的 `SKILL.md`；Agent 根据用户问题自行选择适用 Skill。`FilesystemBackend` 的 root 必须是 `agent.skills_dir`，并用 filesystem permission 禁止所有 write；Agent 只能读取/搜索 Skill 文件，不能浏览项目源码、YAML、迁移或写入宿主文件系统。新增业务能力时优先新增 Skill、配置其 MCP server/tool allowlist 并补充测试，不要增加新的 Agent、Router 分支或 Python 关键字意图路由。

未设置 `agent.model` 的 local/test 环境允许启用 deterministic Mock harness，只用于验证 API、会话、SSE 和 Mock MCP；它不是生产 Agent 实现。真实模型凭据通过 YAML 的 `${ENV_VAR}` 引用注入，绝不写入仓库、日志或 API 响应。

模型来源由 `agent.provider` 明确选择：`internal` 代表公司内部 OpenAI-compatible 网关，必须配置
`agent.base_url` 与 `agent.token_auth`；`openai` 代表 OpenAI 官方外部模型，必须配置固定
`agent.api_key`，且禁止 `base_url` 与 `token_auth`；`openai_compatible` 代表 DeepSeek 等兼容 OpenAI 协议的
外部模型，必须配置固定 `agent.api_key` 与 `agent.base_url`，且禁止 `token_auth`。内部 Token 配置包含 `translator_url`、`service_account_name`、
`service_account_password`、`token_ttl_seconds`（默认 30）、`refresh_before_expiry_seconds`（30 秒 Token 推荐为 5）和 `request_timeout_seconds`。
Agent Factory 仅对 internal Provider 使用 `ChatOpenAI(api_key=token_provider.get_token)`：每一条新的
模型 HTTP 请求建立前，Token Provider 才按需请求或复用 Token；已建立的 SSE 流不再续期或重复校验 Token。默认
translator request 为
`{"input_token_state":{"token_type":"CREDENTIAL","username":"...","password":"..."},"output_token_state":{"token_type":"JWT"}}`，
response 为 `{"issued_token":"..."}`。Translator 不返回有效期，因此 Token Provider 按 `token_ttl_seconds`
缓存，并在距离该本地有效期 `refresh_before_expiry_seconds` 时刷新；前者必须大于后者。不同 Token 字段可通过
`token_field` 配置。Token Provider 以单锁去重，Token、密码和 HTTP body 禁止进入日志。

## 自定义 Tool 与外部 HTTP

应用内自定义 Tool 放在 `src/tools/`，与 `src/mcp/` 的远程 MCP Tool 分层管理。示例 `get_configured_service_status` 只访问 YAML `tools.external_status_url` 指定的 allowlisted 地址，模型不得传入任意 URL。所有外部 HTTP 调用（包括 dynamic model token 和内部 ChatOpenAI 模型网关请求）复用 FastAPI lifespan 创建的专用 `httpx.AsyncClient`，使用 `tools.root_ca_path`（默认 `build/root.cer`）作为 TLS 根证书、禁用环境代理与重定向，并在 shutdown 关闭连接池。启用外部 Tool 或内部动态 Token 模型时，根证书缺失或为空必须启动失败；日志只记录 host、状态码和耗时，不记录 headers、token、URL query 或响应正文。

## 长期记忆

LangGraph checkpointer 只保存单个 `conversation_id` 的会话与 Agent 状态，长期记忆使用独立的 `AsyncPostgresStore`，但可连接同一个 PostgreSQL。memory namespace 固定为 `("staff", staff_id, "memory")`，以确保不同员工永不共享记忆。每次真实 Agent 调用前，从该 namespace 读取最多 100 条显式保存的 memory，作为只读 `context.memories` 注入运行时上下文。

MVP 只支持显式 API 管理记忆：`PUT /agent/api/memories/{key}`、`GET /agent/api/memories?staff_id=...`、`DELETE /agent/api/memories/{key}?staff_id=...`。memory value 只允许字符串字段；不得自动提炼所有聊天内容，也不得保存 password、token、Authorization、完整工单内容或敏感 MCP 输出。后续若启用自动提炼，必须经独立 MemoryService 的敏感字段过滤、明确同意策略和审计。

`danaan-base-context` 是受控例外：用户提交 Danaan 基础资料表单即确认保存。后端仅提取
`resourceOnboardRegion`、`applicationName`、`eimId`、`envName`、`useCaseShortName`，以 key
`danaan-cloud-resource:base-context` 写入 `("staff", staff_id, "memory")` namespace。Harness 每次调用时
必须通过 exact key 读取该值为 `context.danaan_base_context`，不能依赖模型从全部 memory 列表中猜测；再次使用前
仍需用户确认。

## 响应语言

每次用户消息独立决定 **Agent 自然语言回复**：只要 `content` 包含任意中文字符，DeepAgent 和 Mock fallback 均以中文为主；完全不含中文时以英文为主。Ticket ID、字段名、枚举值、Tool 名、URL、代码、产品名和 error code 不翻译。API JSON、认证、校验、SSE `error` 事件和其他系统固定文案始终使用英文。不要翻译已存储的历史消息。

`agent.system_prompt` 必须声明 Skill 文档、Tool 描述、memory、示例和历史消息的语言不能决定 Agent 回复语言。
`ResponseLanguageMiddleware` 在每次模型调用前从 runtime `response_language` 临时附加权威指令，覆盖 Tool
调用与 LangGraph checkpoint 恢复；该指令不得写入可见聊天记录或 checkpoint 消息。前端 UI、表单字段、SSE
协议事件、确认按钮和 API 系统文案始终使用英文，只有 Agent 的自然语言 token 与最终 Markdown 确认摘要使用动态语言。

## 15. Repository / Service 分层与错误处理

Repository 只负责数据库 CRUD（例如 ConversationRepository 的 `create`、`get`、`list`、`delete`）；Service 负责业务（例如 ConversationService 的 `create_conversation`、`send_message`）。Router 不直接写 SQLAlchemy query；Agent Service 不直接操作 ORM Model。依赖方向必须清晰。

统一 API error，例如：

```json
{"code":"CONVERSATION_NOT_FOUND","message":"Conversation not found"}
```

至少处理未认证、无权限访问其他 staff 的 conversation、conversation 不存在、DB error、MCP error、Agent error、validation error 与 streaming 中断。MCP 临时失败不得导致数据库 transaction 长时间保持。

## 16. README 与运行方式

README 至少说明本地 PostgreSQL：

```bash
docker run \
  --name deepagent-postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=deepagent \
  -p 5432:5432 \
  postgres:16

alembic upgrade head
uvicorn src.main:app --reload
```

并说明配置加载方式：运行时仅设置 `AGENT_ENV` 来选择 `config/{AGENT_ENV}.yaml`，从同名 `*.example.yaml` 复制生成实际配置文件；实际 YAML 含数据库密码或 API token 时不得提交。并说明 dev/prod 架构：

```text
FastAPI → 127.0.0.1:5432 → Cloud SQL Auth Proxy → IAM Auth → Cloud SQL PostgreSQL
```

Proxy 示例（不得硬编码实例连接名）：

```bash
cloud-sql-proxy --auto-iam-authn --port 5432 "${CLOUD_SQL_INSTANCE}"
```

Python 的 dev/prod YAML 配置不设置数据库密码。

## 17. 测试

至少实现：

```text
tests/test_settings.py
tests/test_conversation_repository.py
tests/test_conversation_api.py
tests/test_agent_service.py
```

覆盖：YAML 按 `AGENT_ENV` 正确加载、local 必须有 password、dev/prod 可无 password、缺失或错误静态 token 返回 401、staff 不能读取或写入其他 staff 的 conversation、conversation 创建、user/assistant message 保存与恢复、conversation ID 正确传入 thread ID、每次 Agent 调用正确携带 staff ID 上下文、多个 MCP 的连接生命周期与工具命名空间隔离、MCP 重启后的断连标记与下一次调用重连、只读 Tool 单次重试、写 Tool 不自动重试、MCP schema 后继续交互、Mock `create_ticket`、Agent 出错时 `ai_agent_agent_run=failed`、`X-Request-ID` 回传与跨 HTTP/Agent/MCP 日志关联、日志不泄露 password/token/message 正文。测试不得依赖真实 Cloud SQL；无法使用真实 LLM 时 mock Agent / MCP。

## 18. 编码约束

- Python 3.12、async-first、完整 type hints，避免滥用 `Any`。
- 每个 Python 文件只允许定义一个 `class`；存在多个领域对象或服务时，必须按职责拆分到独立模块。
- 不创建巨大 service class、无意义 wrapper 或没有实际用途的抽象层；不使用 global mutable state，不将 Session 保存在 singleton。
- async function 中不得有同步阻塞 IO；日志不得记录 password / token。
- 公共函数和核心类使用简洁 docstring。
- 避免大量 `if/else` workflow；参数收集交由 DeepAgent + Skill，最终校验交给 MCP Tool。

## 19. 实施顺序与验收

按顺序实现并验证：

1. YAML Settings、database engine/session、ORM models、Alembic；
2. Conversation Repository、Service、API；
3. Postgres Checkpointer、DeepAgent Factory、Agent Service；
4. ticket-request SKILL 与 Mock MCP Tools；
5. Streaming、Auth、日志、error handling、tests、README。

完整验收对话：用户发送“我要申请一个 bucket”，Agent 调用 `get_resource_schema`，自然询问 `region` 与 `storage_class`；用户回复“us-east1，用 STANDARD”后，Agent 调用 `validate_ticket_params` 与 `create_ticket`，并返回 `REQ-10001`。用户离开页面后可读取完整 message 历史，使用同一 conversation ID 再发消息时可由 PostgreSQL checkpoint 恢复上下文。local 用户名/密码模式与 dev/prod 经 Cloud SQL Auth Proxy + IAM 模式均须可用。

## 20. 实施前检查

开始实现前检查已有目录、`pyproject.toml`、Python 版本、已安装依赖、现有 FastAPI / DeepAgent / MCP client / 数据库代码。优先复用已有实现；发生架构冲突时做小范围重构，避免推倒重来。实现阶段需实际创建/修改代码、补充依赖、创建 migration 与测试，运行测试并修复问题，最后总结改动、架构选择、启动方式和仍需提供的外部配置。
