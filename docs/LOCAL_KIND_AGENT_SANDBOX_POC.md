# Windows Docker Desktop 内置 Kubernetes（Kind）本地 Sandbox 手册

> 目标：在 Windows 本机运行本项目的 FastAPI/DeepAgent，在 Docker Desktop **内置 Kubernetes 的 Kind provisioner** 中运行 Agent Sandbox。Skill 的脚本实际在 Sandbox Pod 内执行，而非在 Windows 主机执行。

> 本手册是本地集成测试方案，不是 GKE 部署方案。使用开源 `kubernetes-sigs/agent-sandbox` Controller；**不要**在 Docker Desktop Kubernetes 中尝试启用 GKE add-on。GKE 路径见 [GKE Agent Sandbox 部署手册](GKE_AGENT_SANDBOX_DEPLOYMENT_GUIDE.md)。

## 1. 最终架构

```text
Windows PowerShell
├─ 本项目 FastAPI / DeepAgent
│  └─ 应用内 DeepAgents adapter + 官方 k8s-agent-sandbox（connection_mode=direct）
│     └─ kubectl port-forward（开发者手动维护）
│        └─ Docker Desktop Kubernetes 内的 Sandbox Router Service :8080
│           └─ Sandbox Pod 的 runtime :38087
│              └─ /workspace/skills/<skill>/scripts/*.py
└─ Docker Desktop
   └─ 内置 Kubernetes（Kind provisioner）
      ├─ Agent Sandbox Controller + CRD
      ├─ Sandbox Router
      ├─ SandboxTemplate
      └─ SandboxWarmPool
```

端口职责必须区分：

| 组件 | 端口 | 配置位置 |
| --- | ---: | --- |
| Router Service | `8080` | Router manifest；本机手动 port-forward 的目标 |
| Python runtime | `38087` | SandboxTemplate 的 `containerPort`、probe 与应用 `runtime_port` |
| 本项目 API | `8000` | Windows 上运行的 FastAPI 服务 |

不要把某个 Sandbox Pod 的 IP 或 Pod DNS 填进项目配置；Pod 会由 WarmPool/Claim 生命周期替换。

## 2. 何时用 LocalShell，何时用 Docker Desktop Kubernetes

| 模式 | 启动方式 | 命令实际执行位置 | 用途 |
| --- | --- | --- | --- |
| 快速脚本调试 | 默认 | Windows 主机 | 仅调试已信任的脚本；每条命令要求人工确认 |
| Kind 集成测试 | `SANDBOX_PROVIDER=gke_agent` | Docker Desktop Kubernetes 的 Sandbox Pod | 验证 Controller、Router、镜像、依赖、Skill 脚本和 DeepAgent 调用链 |

`LocalShellBackend` 没有隔离。要验证真实 Pod 生命周期与镜像依赖，使用本手册的 Docker Desktop Kubernetes 模式。

## 3. Windows 前置条件

### 3.1 Docker Desktop

安装并启动 Docker Desktop，确认它使用 **Linux containers** 和 WSL 2 backend。Docker Desktop 建议至少分配 8 GB 内存、4 个 CPU；WarmPool 会持续运行 Pod。

在 PowerShell 执行：

```powershell
docker version
docker info --format '{{.OSType}}'
```

第二条应输出 `linux`。不是时，先在 Docker Desktop 切换到 Linux containers 并重启。

然后在 Docker Desktop **Settings > General** 确认 `Use containerd for pulling and storing images` 已启用（新版本默认启用）。Docker Desktop 的内置 Kind 只支持 containerd image store，不支持旧 Docker image store。

### 3.2 工具

需要以下命令在 PowerShell 的 `PATH` 中：

- `kubectl` 1.28 或更新版本；
- Git；
- Python 3.12 与本项目的 `uv` 环境；
- 本项目已执行 `uv sync`。

如果使用 WinGet，可先搜索和安装；公司设备的安装策略以 IT 要求为准：

```powershell
winget search kubectl
winget search Git
winget search uv
```

检查：

```powershell
kubectl version --client
git --version
uv --version
```

官方基础要求和组件说明见 [Agent Sandbox quickstart](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/examples/quickstart/README.md)。

## 4. 定义本地变量

打开 **PowerShell**，进入项目根目录。以下变量仅在当前 PowerShell 窗口有效：

```powershell
$ProjectRoot = (Get-Location).Path
$SandboxNamespace = 'agent-sandbox'
$ControllerNamespace = 'agent-sandbox-system'
$TemplateName = 'deepagent-skill-runtime'
$WarmPoolName = 'deepagent-skill-runtime-pool'
$RuntimePort = 38087
$RouterImage = 'deepagent/sandbox-router:desktop-kind'
$RuntimeImage = 'deepagent/skill-runtime:desktop-kind'
$AgentSandboxVersion = 'v0.4.6'
$PocRoot = Join-Path $env:TEMP 'deepagent-agent-sandbox-poc'
$UpstreamRoot = Join-Path $PocRoot 'agent-sandbox'
```

> `v0.4.6` 与当前项目锁定的 `k8s-agent-sandbox==0.4.6` 对齐，使用 `v1alpha1` CRD。升级时要同时验证 Controller、Router、SDK、CRD API version 与项目内 adapter，不能只升级其中一个。

## 5. 在 Docker Desktop 创建内置 Kind 集群

无需安装或运行独立 `kind.exe`。在 Docker Desktop Dashboard 操作：

1. 打开 **Kubernetes** 页面；
2. 点击 **Create cluster**；
3. Cluster type 选择 **kind**，不要选旧的 `kubeadm`；
4. 初次 PoC 选 1 node 即可；
5. 点击 **Create**，等待状态变为 Running。

回到 PowerShell 验证：

```powershell
kubectl config current-context
kubectl cluster-info
kubectl get nodes
```

预期 context 为 `docker-desktop`。后续所有 `kubectl` 命令都必须保持该 context，不能再执行 `kind create cluster` 或 `kind delete cluster`。

> Docker Desktop Kind 的 Enhanced Container Isolation（ECI）不等于 GKE Agent Sandbox 所用的 gVisor RuntimeClass。本手册验证的是 Agent Sandbox 功能链路；不在 Template 中设置 `runtimeClassName: gvisor`，也不将本机测试视为 GKE gVisor 安全验证。

## 6. 下载上游源码并安装开源 Controller/CRD

```powershell
New-Item -ItemType Directory -Force $PocRoot | Out-Null
if (Test-Path $UpstreamRoot) { Remove-Item -Recurse -Force $UpstreamRoot }
git clone --branch $AgentSandboxVersion --depth 1 `
  https://github.com/kubernetes-sigs/agent-sandbox.git $UpstreamRoot

kubectl apply -f "https://github.com/kubernetes-sigs/agent-sandbox/releases/download/$AgentSandboxVersion/sandbox-with-extensions.yaml"
kubectl wait --for=condition=Ready pod -l app=agent-sandbox-controller `
  -n $ControllerNamespace --timeout=180s

kubectl get crd | Select-String 'agents.x-k8s.io'
kubectl get pods -n $ControllerNamespace
```

`SandboxTemplate`、`SandboxClaim` 和 `SandboxWarmPool` 来自 extensions；缺少它们时，后续 WarmPool 无法创建。

如果 `kubectl wait` 超时，先执行：

```powershell
kubectl get pods -n $ControllerNamespace
kubectl get events -n $ControllerNamespace --sort-by='.lastTimestamp'
kubectl logs -n $ControllerNamespace -l app=agent-sandbox-controller --tail=200
```

## 7. 构建并导入 Router 镜像

Router 是独立集群组件，不在 Python runtime 镜像中。

```powershell
$RouterSource = Join-Path $UpstreamRoot 'clients/python/agentic-sandbox-client/sandbox-router'
docker build -t $RouterImage $RouterSource
```

上游 Router manifest 使用的是 release 内的真实字段。先查看，确认 `image:` 与 `imagePullPolicy` 的写法：

```powershell
$RouterManifestPath = Join-Path $RouterSource 'sandbox_router.yaml'
Get-Content $RouterManifestPath
```

Docker Desktop Kind 使用 containerd image store；本机 `docker build` 的镜像可由该集群使用。将 manifest 复制到临时目录后，替换镜像并设置 `imagePullPolicy: IfNotPresent`：

```powershell
$RouterManifest = Get-Content $RouterManifestPath -Raw
$RouterManifest = $RouterManifest.Replace('${ROUTER_IMAGE}', $RouterImage)
$RouterManifest = $RouterManifest -replace '# imagePullPolicy: Never', 'imagePullPolicy: IfNotPresent'
$RouterManifest | kubectl apply -n $ControllerNamespace -f -

kubectl wait --for=condition=Available deployment -l app=sandbox-router `
  -n $ControllerNamespace --timeout=180s
kubectl get deployment,service -n $ControllerNamespace -l app=sandbox-router
```

Router Service 应保持 `ClusterIP`。本机通过 port-forward 访问它；不要为了本地测试创建公网 LoadBalancer 或 Ingress。

## 8. 构建 runtime 镜像（端口 38087、包含 Skill）

官方 Python runtime 示例默认监听 `8888`。本项目配置为 `38087`，因此本地也必须构建监听 `38087` 的兼容 runtime。

### 8.1 准备 build context

```powershell
$RuntimeContext = Join-Path $PocRoot 'runtime-context'
if (Test-Path $RuntimeContext) { Remove-Item -Recurse -Force $RuntimeContext }
New-Item -ItemType Directory -Force $RuntimeContext | Out-Null

Copy-Item "$UpstreamRoot/examples/python-runtime-sandbox/*" $RuntimeContext -Recurse
Copy-Item "$ProjectRoot/skill-packages" "$RuntimeContext/skills" -Recurse
```

修改 `Dockerfile`：在原官方 runtime 的基础上，加入脚本目录、常用只读命令，并将全部 `8888` 改为 `38087`。以下命令生成可审查的 Dockerfile：

```powershell
$Dockerfile = @'
FROM python:3.14-slim

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 bash coreutils findutils grep \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY main.py .
COPY skills /workspace/skills
RUN chown -R 1000:1000 /app /workspace/skills
USER 1000

EXPOSE 38087
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "38087", "--log-level", "trace"]
'@
Set-Content -Path (Join-Path $RuntimeContext 'Dockerfile') -Value $Dockerfile -NoNewline

docker build -t $RuntimeImage $RuntimeContext
docker run --rm --entrypoint id $RuntimeImage
```

最后一条 `id` 必须显示非 root UID（官方示例为 `1000`）。`ls` 与 `grep` 是操作系统命令，不受 Python runtime 限制；是否可用取决于镜像内是否安装，本 Dockerfile 已显式安装。

Skill 目前只有 `SKILL.md` 而没有脚本时，先不要测试某个业务脚本；第 10 步可先执行 `python -c`，确认链路后再添加 `skill-packages/<skill>/scripts/*.py` 并重建镜像。

## 9. 创建 Template 和 WarmPool

创建 namespace：

```powershell
kubectl create namespace $SandboxNamespace
```

创建 `$PocRoot/template-and-pool.yaml`：

```powershell
$TemplateManifest = @"
apiVersion: extensions.agents.x-k8s.io/v1alpha1
kind: SandboxTemplate
metadata:
  name: $TemplateName
  namespace: $SandboxNamespace
spec:
  podTemplate:
    spec:
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
      containers:
        - name: python-runtime
          image: $RuntimeImage
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: $RuntimePort
          readinessProbe:
            httpGet:
              path: /
              port: $RuntimePort
            periodSeconds: 1
          resources:
            requests:
              cpu: 250m
              memory: 512Mi
            limits:
              cpu: "1"
              memory: 1Gi
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
      restartPolicy: OnFailure
---
apiVersion: extensions.agents.x-k8s.io/v1alpha1
kind: SandboxWarmPool
metadata:
  name: $WarmPoolName
  namespace: $SandboxNamespace
spec:
  replicas: 1
  sandboxTemplateRef:
    name: $TemplateName
"@
Set-Content -Path (Join-Path $PocRoot 'template-and-pool.yaml') -Value $TemplateManifest -NoNewline

kubectl apply -f (Join-Path $PocRoot 'template-and-pool.yaml')
kubectl get sandboxtemplate,sandboxwarmpool -n $SandboxNamespace
kubectl get pods -n $SandboxNamespace -w
```

等待 WarmPool Pod 为 `Running` 且 `Ready`。如果是 `ImagePullBackOff`，先确认 Docker Desktop 的 containerd image store 已启用、镜像标签和 manifest 一致、并使用 `imagePullPolicy: IfNotPresent`。若公司策略使 Kubernetes 无法访问本机镜像，改为把无敏感信息的 PoC 镜像推送至私有 Docker Hub 或公司 Artifact Registry，再将 manifest 的 `image:` 改为该完整仓库地址。

## 10. 不经 DeepAgent 的 SDK 冒烟测试

先验证基础设施，避免把 Controller/镜像问题误判为 Agent 问题。先在独立 PowerShell 窗口保持 Router 转发：

```powershell
kubectl -n $ControllerNamespace port-forward svc/sandbox-router-svc 8080:8080
```

项目已安装 `k8s-agent-sandbox`，在项目虚拟环境创建 `$PocRoot/smoke.py`：

```powershell
$SmokeScript = @"
from k8s_agent_sandbox import SandboxClient
from k8s_agent_sandbox.models import SandboxDirectConnectionConfig

client = SandboxClient(
    connection_config=SandboxDirectConnectionConfig(
        api_url='http://127.0.0.1:8080',
        server_port=38087,
    )
)
sandbox = client.create_sandbox(
    template='deepagent-skill-runtime',
    namespace='agent-sandbox',
)
try:
    result = sandbox.commands.run("python -c 'import sys; print(sys.version)'")
    print('stdout:', result.stdout)
    print('stderr:', result.stderr)
    print('exit_code:', result.exit_code)
finally:
    sandbox.terminate()
"@
Set-Content -Path (Join-Path $PocRoot 'smoke.py') -Value $SmokeScript -NoNewline

uv run python (Join-Path $PocRoot 'smoke.py')
```

成功标准：

- 通过手动 port-forward 连接 Router；
- 创建 `SandboxClaim`，并由 WarmPool 领取一个 Pod；
- 命令在 runtime 内返回 Python 版本，`exit_code` 为 `0`；
- `terminate()` 后 Claim 被回收，WarmPool 自动补充预热 Pod。

观察资源：

```powershell
kubectl get sandboxclaim,sandbox -n $SandboxNamespace
kubectl get pods -n $SandboxNamespace
kubectl get events -n $SandboxNamespace --sort-by='.lastTimestamp'
```

## 11. 使用本项目连接 Docker Desktop Kubernetes

确认 kubeconfig 仍指向 Docker Desktop：

```powershell
kubectl config current-context
# 预期：docker-desktop
```

启用 Kubernetes sandbox backend 并按 Windows 入口启动本项目：

```powershell
$env:AGENT_ENV = 'local'
$env:SANDBOX_PROVIDER = 'gke_agent'
.\.venv\Scripts\python.exe src\main.py
```

> Windows 必须使用 `src\main.py` 入口，而不是直接运行 `uvicorn` CLI；项目入口会设置 psycopg3 所需的 `WindowsSelectorEventLoopPolicy`。

此时 [`config/local.yaml`](../config/local.yaml) 选择：

```yaml
provider: ${SANDBOX_PROVIDER:-local_shell}
gke:
  connection_mode: direct
  namespace: ${SANDBOX_NAMESPACE:-agent-sandbox}
  template_name: ${SANDBOX_TEMPLATE_NAME:-deepagent-skill-runtime}
  router_url: ${SANDBOX_ROUTER_URL:-http://127.0.0.1:8080}
  runtime_port: 38087
```

项目内 adapter 使用官方 `k8s-agent-sandbox==0.4.6` 创建 `v1alpha1` Template Claim。每条 `run_skill_script` 仍先进入应用既有的人工确认 SSE 流程，确认后才会发往 Sandbox Pod。

## 12. 常见故障

| 现象 | 优先检查 |
| --- | --- |
| `kubectl` 连错集群 | `kubectl config current-context` 必须是 `docker-desktop` |
| Controller 无 Ready | Docker Desktop 是否运行、Controller events/log、CRD 是否已安装 |
| WarmPool `ImagePullBackOff` | Docker Desktop 的 containerd image store、镜像名、`imagePullPolicy: IfNotPresent`；必要时推送到私有 registry |
| Router 不 Ready | Router manifest 的本地镜像是否替换成功，及 Service/Deployment 是否位于 `agent-sandbox-system` |
| Router 连接失败 | 手动运行 `kubectl -n agent-sandbox-system port-forward svc/sandbox-router-svc 8080:8080`，并确认 `SANDBOX_ROUTER_URL=http://127.0.0.1:8080` |
| `connection refused` / `/execute` 失败 | Template `containerPort`、probe、项目 `runtime_port`、Dockerfile CMD 必须全为 `38087` |
| `execute` 未出现在 Agent | 确认 `$env:SANDBOX_PROVIDER = 'gke_agent'` 在启动进程中已设置 |
| 应用启动后数据库异常 | 按 README 启动本地 PostgreSQL，并使用 `src\main.py` 入口 |

## 13. 清理

确认当前 context 是 `docker-desktop` 后删除本手册创建的 namespace：

```powershell
kubectl config current-context
kubectl delete namespace $SandboxNamespace
```

如需删除整个本地集群，在 Docker Desktop 的 **Kubernetes** 页面选择 **Stop** 或 **Reset cluster**。这会删除该集群内的全部 Kubernetes 资源，不仅是 Sandbox。

可选地删除本次构建的明确镜像和临时上游目录：

```powershell
docker image rm $RuntimeImage $RouterImage
Remove-Item -Recurse -Force $PocRoot
```

不要对 Docker Desktop、`C:\`、用户目录或未知 Kubernetes context 执行宽泛删除。

## 14. 官方参考

- [Agent Sandbox quickstart](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/examples/quickstart/README.md)
- [Docker Desktop Kubernetes（Kind provisioner）](https://docs.docker.com/desktop/use-desktop/kubernetes/)
- [Python runtime 示例](https://github.com/kubernetes-sigs/agent-sandbox/tree/main/examples/python-runtime-sandbox)
- [Sandbox Router 源码与 manifest](https://github.com/kubernetes-sigs/agent-sandbox/tree/main/clients/python/agentic-sandbox-client/sandbox-router)
- [官方 k8s-agent-sandbox Python SDK](https://pypi.org/project/k8s-agent-sandbox/)
- [GKE Agent Sandbox 官方文档](https://cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox)
