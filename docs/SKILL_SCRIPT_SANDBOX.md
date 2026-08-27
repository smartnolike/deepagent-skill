# Skill 脚本执行与 Sandbox 设计（历史稿）

> 状态：旧的一次性受控 Job / GCS 方案，已由 [WORKSPACE_SANDBOX_BACKENDS.md](WORKSPACE_SANDBOX_BACKENDS.md) 取代。本文仅保留设计过程。

> 状态：设计提案。当前项目尚未实现脚本执行器、GKE Job 或 DeepAgent SandboxBackend。

## 目标

平台中的 Skill 除 `SKILL.md` 指令外，未来可能携带由平台团队开发、评审并随版本发布的 Python 脚本。例如：

- 查询计费数据；
- 查询 Jira Issue；
- 调用 Danaan 创建资源；
- 生成固定格式的业务报告。

这些脚本是可信的业务代码，但 Agent 输入、外部系统响应和运行资源仍不可信。因此执行能力必须具备：

- 固定入口与输入 Schema；
- 最小网络和云权限；
- 超时、资源限制、审计与幂等；
- 不影响 FastAPI / DeepAgent 主服务；
- local 易调试，dev / prod 可在 GKE 上安全运行。

## 当前状态

当前 `FilesystemBackend` 只用于读取 `skill-packages/*/SKILL.md`，且配置禁止写入。它不是进程 Sandbox，也不会自动执行 Skill 目录中的 `.py` 文件。

因此，仅将 Python 文件放到 Skill 包中不会让 Agent 获得执行能力。必须通过注册的应用内 Tool 调用专门的脚本执行服务。

## 方案对比

| 方案 | 执行位置 | 适用范围 | 文件状态 | 推荐环境 |
| --- | --- | --- | --- | --- |
| 本地子进程 | FastAPI Pod / 本机进程 | 开发调试、短且可信的固定脚本 | 与当前进程共享，不应依赖 | local |
| GKE Job | 独立、短生命周期 Runner Pod | 固定业务 Skill 脚本 | 单次执行，不保留 | dev / prod |
| 持久 SandboxBackend | 独立 gVisor Sandbox Pod | 动态代码、反复编辑和运行 | 在 Sandbox 生命周期内保留 | 后续按需引入 |

## 推荐决策

第一阶段采用“受控脚本执行器”。

```text
local     → 白名单脚本的本地子进程
dev/prod  → 白名单脚本的 GKE Job
```

不向 Agent 暴露原始 Shell `execute`。DeepAgent 只能调用具备业务语义的 Tool；每个 Tool 最终由同一个 `ScriptExecutionService` 调度。

持久 SandboxBackend 仅在确实需要“Agent 写 Python → 执行 → 读取结果 → 修改后再次执行”的多步工作区时引入。

## 受控脚本执行模型

```text
SKILL.md
  ↓ 指定何时调用及参数收集规则
业务语义 Tool
  ↓ 例如 billing_get_monthly_cost(...)
ScriptExecutionService
  ↓ 校验脚本注册信息、输入、确认状态与幂等键
Runner
  ├── local：受限子进程
  └── dev/prod：GKE Job
  ↓
结构化结果
  ↓
Agent 根据结果回复用户
```

禁止把模型生成的命令、脚本路径、镜像名或环境变量直接传入执行器。

不允许：

```text
run_skill_script(command="python arbitrary.py --input ...")
```

允许：

```text
billing_get_monthly_cost(project_id="payment-platform", month="2026-08")
```

或在脚本数量较多时：

```text
run_skill_script(
  script_id="billing-query.monthly-cost",
  input={"project_id": "payment-platform", "month": "2026-08"}
)
```

`script_id` 必须来自平台的静态注册表，不能由用户或模型任意指定。

## 脚本注册表

注册表是执行层的权威来源。可使用 Python 配置或 YAML；其职责不是替代 `SKILL.md`，而是定义可执行能力的安全边界。

示例：

```yaml
scripts:
  billing-query.monthly-cost:
    skill_id: billing-query
    entrypoint: python -m skill_scripts.billing.monthly_cost
    input_schema: BillingMonthlyCostInput
    result_schema: BillingMonthlyCostResult
    timeout_seconds: 30
    runner_profile: billing-readonly
    requires_confirmation: false

  jira-query.search-issues:
    skill_id: jira-query
    entrypoint: python -m skill_scripts.jira.search_issues
    input_schema: JiraSearchInput
    result_schema: JiraSearchResult
    timeout_seconds: 30
    runner_profile: jira-readonly
    requires_confirmation: false

  danaan-cloud-resource.create:
    skill_id: danaan-cloud-resource
    entrypoint: python -m skill_scripts.danaan.create_resource
    input_schema: DanaanCreateInput
    result_schema: DanaanCreateResult
    timeout_seconds: 60
    runner_profile: danaan-write
    requires_confirmation: true
```

每个脚本都必须：

1. 有输入和输出 Pydantic Schema；
2. 有固定的 timeout 和 runner profile；
3. 显式声明是否属于有副作用操作；
4. 使用固定入口点，禁止传递 Shell 字符串；
5. 由 CI 测试并随 Runner 镜像一起发布。

## 业务语义 Tool 与通用执行器

推荐对 Agent 暴露业务语义 Tool，而不是优先暴露一个万能 Tool：

```text
billing_get_monthly_cost(...)
jira_search_issues(...)
danaan_create_resource(...)
```

这些 Tool 在内部统一调用：

```text
ScriptExecutionService.run(script_id, input, runtime_context)
```

这样 Agent 不需要猜测 `script_id`，参数约束也更清楚。若脚本数量增长，可保留 `run_skill_script(script_id, input)` 作为内部实现，但其输入必须经过注册表校验。

## Runner 镜像与发布

所有可信脚本应随专用 Runner 镜像发布：

```text
skill-runner:<git-sha>@sha256:<digest>
├── Python runtime
├── 固定、已扫描的依赖
├── runner_entrypoint.py
└── skill_scripts/
    ├── billing/
    ├── jira/
    └── danaan/
```

执行时使用固定 image digest，记录对应 git SHA。禁止在运行时：

- `pip install`；
- 从 Git 或互联网下载脚本；
- 挂载 Agent 主服务工作目录；
- 从 `skill-packages` 直接执行任意 `.py`。

`SKILL.md` 是给模型的指令；Runner 镜像中的 `skill_scripts` 才是可运行、可审计的业务代码。

## 本地执行器

local 环境可实现 `LocalScriptRunner`，使用 `asyncio.create_subprocess_exec` 调用注册表中的固定入口。

要求：

- 使用参数数组，不使用 `shell=True`；
- 传入 JSON 文件或标准输入，不把用户输入拼接成命令行；
- 设置 timeout、最大 stdout / stderr 长度；
- 使用单独工作目录；
- 只允许注册表中定义的脚本；
- local 也记录 execution id 和结果状态。

本地子进程不应用于生产，因为它与 FastAPI 共享容器资源、网络和身份。

## GKE Job 执行器

dev / prod 使用 `GkeJobScriptRunner` 创建固定 Pod 模板的 Kubernetes Job。

```text
Agent Tool
  → 创建 ai_agent_script_execution
  → 创建 Job（携带 execution_id）
  → Runner 读取本次输入
  → 执行固定入口点
  → 提交结构化结果
  → ScriptExecutionService 返回结果给 Agent
```

### 输入与结果

Job 不应将完整 JSON 输入拼接到 `command` 或 `args`。推荐 Job 只携带 `execution_id` 和短期内部凭据：

```text
Runner → GET  /internal/executions/{execution_id}/input
Runner → POST /internal/executions/{execution_id}/result
```

短期凭据仅可读取和回写当前 execution。Runner 不应拥有业务数据库密码，也不应直接拥有 Kubernetes API 管理权限。

结果必须先通过 `result_schema` 校验，再返回给 Agent。stdout / stderr 仅用于审计和排障，须截断、脱敏，不能直接作为用户回复。

### Job 基线

每个 Job 至少配置：

```yaml
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 300
  template:
    spec:
      runtimeClassName: gvisor
      restartPolicy: Never
      activeDeadlineSeconds: 60
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: skill-runner
          image: <pinned-image-digest>
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: "1"
              memory: 512Mi
```

GKE Sandbox 使用 gVisor 为 Pod 增加宿主机隔离层，适用于运行高价值或未知代码。即使脚本可信，也建议将 Runner 与 Agent API 放在独立节点池和 namespace 中。详情见 [GKE Sandbox](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/sandbox-pods?authuser=00&hl=en)。

## 网络、身份与权限

可信脚本不等于可以拥有全部权限。每个 `runner_profile` 应独立配置：

```text
billing-readonly
└── 仅允许访问计费 API

jira-readonly
└── 仅允许访问 Jira API

danaan-write
└── 仅允许访问 Danaan API
└── 创建操作须已有用户 approve 记录
```

要求：

- Runner namespace 默认拒绝所有 egress，再按 profile 放行；
- 禁止 host network、host PID、host IPC、HostPath、特权容器和新增 Linux capability；
- 采用独立 Kubernetes ServiceAccount；
- 调用 Google Cloud 服务时使用最小权限的 Workload Identity，不使用服务账号 JSON key；
- 对写操作要求已有的 Agent HITL approve，再创建 Job；
- 执行 namespace 启用 Kubernetes Pod Security `restricted` 策略。

Workload Identity Federation 是 GKE 工作负载访问 Google Cloud API 的推荐授权模式，见 [官方文档](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/workload-identity?authuser=77)。

## 幂等、状态与审计

建议创建业务表：

```text
ai_agent_script_execution
```

建议字段：

```text
id UUID
conversation_id UUID
agent_run_id UUID
staff_id string
skill_id string
script_id string
status queued | running | completed | failed | cancelled
input_digest string
result JSON nullable
error_message nullable
runner_image_digest string
started_at timestamptz nullable
completed_at timestamptz nullable
created_at timestamptz
updated_at timestamptz
```

对可能有副作用的操作，以 `agent_run_id + tool_call_id` 作为幂等键。网络超时或 Agent 重试时，执行器必须先查询既有 execution，而不是创建第二次外部操作。

## SSE 与 Agent 交互

第一阶段仅支持不超过 60 秒的短任务，Tool 等待 Job 完成后把结构化结果交给同一次 Agent 调用。

前端可收到：

```text
tool_start        正在执行 Jira 查询
execution_status  Runner 已启动
execution_status  正在获取数据
tool_end          查询完成
token             Agent 基于结果的回复
```

超过短任务时限的批处理任务不应保持聊天 SSE 连接。后续可采用：

```text
start_skill_script → execution_id
前端轮询 / 订阅执行状态
用户查看结果或重新触发 Agent 解读
```

自动在后台 Job 完成时恢复 Agent checkpoint 属于后续能力，第一阶段不实现。

## 持久 SandboxBackend（后续能力）

仅在以下需求出现后评估：

```text
Agent 写 Python 文件
  → 执行
  → 读取输出
  → 修改文件
  → 再次执行
```

此时实现 `GkeSandboxBackend` 适配 DeepAgents `SandboxBackendProtocol`：

```text
conversation_id / agent_run_id
  → 一个短期 gVisor Sandbox Pod
  → /workspace 保留至 Sandbox 到期
  → read / write / edit / execute 映射到该 Pod
```

这不是固定业务脚本执行器的替代品。它需要额外处理：会话映射、工作区持久化、Pod 回收、命令限制、输出限制、并发配额和更严格的网络策略。

## 实施顺序

1. 定义脚本注册表、输入 / 输出 Schema 与 `ai_agent_script_execution`；
2. 实现 `ScriptExecutionService` 与 local `LocalScriptRunner`；
3. 为一个只读脚本（推荐 Jira 查询）增加业务语义 Tool 和测试；
4. 实现 GKE Job Runner、状态监听、结果回传与 TTL 清理；
5. 增加 runner profile、NetworkPolicy、Workload Identity 和 gVisor 节点池；
6. 为写操作增加 HITL、幂等键和下游 idempotency key；
7. 仅在动态代码需求明确后，单独设计持久 `GkeSandboxBackend`。

## 非目标

第一阶段明确不支持：

- 用户上传任意 Python 后执行；
- Agent 生成任意 Shell 命令后执行；
- 运行时下载或安装依赖；
- 任意 URL、任意镜像或任意入口点；
- 后台长任务自动恢复聊天 Agent；
- 使用 `FilesystemBackend` 或 `LocalShellBackend` 作为生产脚本沙盒。
