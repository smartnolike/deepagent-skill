# 本地 kind + Agent Sandbox PoC 手册

> 目的：在 GKE Agent Sandbox 尚不可用前，于本机 Docker 中运行 kind，验证 Agent Sandbox Controller、CRD、Router、Python runtime 镜像和 Skill 脚本执行的完整链路。

> 这是一份开发 PoC 手册，不是生产部署手册。生产路径见 [GKE Agent Sandbox 部署手册](GKE_AGENT_SANDBOX_DEPLOYMENT_GUIDE.md)。

## 1. 先理解四个独立组件

```text
本机 Docker Desktop
└─ kind Kubernetes 集群
   ├─ Agent Sandbox Controller + CRD + extensions   # 集群级安装
   ├─ Sandbox Router                                # 集群内 Deployment/Service
   └─ Sandbox Pod
      └─ Custom Python Runtime Image                # 每个 sandbox 使用的容器镜像
         ├─ /execute HTTP server
         ├─ Python 和依赖
         └─ Skill scripts
```

Controller、CRD 和 Router **不能安装进 Python 镜像**。普通 `python:3.12-slim` 也不能直接作为 runtime，因为 Router 需要调用 runtime 暴露的命令执行 HTTP API。

官方 Python Runtime Sandbox 是一个 FastAPI server，提供 `/execute`：输入 command，返回 `stdout`、`stderr` 和 `exit_code`。源码位于 [Agent Sandbox Python runtime 示例](https://github.com/kubernetes-sigs/agent-sandbox/tree/main/examples/python-runtime-sandbox)。

## 2. 路线选择

本 PoC 使用“自建镜像，但继承官方 runtime”的方式：

```text
官方 runtime 示例源码
  → 构建 deepagent/python-runtime:local
  → 继承该镜像，加入本项目 Skill scripts 和依赖
  → 构建 deepagent/skill-sandbox:local
  → kind load docker-image
```

这意味着你不依赖官方预构建镜像，但保留 `/execute` 协议兼容性。不要用普通 Python 镜像替换 runtime，除非你自行实现并测试相同的执行 API。

## 3. 前置条件

- Docker Desktop 正在运行；
- `kind` >= 0.20；
- `kubectl` >= 1.28；
- Python 3.12；
- Git；
- 至少 8 GB Docker 可用内存；
- 不在生产 kubecontext 上执行以下命令。

检查：

```bash
docker version
kind version
kubectl version --client
kubectl config current-context
```

## 4. 下载并固定 Agent Sandbox 源码版本

在项目外创建一个临时工作目录，避免把上游源码提交到本仓库：

```bash
export POC_ROOT="$(mktemp -d)"
export AGENT_SANDBOX_VERSION="v0.5.6"
export AGENT_SANDBOX_PY_VERSION="0.5.6"
export KIND_CLUSTER_NAME="deepagent-sandbox-poc"
export SANDBOX_NAMESPACE="agent-sandbox-local"
export RUNTIME_IMAGE="deepagent/python-runtime:local"
export SKILL_IMAGE="deepagent/skill-sandbox:local"
export ROUTER_IMAGE="deepagent/sandbox-router:local"

git clone --branch "$AGENT_SANDBOX_VERSION" --depth 1 \
  https://github.com/kubernetes-sigs/agent-sandbox.git \
  "$POC_ROOT/agent-sandbox"
```

执行前应将 `AGENT_SANDBOX_VERSION` 更新为你测试当日的稳定 release，并让 Controller、Python SDK、Router 和 runtime 都使用同一 release。release 列表见 [Agent Sandbox releases](https://github.com/kubernetes-sigs/agent-sandbox/releases)。

## 5. 创建 kind 集群和 gVisor

Agent Sandbox 的基础 quickstart 默认创建不带容器运行时隔离的 kind 集群。要验证接近 GKE 的运行时隔离，必须**先**按官方 [gVisor on kind quickstart](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/examples/quickstart/gvisor.md) 配置 gVisor，然后再安装 Controller。

完成 gVisor quickstart 后，确认：

```bash
kubectl config use-context "kind-$KIND_CLUSTER_NAME"
kubectl get runtimeclass
```

期望存在可用于 Template 的 gVisor RuntimeClass。若 quickstart 创建的名称不是 `gvisor`，后文 Template 的 `runtimeClassName` 必须替换为实际名称。

> 若你只是先验证 Controller/Router/runtime 协议，可暂时使用普通 kind；但这不能验证 gVisor 隔离，也不能作为安全结论。

## 6. 安装 Controller、CRD 与 extensions

这些是集群级资源，安装一次即可。extensions 包含 `SandboxTemplate`、`SandboxClaim` 与 `SandboxWarmPool` 能力，Python SDK 需要它们。

```bash
kubectl apply -f \
  "https://github.com/kubernetes-sigs/agent-sandbox/releases/download/$AGENT_SANDBOX_VERSION/sandbox-with-extensions.yaml"

kubectl wait --for=condition=Ready pod \
  -l app=agent-sandbox-controller \
  -n agent-sandbox-system \
  --timeout=180s

kubectl get crd | rg 'agents.x-k8s.io'
kubectl get pods -n agent-sandbox-system
```

如果你希望分别控制 core 与 extensions，也可依次应用同一 release 的 `sandbox.yaml` 和 `extensions.yaml`。安装顺序和说明见 [官方 quickstart](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/examples/quickstart/README.md)。

## 7. 构建 runtime 镜像和自定义 Skill 镜像

### 7.1 构建官方 runtime 示例

```bash
docker build \
  -t "$RUNTIME_IMAGE" \
  "$POC_ROOT/agent-sandbox/examples/python-runtime-sandbox"
```

这一步构建的是官方示例中的 `/execute` server；它不是 Controller，也不是 Router。

### 7.2 在本项目创建 PoC Dockerfile

创建目录 `sandbox-poc/`（仅用于本地 PoC；正式引入时再决定最终目录）并添加：

```dockerfile
# sandbox-poc/Dockerfile
FROM deepagent/python-runtime:local

# 基础 runtime 的启动命令与 /execute server 保持不变。
# 仅增加 Skill 代码和构建时依赖。
USER root
COPY sandbox-poc/requirements-sandbox.lock /tmp/requirements-sandbox.lock
RUN pip install --no-cache-dir -r /tmp/requirements-sandbox.lock
COPY skill-packages /workspace/skills

# 运行时 UID 必须与官方 runtime 的非 root 用户一致；
# 构建后用 `docker image inspect` 和 `docker run --rm ... id` 核验。
USER 1000
```

为 PoC 创建一个最小 lock 文件，例如：

```text
# sandbox-poc/requirements-sandbox.lock
# 本次 smoke test 无额外依赖
```

构建前将该文件放到 Docker build context 根目录。若当前项目还没有可执行 Skill，先新增一个只读 `sandbox-smoke` Skill，其脚本只输出 Python 版本和固定 JSON。

构建：

```bash
docker build \
  -f sandbox-poc/Dockerfile \
  -t "$SKILL_IMAGE" \
  .

docker run --rm --entrypoint id "$SKILL_IMAGE"
```

如果上游 runtime 的实际非 root UID 不是 `1000`，更新 Dockerfile 最后一行；不要为了省事让 SandboxTemplate 以 root 运行。

### 7.3 将本地镜像导入 kind

```bash
kind load docker-image "$RUNTIME_IMAGE" --name "$KIND_CLUSTER_NAME"
kind load docker-image "$SKILL_IMAGE" --name "$KIND_CLUSTER_NAME"
```

local 镜像仅存在于 Docker Desktop 和 kind node 内；不会自动上传到任何远端 registry。

## 8. 构建并部署 Sandbox Router

Router 是 SDK 与 sandbox runtime 的 HTTP 代理，单独运行在集群中。

```bash
docker build \
  -t "$ROUTER_IMAGE" \
  "$POC_ROOT/agent-sandbox/clients/python/agentic-sandbox-client/sandbox-router"

kind load docker-image "$ROUTER_IMAGE" --name "$KIND_CLUSTER_NAME"
```

上游 Router manifest 使用环境变量引用镜像。先阅读并确认本 release 的 manifest，再部署：

```bash
sed -n '1,260p' \
  "$POC_ROOT/agent-sandbox/clients/python/agentic-sandbox-client/sandbox-router/sandbox_router.yaml"

ROUTER_IMAGE="$ROUTER_IMAGE" envsubst '${ROUTER_IMAGE}' \
  < "$POC_ROOT/agent-sandbox/clients/python/agentic-sandbox-client/sandbox-router/sandbox_router.yaml" \
  | kubectl apply -n agent-sandbox-system -f -

kubectl wait --for=condition=Available deployment \
  -l app=sandbox-router \
  -n agent-sandbox-system \
  --timeout=180s
kubectl get service -n agent-sandbox-system sandbox-router-svc
```

如果该 release 的 manifest 不使用 `${ROUTER_IMAGE}`，不要靠猜测替换；复制 manifest 到 PoC 目录，显式替换其 `image:` 值并设置 `imagePullPolicy: IfNotPresent` 或 `Never`，再 apply。

## 9. 创建 Template 和 WarmPool

```bash
kubectl create namespace "$SANDBOX_NAMESPACE"
```

将以下保存为 `sandbox-poc/template-and-pool.yaml`。`runtimeClassName` 仅在第 5 步完成 gVisor 配置时保留；普通 kind PoC 删除该行。

```yaml
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxTemplate
metadata:
  name: deepagent-python
  namespace: agent-sandbox-local
spec:
  podTemplate:
    spec:
      runtimeClassName: gvisor
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: runtime
          image: deepagent/skill-sandbox:local
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 8888
          readinessProbe:
            httpGet:
              path: /
              port: 8888
          resources:
            requests:
              cpu: 250m
              memory: 512Mi
            limits:
              cpu: "1"
              memory: 1Gi
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
      restartPolicy: OnFailure
---
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxWarmPool
metadata:
  name: deepagent-python-pool
  namespace: agent-sandbox-local
spec:
  replicas: 1
  sandboxTemplateRef:
    name: deepagent-python
```

```bash
kubectl apply -f sandbox-poc/template-and-pool.yaml
kubectl get sandboxtemplate,sandboxwarmpool -n "$SANDBOX_NAMESPACE"
kubectl get pods -n "$SANDBOX_NAMESPACE" -w
```

预热 Pod 必须进入 `Running` 与 `Ready`。若失败，先看事件：

```bash
kubectl get events -n "$SANDBOX_NAMESPACE" --sort-by='.lastTimestamp'
kubectl describe sandboxwarmpool deepagent-python-pool -n "$SANDBOX_NAMESPACE"
```

## 10. 使用 Python SDK 验证完整链路

安装与 Controller 同版本的 SDK：

```bash
python3 -m venv "$POC_ROOT/.venv"
. "$POC_ROOT/.venv/bin/activate"
pip install "k8s-agent-sandbox==$AGENT_SANDBOX_PY_VERSION"
```

保存为 `$POC_ROOT/smoke.py`：

```python
from k8s_agent_sandbox import SandboxClient
from k8s_agent_sandbox.models import SandboxLocalTunnelConnectionConfig

client = SandboxClient(
    connection_config=SandboxLocalTunnelConnectionConfig(server_port=8888)
)
sandbox = client.create_sandbox(
    warmpool="deepagent-python-pool",
    namespace="agent-sandbox-local",
)
try:
    result = sandbox.commands.run(
        "python /workspace/skills/sandbox-smoke/scripts/hello.py"
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    print("exit_code:", result.exit_code)
finally:
    sandbox.terminate()
```

执行：

```bash
python "$POC_ROOT/smoke.py"
```

成功标准：

- Python SDK 创建 `SandboxClaim`；
- Claim 从 WarmPool 获得 Pod；
- Router 转发到 runtime 的 `/execute`；
- Skill 脚本返回 stdout/stderr/exit code；
- `terminate()` 后 Claim 和 Sandbox 被回收。

## 11. 再接入 DeepAgent

只有第 10 步通过后，才在项目虚拟环境安装：

```bash
pip install "langchain-kubernetes[agent-sandbox]"
```

先做一个独立的 `KubernetesSandbox` smoke test，再接入现有 `create_agent_service()`。本项目的目标接入、thread 到 sandbox 生命周期映射和 feature flag 见 [GKE Agent Sandbox 开发方案](GKE_AGENT_SANDBOX_DEVELOPMENT_PLAN.md)。

不要在第 10 步之前移除当前 Harness 对 `execute` 的限制。

## 12. 清理

仅删除本 PoC 创建的明确目标：

```bash
kubectl delete namespace "$SANDBOX_NAMESPACE"
kind delete cluster --name "$KIND_CLUSTER_NAME"
docker image rm "$SKILL_IMAGE" "$RUNTIME_IMAGE" "$ROUTER_IMAGE"
```

不要在有其他项目运行的 Docker Desktop 或 Kubernetes context 上执行宽泛清理命令。

## 13. 常见故障

| 症状 | 首先检查 |
| --- | --- |
| `SandboxTemplate` 资源不存在 | extensions manifest 是否已安装；API version 是否与 release 匹配 |
| WarmPool Pod `ImagePullBackOff` | 是否执行了 `kind load docker-image`；`imagePullPolicy` 是否合适 |
| Pod 无法调度 | gVisor RuntimeClass 名称、kind gVisor 安装、CPU/内存是否足够 |
| SDK 创建后超时 | Controller、Router、runtime 的 readiness probe 和 port `8888` |
| `/execute` 返回 404 或连接失败 | runtime 是否使用官方示例协议；Router 是否指向正确 Pod/port |
| 运行时 root 被拒绝 | Dockerfile 最终 `USER` 与 Template `runAsUser` 不一致 |

## 14. 官方参考

- [Agent Sandbox quickstart](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/examples/quickstart/README.md)
- [gVisor on kind quickstart](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/examples/quickstart/gvisor.md)
- [Python Runtime Sandbox 源码](https://github.com/kubernetes-sigs/agent-sandbox/tree/main/examples/python-runtime-sandbox)
- [Sandbox Router 源码](https://github.com/kubernetes-sigs/agent-sandbox/tree/main/clients/python/agentic-sandbox-client/sandbox-router)
- [GKE Agent Sandbox 官方部署文档](https://cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox)
