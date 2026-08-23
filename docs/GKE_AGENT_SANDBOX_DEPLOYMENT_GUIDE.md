# GKE Agent Sandbox 部署手册

> 目标：为 DeepAgent 的 Skill 脚本准备 GKE 内隔离、可复用的 Python sandbox。本手册先部署 `dev` 环境；生产复用相同步骤，但使用独立 GKE 集群或 namespace、镜像 digest、身份和网络策略。

> 本文以 Google 官方文档为准。GKE Agent Sandbox 的可用版本和命令仍可能变化；执行前先检查 [启用 Agent Sandbox](https://cloud.google.com/kubernetes-engine/docs/how-to/how-install-agent-sandbox) 的最新要求。

## 1. 架构和职责

```text
local 开发机
  → kubectl port-forward（仅开发）
  → dev GKE 的 Sandbox Router
  → GKE Agent Sandbox Claim
  → gVisor Sandbox Pod

dev/prod DeepAgent API（位于 GKE）
  → ClusterIP Service 的 in-cluster URL
  → Sandbox Router
  → GKE Agent Sandbox Claim
  → gVisor Sandbox Pod
```

GKE Agent Sandbox 负责 Sandbox Controller、Claim、Template 和 WarmPool 的运行时能力；`langchain-kubernetes[agent-sandbox]` 负责把 DeepAgents 的 sandbox backend 调用映射到这套基础设施。更多上下文见 [GKE Agent Sandbox 开发方案](GKE_AGENT_SANDBOX_DEVELOPMENT_PLAN.md)。

## 2. 官方资料

- [启用 GKE Agent Sandbox](https://cloud.google.com/kubernetes-engine/docs/how-to/how-install-agent-sandbox)：集群版本、Autopilot/Standard 启用方式。
- [隔离 AI 代码执行](https://cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox)：Template、WarmPool、Router、Python client 和生产连接建议。
- [使用 gVisor 强化隔离](https://cloud.google.com/kubernetes-engine/docs/how-to/sandbox-pods)：gVisor node pool、RuntimeClass、验证和运行时安全说明。
- [GKE Agent Sandbox 概览](https://cloud.google.com/kubernetes-engine/docs/concepts/machine-learning/agent-sandbox)：资源模型、生命周期和限制。
- [Workload Identity Federation for GKE](https://cloud.google.com/kubernetes-engine/docs/concepts/workload-identity)：Sandbox 确有访问 Google Cloud API 需求时的最小权限身份方案。

## 3. 前置检查

本手册假设：

- 已拥有隔离的 dev GCP project 或 dev GKE cluster；
- 已启用 billing、Artifact Registry API 和 Kubernetes Engine API；
- 使用的 GKE 版本满足官方当前最低要求。撰写时官方要求 `1.35.2-gke.1269000` 或更新版本；执行时必须以官方页面为准；
- 操作人拥有创建/更新集群和 node pool、管理目标 namespace 的权限；
- 已安装并初始化 `gcloud` 与 `kubectl`；
- 已有可推送到 Artifact Registry 的 sandbox 镜像，或先使用官方示例 Python runtime 完成 smoke test。

在命令中只使用任务专属变量：

```bash
export SANDBOX_PROJECT_ID="YOUR_PROJECT_ID"
export SANDBOX_CLUSTER_NAME="deepagent-dev"
export SANDBOX_LOCATION="YOUR_REGION_OR_ZONE"
export SANDBOX_NODE_POOL="agent-sandbox-pool"
export SANDBOX_NAMESPACE="agent-sandbox-dev"
export SANDBOX_MACHINE_TYPE="e2-standard-2"
```

`Autopilot` 使用 region；`Standard` 的示例使用 zone。不要将同一套变量不加确认地复制到生产集群。

## 4. 启用 GKE Agent Sandbox

### 4.1 已有 Autopilot 集群

对已满足版本要求的集群启用功能：

```bash
gcloud beta container clusters update "$SANDBOX_CLUSTER_NAME" \
  --location="$SANDBOX_LOCATION" \
  --enable-agent-sandbox
```

新建 Autopilot 集群时，在创建命令加入 `--enable-agent-sandbox`。完整命令和区域要求见 [官方启用说明](https://cloud.google.com/kubernetes-engine/docs/how-to/how-install-agent-sandbox#enable-agent-sandbox-when-creating-a-new-gke-cluster)。

### 4.2 已有 Standard 集群

Standard 集群必须有独立的 gVisor node pool；不要把 Agent Sandbox 作为默认 node pool 的常规工作负载运行时。

```bash
gcloud container node-pools create "$SANDBOX_NODE_POOL" \
  --cluster="$SANDBOX_CLUSTER_NAME" \
  --location="$SANDBOX_LOCATION" \
  --machine-type="$SANDBOX_MACHINE_TYPE" \
  --image-type=cos_containerd \
  --sandbox=type=gvisor

gcloud beta container clusters update "$SANDBOX_CLUSTER_NAME" \
  --location="$SANDBOX_LOCATION" \
  --enable-agent-sandbox
```

这是官方 Standard cluster 的启用顺序；不要忽略 `cos_containerd` 和 `--sandbox=type=gvisor`。[官方启用说明](https://cloud.google.com/kubernetes-engine/docs/how-to/how-install-agent-sandbox#enable-agent-sandbox-when-updating-an-existing-gke-cluster)

获取集群凭据并确认 gVisor RuntimeClass：

```bash
gcloud container clusters get-credentials "$SANDBOX_CLUSTER_NAME" \
  --location="$SANDBOX_LOCATION" \
  --project="$SANDBOX_PROJECT_ID"

kubectl get runtimeclass gvisor
kubectl get nodes -l sandbox.gke.io/runtime=gvisor
```

如果 RuntimeClass 或节点标签缺失，停止后续操作，先按 [GKE Sandbox 排障与配置](https://cloud.google.com/kubernetes-engine/docs/how-to/sandbox-pods) 修复。

## 5. 创建隔离 namespace 和基础护栏

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: agent-sandbox-dev
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: sandbox-quota
  namespace: agent-sandbox-dev
spec:
  hard:
    pods: "20"
    requests.cpu: "4"
    requests.memory: 8Gi
    limits.cpu: "8"
    limits.memory: 16Gi
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all-egress
  namespace: agent-sandbox-dev
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress: []
```

将上述内容保存为受 IaC 管理的 manifest 后执行：

```bash
kubectl apply -f sandbox-namespace-guardrails.yaml
```

默认拒绝出口后，必须为 DNS、Sandbox Router 以及每个有明确业务需要的服务，单独新增最小 egress allow policy。不要为“排错方便”恢复全网访问。

## 6. 创建 SandboxTemplate 与 WarmPool

先用官方示例镜像验证 GKE 能力；生产改为你自己的、使用不可变 digest 的 Skill sandbox 镜像。官方 Template 与 WarmPool 示例见 [隔离 AI 代码执行](https://cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox#deploy-a-sandboxed-environment)。

```yaml
apiVersion: extensions.agents.x-k8s.io/v1alpha1
kind: SandboxTemplate
metadata:
  name: deepagent-python
  namespace: agent-sandbox-dev
spec:
  podTemplate:
    metadata:
      labels:
        app.kubernetes.io/name: deepagent-sandbox
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
        - name: python-runtime
          # Smoke test only. Production must use Artifact Registry image digest.
          image: registry.k8s.io/agent-sandbox/python-runtime-sandbox:v0.1.0
          ports:
            - containerPort: 8888
          readinessProbe:
            httpGet:
              path: /
              port: 8888
            periodSeconds: 1
          resources:
            requests:
              cpu: 250m
              memory: 512Mi
            limits:
              cpu: 500m
              memory: 1Gi
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
      restartPolicy: OnFailure
---
apiVersion: extensions.agents.x-k8s.io/v1alpha1
kind: SandboxWarmPool
metadata:
  name: deepagent-python-pool
  namespace: agent-sandbox-dev
spec:
  replicas: 2
  sandboxTemplateRef:
    name: deepagent-python
```

```bash
kubectl apply -f sandbox-template-and-pool.yaml
kubectl get sandboxtemplates,sandboxwarmpools -n "$SANDBOX_NAMESPACE"
kubectl get pods -n "$SANDBOX_NAMESPACE" -w
```

CRD `apiVersion`、WarmPool 字段和官方 runtime 镜像会随 Agent Sandbox 版本演进；部署时以当前官方示例为准，不要混用不同版本的 CRD manifest。

## 7. 部署 Sandbox Router

Sandbox Router 是 client 与 sandbox Pod 的稳定通信入口。使用 Google 提供的 Router manifest 作为起点，部署为 ClusterIP；不要将 Router 公开到互联网。

```text
官方部署示例：
https://cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox#deploy-the-sandbox-router
```

生产要求：

- Router Deployment、Service 与 sandbox 放在受控 namespace；
- Router 镜像必须固定到经过审查的版本或 digest，禁止使用 `latest`/`latest-main`；
- 配置 readiness/liveness probes、资源 requests/limits 与至少两个副本（按可用区和负载决定）；
- Router Service 仅使用 ClusterIP；
- Agent API 到 Router 的 NetworkPolicy 仅允许必要端口；
- 不使用官方开发示例中的 `kubectl port-forward` 作为生产连接方式。

部署后确认：

```bash
kubectl get deployment,service -n "$SANDBOX_NAMESPACE"
kubectl get endpoints -n "$SANDBOX_NAMESPACE" sandbox-router-svc
```

## 8. 连接测试

### 8.1 local：开发 tunnel

local 仅可对 `agent-sandbox-dev` 使用 tunnel。Python client 会建立到 Router 的 port-forward；这是开发便利措施，不是生产连接方案。

```bash
python -m venv .venv
. .venv/bin/activate
pip install k8s-agent-sandbox
```

```python
from k8s_agent_sandbox import SandboxClient
from k8s_agent_sandbox.models import SandboxLocalTunnelConnectionConfig

client = SandboxClient(connection_config=SandboxLocalTunnelConnectionConfig())
sandbox = client.create_sandbox(
    template="deepagent-python",
    namespace="agent-sandbox-dev",
)
try:
    result = sandbox.commands.run("python --version")
    print(result.stdout)
    print(result.stderr)
    print(result.exit_code)
finally:
    client.delete_sandbox(sandbox.claim_name, namespace="agent-sandbox-dev")
```

该 API 形态和开发 tunnel 行为见 [Google 官方 Python client 测试说明](https://cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox#test-the-sandbox)。

### 8.2 dev/prod：in-cluster direct

DeepAgent API 部署在相同集群后，配置 `langchain-kubernetes[agent-sandbox]` 使用 `connection_mode="direct"`，`api_url` 指向 Router 的 ClusterIP DNS。不要运行 `kubectl port-forward`，不要把用户 kubeconfig 放进 API Pod。

应用 ServiceAccount 只授予创建、查看和删除目标 namespace Sandbox 资源所需的最小 RBAC。Sandbox Pod 自身保持 `automountServiceAccountToken: false`；仅当某个 Skill 确需 Google Cloud API 时，额外配置专属 Kubernetes ServiceAccount 与最小 Workload Identity 权限。

## 9. 验收清单

- [ ] 集群版本与 Agent Sandbox feature 已核验；
- [ ] Standard 集群有独立 gVisor node pool，Sandbox Pod 的 `runtimeClassName` 是 `gvisor`；
- [ ] `agent-sandbox-dev` 和 `agent-sandbox-prod` 相互独立；
- [ ] Template、WarmPool、Router 都处于 Ready；
- [ ] local 通过 tunnel 能创建、执行和销毁测试 sandbox；
- [ ] GKE 内的 DeepAgent API 通过 ClusterIP direct 连接 Router；
- [ ] sandbox 无法读取 Kubernetes token、metadata、主服务文件或未经允许的网络目标；
- [ ] Sandbox 镜像使用 Artifact Registry 的 digest，包含 Skill 脚本和锁定依赖；
- [ ] TTL、资源限制、日志和告警已验证；
- [ ] 高风险写操作未因启用 `execute` 绕过现有 HITL/幂等机制。

## 10. 交付给应用接入前的输出

基础设施负责人完成本手册后，应提供：

```text
cluster / location
namespace
SandboxTemplate 名称
SandboxWarmPool 名称
Router 的 in-cluster URL 与端口
Agent API ServiceAccount/RBAC 名称
Sandbox 镜像 digest
local 连接所需的 dev kubecontext
已批准的 egress 目标列表
```

应用侧再按 [GKE Agent Sandbox 开发方案](GKE_AGENT_SANDBOX_DEVELOPMENT_PLAN.md) 的 Milestone 2 开始独立兼容性验证。
