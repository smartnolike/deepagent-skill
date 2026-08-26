# DeepAgent × GKE Agent Sandbox 开发方案

> 状态：实施中。本文覆盖“安装的 Skill 可在隔离工作区执行其脚本”的场景；固定、强业务语义脚本的受控 Job 方案见 [SKILL_SCRIPT_SANDBOX.md](SKILL_SCRIPT_SANDBOX.md)。

## 1. 目标

为 DeepAgent 提供接近 Copilot 的 Skill 使用体验：Skill 包同时包含 `SKILL.md` 和 Python 脚本，Agent 在独立的 GKE 沙盒中读取、运行并在同一会话内复用脚本产生的文件。

```text
Skill package
├── SKILL.md                     # Agent 指令，仍由应用的 FilesystemBackend 读取
└── scripts/                     # 可执行代码，随 Sandbox 镜像发布
    └── query.py

run_skill_script（用户确认后）
  → 应用内一次性 GKE Script Runner
  → GKE Agent Sandbox
  → gVisor Sandbox Pod
  → /workspace/skills/<skill-id>/scripts/query.py
```

脚本不在 Mac、FastAPI Pod 或 Kubernetes 宿主机运行。

## 2. 方案选择和边界

使用以下组件：

| 组件 | 职责 |
| --- | --- |
| GKE Agent Sandbox add-on | Google 托管的 Controller、CRD、Template、Claim、WarmPool 能力 |
| GKE Sandbox / gVisor | Sandbox Pod 的运行时隔离 |
| `k8s-agent-sandbox` | 与 GKE Agent Sandbox 通讯的 Python SDK；同集群可直接连接 Sandbox Pod |
| `FilesystemBackend` | API 镜像中只读浏览 `SKILL.md` 与已审阅脚本；`ls` 不访问 GKE |
| `ScriptCatalog` | 启动时扫描已启用 Skill 的 `scripts/*.py`，形成内存白名单 |
| 应用内 GKE Script Runner | 仅执行确认后的固定脚本，下载 `.xlsx` 产物后立即终止 Claim |

项目固定官方 `k8s-agent-sandbox==0.4.6`，与 GKE 托管 Agent Sandbox 当前提供的 `v1alpha1` CRD 对齐，并维护很薄的一次性 Script Runner。`0.5.x` SDK 请求 `v1beta1`，不能用于仅提供 `v1alpha1` 的 GKE add-on。此前评估的第三方 `langchain-kubernetes` 与该 SDK 的 `SandboxClient` API 不兼容，因此不作为生产依赖。

此方案会让 Agent 获得沙盒内的 `execute`、文件读写和编辑能力；它不是“只允许执行一个固定 Python 文件”的模型。固定、高风险的业务脚本仍应使用语义 Tool、HITL 与受控 GKE Job，见 [SKILL_SCRIPT_SANDBOX.md](SKILL_SCRIPT_SANDBOX.md)。

## 3. 默认安全策略

- local 和 dev 只连接 `agent-sandbox-dev`，绝不访问生产 sandbox；
- prod 只连接 `agent-sandbox-prod`；
- 一个 conversation 对应一个可复用、短生命周期 sandbox；
- 默认拒绝所有网络出口；按明确的 Skill profile 单独放行；
- Sandbox Pod 无 Kubernetes token、无云管理员凭据、无 hostPath、无特权模式、非 root 运行；
- 不挂载 FastAPI 源码、数据库凭据、本机目录、Docker socket、`kubeconfig` 或服务账号 JSON key；
- Python 依赖只在镜像构建期安装；禁止运行时 `pip install`、下载代码或用户指定镜像；
- 有副作用的业务操作继续通过业务 Tool 和现有 HITL confirmation，sandbox 不代替业务授权。

第三方 Skill 必须经过代码审查、依赖锁定、镜像扫描和签名后才可进入受信任镜像。gVisor 降低进程逃逸风险，但不能阻止已允许网络上的数据外传或提示注入诱导的沙盒内命令。

## 4. 环境和连接方式

```text
local FastAPI / DeepAgent
  → kubeconfig + kubectl port-forward（仅开发）
  → dev GKE Sandbox Router

dev FastAPI（在 dev GKE）
  → ClusterIP / in-cluster direct URL
  → dev GKE Sandbox Router

prod FastAPI（在 prod GKE）
  → ClusterIP / in-cluster direct URL + 最小 Kubernetes RBAC / Workload Identity
  → prod GKE Sandbox Router
```

| 环境 | Sandbox namespace | `connection_mode` | 生命周期建议 |
| --- | --- | --- | --- |
| local | `agent-sandbox-dev` | `direct` + 手动 port-forward | idle 15 分钟，绝对 2 小时 |
| dev | `agent-sandbox-dev` | `direct` | idle 15 分钟，绝对 2 小时 |
| prod | `agent-sandbox-prod` | `direct` | idle 30 分钟，绝对 4 小时 |

local 使用开发者 kubeconfig 创建 Claim，并手动 `kubectl port-forward` 到 Router 后使用 direct URL；这是开发便利措施。生产禁止 port-forward，改用集群内 Service DNS 和专用 Kubernetes ServiceAccount。旧 `v1alpha1` SDK 的内置 tunnel 固定要求 `svc/sandbox-router-svc:8080`，不适用于自定义 Router 名称或端口。

## 5. 基础设施实施

具体部署命令、Template/Router 验证和环境交付清单见 [GKE Agent Sandbox 部署手册](GKE_AGENT_SANDBOX_DEPLOYMENT_GUIDE.md)。本节说明架构约束，部署时以该手册和 Google 官方文档为准。

在 GKE 版本暂不满足要求时，可先按 [本地 kind + Agent Sandbox PoC 手册](LOCAL_KIND_AGENT_SANDBOX_POC.md) 验证 Controller、Router、自建 runtime 镜像和 Skill 脚本执行链路。

按 dev、再 prod 的顺序执行：

1. 启用 GKE Agent Sandbox，建立 gVisor 专用节点池；
2. 验证 add-on 已提供 Controller 和 CRD；不要在 GKE 上额外应用开源 Controller/CRD release manifest；
3. 部署 Sandbox Router：local 手动 port-forward 与集群内 direct Router URL 都使用它；默认 GKE 网络策略只允许 Router 进入 Sandbox Pod；
4. 创建 `agent-sandbox-dev` 或 `agent-sandbox-prod` namespace；
5. 应用 Pod Security `restricted`、ResourceQuota、LimitRange 和默认拒绝 egress 的 NetworkPolicy；
6. 配置 Agent API ServiceAccount，使其仅能管理本 namespace 的 sandbox 资源；
7. 为需要 Google Cloud API 的特定 Skill 使用最小权限 Workload Identity，不使用 JSON key；
8. 创建 `SandboxTemplate` 和 `SandboxWarmPool`。dev 起始维持 1--2 个 warm sandbox，prod 根据压测扩容。

模板必须固定镜像、资源和安全上下文：

```yaml
apiVersion: extensions.agents.x-k8s.io/v1alpha1
kind: SandboxTemplate
metadata:
  name: deepagent-python
  namespace: agent-sandbox-dev
spec:
  podTemplate:
    spec:
      runtimeClassName: gvisor
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      nodeSelector:
        sandbox.gke.io/runtime: gvisor
      tolerations:
        - key: sandbox.gke.io/runtime
          value: gvisor
          effect: NoSchedule
      containers:
        - name: sandbox
          image: asia-docker.pkg.dev/PROJECT/agent/skill-sandbox@sha256:IMAGE_DIGEST
          resources:
            requests: {cpu: 250m, memory: 512Mi}
            limits: {cpu: "1", memory: 1Gi}
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
```

## 6. Skill 和镜像供应链

`SKILL.md` 继续由应用的 `FilesystemBackend` 从 `skill-packages/` 读取。Python 脚本必须同时进入 sandbox 镜像；不会自动从应用文件系统同步到远程 sandbox。

推荐目录：

```text
skill-packages/
  example-skill/
    SKILL.md
    scripts/
      query.py
    requirements-sandbox.in
```

发布流程：

1. 合并并锁定所有 sandbox Python dependencies；
2. 构建 `skill-sandbox` 镜像，复制 scripts 到 `/workspace/skills/<skill-id>/scripts/`；
3. 在构建期安装 lock 文件中的依赖；
4. 生成 SBOM、扫描镜像并推送 Artifact Registry；
5. `SandboxTemplate` 使用不可变 image digest；
6. 记录 image digest 与 Skill 版本的映射。

```dockerfile
FROM registry.k8s.io/agent-sandbox/python-runtime-sandbox:v0.1.0

COPY requirements-sandbox.lock /tmp/requirements-sandbox.lock
RUN pip install --no-cache-dir -r /tmp/requirements-sandbox.lock

COPY skill-packages /workspace/skills
```

新增 Skill 依赖时必须构建新镜像并更新 Template，不在 sandbox 启动后安装。

## 7. 应用接入

### 7.1 配置

增加 `SandboxSettings`，按 `config/local.yaml`、`config/dev.yaml`、`config/prod.yaml` 注入：

```text
enabled
provider = kubernetes
namespace
template_name
connection_mode = direct（GKE 自定义 Router 时）或 tunnel（仅默认 svc/8080）
api_url                         # direct 模式必填
ttl_seconds
ttl_idle_seconds
```

增加 Python 依赖：

```text
k8s-agent-sandbox==0.4.6
```

### 7.2 DeepAgent Harness

`conversation_id` 仅用于归属下载产物；SandboxClaim 不跨会话或跨轮复用：

```text
conversation_id
  → graph state / checkpointer 中的 sandbox_id
  → 同一会话重连同一 sandbox
```

现有 `create_agent_service()` 保留 MCP Tools、自定义 Tools、Skills、系统提示、Postgres checkpointer、HITL confirmation、语言中间件和 SSE；应用内 adapter 作为 `create_deep_agent(backend=...)` 的 backend factory 接入。

仅在 `sandbox.enabled=true` 时，移除 Harness 对 `execute`、`write_file`、`edit_file` 的排除。`delete` 默认继续排除，除非产品明确允许 Agent 删除 sandbox 文件。

所有 Skill 指令和 system prompt 需补充：

```text
仅执行 /workspace/skills/<enabled-skill-id>/scripts/ 下的已发布脚本。
不得访问其他 Skill 私有目录、系统敏感路径或环境中的凭据。
不得下载代码、安装依赖或修改系统包。
```

这些提示是额外约束，不是安全边界；最终边界由镜像、NetworkPolicy、身份和 gVisor 提供。

## 8. 生命周期、SSE 和审计

第一版沿用当前 SSE：

```text
tool_start → sandbox command execution → tool_end → token → done
```

后续可增加 `sandbox_starting`、`sandbox_ready`、`sandbox_expired` 事件。

记录并监控以下信息；不记录敏感输入或完整未脱敏命令输出：

```text
conversation_id, sandbox_id, skill_id
SandboxTemplate, image digest
创建/复用/销毁时间、TTL 原因
命令摘要、exit code、耗时、截断标记
CPU/内存限制、失败类型、网络拒绝事件
```

TTL 后删除 sandbox；同一会话后续请求创建新 sandbox。新 sandbox 会恢复镜像内的脚本和依赖，不恢复旧 sandbox 的临时文件。

## 9. 里程碑和验收

### Milestone 0：方案冻结

- 确认可获得通用 sandbox 执行能力的 Skill 范围；
- 确认默认无 egress、无运行时依赖安装；
- 确认高风险写操作继续走语义 Tool/HITL。

### Milestone 1：dev GKE 基础设施

- 验证 add-on 管理的 Controller/CRD，并完成 Router、gVisor Template、WarmPool、RBAC 和 NetworkPolicy；
- 验收：开发机创建 sandbox、`python --version` 成功、RuntimeClass 为 `gvisor`，且不能访问公网和 Kubernetes API。

### Milestone 2：独立兼容性 Spike

- 使用官方 SDK 与应用内 adapter 验证创建、复用、执行、文件读写、超时、输出截断、TTL、删除和 WarmPool；
- 验证 local 手动 port-forward + `direct` 和 in-cluster `direct`；
- 此阶段不修改现有 Agent 主流程。

### Milestone 3：镜像与 Skill 供应链

- 发布第一份包含测试 Skill 脚本的不可变镜像；
- 验收：新 sandbox 不联网安装依赖也可执行脚本。

### Milestone 4：Harness 接入

- 接入受控 `run_skill_script`、`ScriptCatalog` 与私有对象存储产物下载；
- 通过 feature flag 开放 sandbox 工具；
- 验收：同会话跨轮复用文件，不同会话不互通，原有 MCP/HITL/SSE 测试继续通过。

### Milestone 5：安全、压测和灰度

- 测试 namespace 越权、metadata/Kubernetes API 访问、网络外传、资源耗尽和并发；
- 对内部用户和白名单 Skill 灰度；
- feature flag 关闭后回退为当前只读 `FilesystemBackend` 行为。

## 10. 非目标

第一阶段不支持：

- local 直接运行带业务凭据的 shell sandbox；
- local 访问 prod GKE sandbox；
- sandbox 挂载宿主机目录、Docker socket、主服务代码或 kubeconfig；
- 用户上传任意依赖并在运行时安装；
- 将模型指定的镜像、入口点或网络目的地直接传给 Kubernetes；
- 以 sandbox 执行替代高风险写操作的业务 Tool、审批或幂等保护。

## 11. 参考

- [DeepAgents Sandboxes](https://docs.langchain.com/oss/python/deepagents/sandboxes)
- [LangChain Sandbox Integrations](https://docs.langchain.com/oss/python/integrations/sandboxes)
- [GKE Agent Sandbox](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox)
- [GKE Sandbox with gVisor](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/sandbox-pods)
- [官方 k8s-agent-sandbox Python SDK](https://pypi.org/project/k8s-agent-sandbox/)
