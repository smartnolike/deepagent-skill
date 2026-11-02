# Google Agent Sandbox 使用与接入指南

> 依据官方文档（2026-11 校对）：<https://agent-sandbox.sigs.k8s.io>、<https://github.com/kubernetes-sigs/agent-sandbox>

## 0. 先对齐概念

"Google Agent Sandbox" 现在通常指 **kubernetes-sigs/agent-sandbox**（SIG Apps 下的开源项目，Google 主导，
GKE 官方文档有专门章节）。它不是一个 SaaS，而是**跑在你自己的 Kubernetes 集群里**的沙箱编排层。

| 方案 | 形态 | 谁托管 | 适用 |
|---|---|---|---|
| **agent-sandbox**（本文） | K8s CRD + Controller + Router + SDK | 你的集群（GKE/KinD/AKS/EKS） | 要自控隔离、自建 agent 运行时 |
| Vertex AI Agent Engine Sandbox | 托管 API（Code Interpreter） | Google | 不想运维 K8s，只跑 Python 代码 |
| Cloud Run code execution | 沙箱化执行环境 | Google | 已在 Cloud Run 上 |
| Gemini Enterprise Managed Agents sandbox | 托管 agent 沙箱 | Google | 用 Google 的 agent 平台 |

## 1. 架构：一个 Controller + 四类资源 + 一个 Router

```
用户 ──> SandboxClaim ──> (从 SandboxWarmPool 领养) ──> Sandbox ──> Pod ──> RuntimeClass(gVisor/Kata)
                                    │                      │
                             SandboxTemplate         稳定 hostname / PVC / 生命周期
客户端 SDK ──> sandbox-router ──> 按 X-Sandbox-ID 转发到 Pod
```

- **Sandbox**（`agents.x-k8s.io/v1beta1`，core）：单个有状态 Pod，固定身份、可挂 PVC、可 pause/resume、
  支持 `shutdownTime` 定时回收。
- **SandboxTemplate**（`extensions.agents.x-k8s.io/v1beta1`）：可复用的 Pod 模板。
- **SandboxWarmPool**：预热池，维持 N 个已就绪 Sandbox。
- **SandboxClaim**：从池子里"领养"一个，秒级返回（实测 &lt;2s；冷启动 10–30s）。
- **sandbox-router**：无状态 HTTP/gRPC 反向代理，一个静态入口服务几千个沙箱，避免给每个 Pod 建 Service/路由。
- **Runtime** 两种：
  - legacy `python-runtime`：HTTP `:8888`，简单 exec/files API（SDK 默认）。
  - `sandboxd`：gRPC `:9090`（ProcessService 流式执行）+ REST `:8080`（文件系统），支持流式输出、PTY、信号、文件监听。

隔离由 `RuntimeClass` 决定：默认共享内核；生产建议 **gVisor**（用户态内核）或 **Kata Containers**（轻量 VM）。

## 2. 安装（KinD 本地 / GKE）

前置：`kubectl` 1.28+、`docker`、`kind`（或 `gcloud`）。

```bash
# 1) 集群
kind create cluster --wait 90s --name agent-sandbox-test
# 或 GKE：
# gcloud container clusters create-auto agent-sandbox-test --region=us-central1
# gcloud container clusters get-credentials agent-sandbox-test --location us-central1

# 2) Controller + CRDs（core + extensions 一把装完）
kubectl apply -f https://github.com/kubernetes-sigs/agent-sandbox/releases/latest/download/sandbox-with-extensions.yaml
kubectl -n agent-sandbox-system rollout status deployment/agent-sandbox-controller --timeout=90s

# 3) Router（本地测试可关鉴权；生产务必保持鉴权）
VERSION=$(curl -s https://api.github.com/repos/kubernetes-sigs/agent-sandbox/releases/latest | jq -r .tag_name)
curl -sSL https://raw.githubusercontent.com/kubernetes-sigs/agent-sandbox/refs/tags/${VERSION}/clients/python/agentic-sandbox-client/sandbox-router/sandbox_router.yaml \
  | sed 's|${ROUTER_IMAGE}|us-central1-docker.pkg.dev/k8s-staging-images/agent-sandbox/sandbox-router:latest-main|g' \
  | sed '/ALLOW_UNAUTHENTICATED_ROUTER/{n;s/value: "false"/value: "true"/}' \
  | kubectl -n agent-sandbox-system apply -f -
kubectl -n agent-sandbox-system rollout status deployment/sandbox-router-deployment --timeout=90s

# 4) 模板 + 预热池（repo 里有现成 yaml）
git clone https://github.com/kubernetes-sigs/agent-sandbox.git && cd agent-sandbox
export SANDBOX_NAMESPACE=default SANDBOX_TEMPLATE_NAME=python-sandbox-template SANDBOX_WARMPOOL_NAME=python-sandbox-pool
envsubst < clients/python/agentic-sandbox-client/python-sandbox-template.yaml | kubectl apply -f -
envsubst < clients/python/agentic-sandbox-client/python-sandbox-warmpool.yaml | sed 's/replicas: 0/replicas: 1/' | kubectl apply -f -

# 5) 验证
kubectl get crd sandboxes.agents.x-k8s.io
kubectl get pods -l agents.x-k8s.io/warm-pool-sandbox
kubectl port-forward svc/sandbox-router-svc 8080:8080 -n agent-sandbox-system & curl -s localhost:8080/healthz
```

## 3. 两种用法

### 3.1 K8s 原生（YAML）

最小 Sandbox：

```yaml
apiVersion: agents.x-k8s.io/v1beta1
kind: Sandbox
metadata:
  name: my-sandbox
spec:
  podTemplate:
    spec:
      containers:
        - name: my-container
          image: <IMAGE>
```

从预热池领取：

```bash
kubectl apply -f - <<'EOF'
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxClaim
metadata:
  name: quickstart-test
spec:
  warmPoolRef:
    name: python-warmpool
EOF
kubectl wait --for=condition=Ready sandboxclaim/quickstart-test --timeout=60s
kubectl get sandboxclaim quickstart-test -o jsonpath='{.status.sandbox.name}'   # 真正的 sandbox/pod 名
```

### 3.2 SDK（推荐）

```bash
pip install k8s-agent-sandbox              # 同步
pip install "k8s-agent-sandbox[async]"     # 异步
pip install "k8s-agent-sandbox[grpc]"      # sandboxd 流式执行
```

## 4. 怎么连接（核心）

`SandboxClient` 有四种连接模式，**默认 Tunnel**：

| 模式 | 配置类 | 链路 | 适用 |
|---|---|---|---|
| Tunnel（默认） | `SandboxLocalTunnelConnectionConfig` | localhost → `kubectl port-forward` → router → Pod | 本地开发/CI（KinD、Minikube） |
| Gateway | `SandboxGatewayConnectionConfig` | LB/Gateway → router → Pod | 生产，有公网入口 |
| Direct URL | `SandboxDirectConnectionConfig` | 直连你给的 `api_url` | 自定义域名、内网 Service DNS、带 mTLS |
| In-Cluster | `SandboxInClusterConnectionConfig` | 直接连 Pod IP / headless DNS，绕过 router | 客户端就在集群里 |

```python
from k8s_agent_sandbox import SandboxClient
from k8s_agent_sandbox.models import (
    SandboxLocalTunnelConnectionConfig, SandboxGatewayConnectionConfig,
    SandboxDirectConnectionConfig, SandboxInClusterConnectionConfig,
)

client = SandboxClient()  # == Tunnel
# client = SandboxClient(connection_config=SandboxLocalTunnelConnectionConfig(router_namespace="agent-sandbox-system"))
# client = SandboxClient(connection_config=SandboxGatewayConnectionConfig(gateway_name="external-http-gateway"))
# client = SandboxClient(connection_config=SandboxDirectConnectionConfig(api_url="http://sandbox-router-svc.agent-sandbox-system.svc.cluster.local:8080"))
# client = SandboxClient(connection_config=SandboxInClusterConnectionConfig())
```

要点：
- `router_namespace`（router 在哪，默认 `agent-sandbox-system`）与 `create_sandbox(namespace=...)`（沙箱调度到哪）是**两个不同参数**，配错会报 `services sandbox-router-svc not found`。
- runtime 端口不是 8888 时用 `server_port=` 覆盖。
- 异步客户端不支持 Tunnel 模式（依赖同步的 kubectl 子进程）。
- `create_sandbox()` 是 **watch 驱动**，不做轮询；`sandbox_ready_timeout` 默认 180s 只是上限。
- 切集群：传自己的 `api_client`（`kubernetes.config.load_kube_config(config_file=..., context=...)`）。

### Router 契约（想自己写客户端时）

在 `X-Sandbox-ID`、`X-Sandbox-Namespace`、`X-Sandbox-Port` 头里带上目标，router 转发到
`<id>.<namespace>.svc.cluster.local:<port>`；`X-Sandbox-*` 为保留头，`/healthz` 做健康检查。
Go 版 router 是官方推荐实现（TLS、metrics、tracing、重试、优雅退出）。

### 手工验证（不写代码）

```bash
kubectl port-forward -n default pod/<sandbox-name> 8888:8888
curl -s localhost:8888/...            # legacy runtime 的 HTTP 执行/文件 API
# sandboxd 运行时：
curl -s localhost:8080/v1/health
curl -s -X PUT --data-binary @main.py localhost:8080/v1/files/main.py
grpcurl -plaintext -d '{"config":{"command":["echo","hello"]}}' localhost:9090 process.v1.ProcessService/Execute
```

## 5. 最小可跑脚本

```python
from k8s_agent_sandbox import SandboxClient

with SandboxClient() as client:                      # 退出时自动清理
    sb = client.create_sandbox(warmpool="python-sandbox-pool", namespace="default")
    print(sb.commands.run("echo 'Hello from Agent Sandbox!'").stdout)

    sb.files.write("hello.py", 'print("hi from sandbox")\n')
    print(sb.commands.run("python3 hello.py").stdout)

    sb.files.write("data.tar", open("local.tar", "rb"))   # 文件对象 = 流式上传
    with open("out.tar", "wb") as f:
        sb.files.read_to("data.tar", f, max_bytes=64 << 20)
```

常用参数：`env={"FOO":"bar"}`（会强制冷启动）、`labels` / `pod_labels`（Downward API 可读）、
`volume_claim_templates=[...]`、`claim_name` + `adopt_existing=True`（幂等重试）、
`shutdown_after_seconds`（自动回收）、`file_config=SandboxFileConfig(max_download_size=...)`。

### 接进 ADK agent

```python
from google.adk.agents.llm_agent import Agent
from k8s_agent_sandbox import SandboxClient

def execute_python(code: str) -> str:
    with SandboxClient() as c:
        sb = c.create_sandbox(warmpool="python-sandbox-pool", namespace="default")
        sb.files.write("run.py", code)
        return sb.commands.run("python3 run.py").stdout

root_agent = Agent(
    model="gemini-3.7-flash", name="coding_agent",
    instruction="写 Python 并用 execute_python 在沙箱里执行。",
    tools=[execute_python],
)
```

## 6. 生产 checklist

1. **入口鉴权**：Gateway + `HTTPRoute` + TLS；不要留 `ALLOW_UNAUTHENTICATED_ROUTER=true`；
   需要时分米 mTLS（`client_cert`/`ca_cert`）或 `extra_headers={"Authorization": "Bearer ..."}`。
2. **网络**：NetworkPolicy 限制沙箱出网（可配 Cilium FQDN 白名单）；客户端到 sandboxd 的 8080/9090 也要放行。
3. **隔离**：`runtimeClassName: gvisor` 或 `kata`；Kata/gVisor 下 pod port-forward 直连不可用 → 用 router 或 in-cluster。
4. **容量**：warm pool 副本数按并发峰值定，配 HPA/KEDA（scale-to-zero）、PDB、Kueue 配额、APF 隔离。
5. **成本**：`shutdownTime` 兜底回收；Sandbox 不是 Deployment，别指望 ReplicaSet 自愈。
6. **可观测**：controller metrics、router metrics、GCP Trace（`k8s-agent-sandbox[tracing]`）。
7. **持久化**：`volumeClaimTemplates` 挂 PVC；快照/休眠恢复参考 Snapshot 文档。

## 7. 常见坑

- `create_sandbox` 卡住：先看 `SandboxClaim` 的 `Ready` condition，别轮询。
- `env` / `volume_claim_templates` 会绕过预热（冷启动 10–30s）。
- 忘了 `terminate()`：用 `with SandboxClient()` 或 `shutdown_after_seconds`。
- 本地 SDK 找不到集群：`KUBECONFIG` 或 `~/.kube/config` 的 current-context；跨集群要显式传 `api_client`。
- 自建 runtime 要同时实现 gRPC `process.v1` 和 REST `/v1/files`、`/v1/health`、`/v1/metadata`。

## 8. 参考

- 官网 / 总览：<https://agent-sandbox.sigs.k8s.io/docs/getting_started/overview/>
- 安装：<https://agent-sandbox.sigs.k8s.io/docs/getting_started/install_prerequisites/>
- Python SDK Quickstart：<https://agent-sandbox.sigs.k8s.io/docs/getting_started/python-sdk-quickstart/>
- Python Client README（连接模式细节）：<https://github.com/kubernetes-sigs/agent-sandbox/blob/main/clients/python/agentic-sandbox-client/README.md>
- Runtime API（sandboxd）：<https://agent-sandbox.sigs.k8s.io/docs/api/runtime/>
- ADK 集成：<https://agent-sandbox.sigs.k8s.io/docs/use-cases/examples/code-interpreter-agent-on-adk/>
- 安全快速上手：<https://agent-sandbox.sigs.k8s.io/docs/use-cases/examples/quickstart/>
- GKE 官方指南：<https://cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox>
- Router：<https://github.com/kubernetes-sigs/agent-sandbox/tree/main/sandbox-router>
