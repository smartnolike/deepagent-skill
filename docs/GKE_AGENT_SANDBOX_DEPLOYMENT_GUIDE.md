# GKE 共享 Sandbox 部署手册

本项目在 dev / prod 各部署一个长期存在的、assistant-scoped `SandboxClaim`。应用只连接这个固定 Claim；不会在请求处理中创建或删除 Claim。

## 资源

```text
Sandbox Router (ClusterIP)
  └─ SandboxClaim/deepagent-assistant-{env}
       └─ SandboxTemplate/deepagent-runtime-template
            └─ 一个 gVisor Sandbox Pod
```

Router 保留给 `k8s-agent-sandbox` Python SDK 使用。应用在集群内通过 Router Service DNS 访问 Sandbox；禁止生产环境使用 `kubectl port-forward`。

## 固定 Template 与 Claim

将以下资源纳入 GitOps。镜像必须使用不可变 digest，`SANDBOX_IMAGE` 替换为实际值。

```yaml
apiVersion: extensions.agents.x-k8s.io/v1alpha1
kind: SandboxTemplate
metadata:
  name: deepagent-runtime-template
  namespace: danaan-gcp-portal
spec:
  podTemplate:
    spec:
      runtimeClassName: gvisor
      restartPolicy: OnFailure
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
          image: SANDBOX_IMAGE
          resources:
            requests: {cpu: 250m, memory: 512Mi}
            limits: {cpu: "1", memory: 1Gi}
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
---
apiVersion: extensions.agents.x-k8s.io/v1alpha1
kind: SandboxClaim
metadata:
  name: deepagent-assistant-prod
  namespace: danaan-gcp-portal
spec:
  sandboxTemplateRef:
    name: deepagent-runtime-template
  warmpool: none
```

镜像在构建期复制 `skill-packages` 到 `/workspace/skill-packages`，并创建可写的 `/workspace/staff-workspaces`。不要挂载主服务源码、Docker socket、hostPath、Kubernetes token 或云管理员凭据。

## Router 与连接验证

保留现有 Router Deployment 和 ClusterIP Service。`SANDBOX_ROUTER_URL` 指向其 in-cluster URL。

当前项目固定 `k8s-agent-sandbox==0.4.6`。应用配置的 `sandbox_claim_name` 必须与上述固定 Claim 一致。SDK 通过 Router 按 Claim 解析其已分配的 Sandbox，再执行命令、上传和下载文件。

```text
预期 pwd：
/workspace/staff-workspaces/<staff_id>/<conversation_id>/work
```

## 运行时文件清理

应用每小时删除超过两天未活动的 conversation workspace：

```text
/workspace/staff-workspaces/{staff_id}/{conversation_id}/
```

固定 Claim 绑定的 Sandbox 重建时会清空所有 runtime workspace。不要把 Sandbox 重启作为逐 conversation TTL 的实现方式；它会影响仍活跃的用户。

## 验收

- `kubectl get sandboxclaim deepagent-assistant-prod -n danaan-gcp-portal` 为 Ready，且 `status.sandbox.name` 有值；
- 正常 API 请求不创建或删除 `SandboxClaim`；
- Router 能执行命令与文件 I/O；
- 两个 conversation 写同名文件时，实际路径不同；
- 删除或过期一个 conversation 不影响其他 conversation；
- Sandbox 重建后 runtime workspace 为空，镜像中的 Skill 仍存在。
