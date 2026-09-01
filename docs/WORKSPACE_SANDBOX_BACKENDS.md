# DeepAgent 共享 GKE Sandbox

## 目标

生产环境使用一个由基础设施预先部署的 GKE Agent Sandbox。应用只连接这个固定 Sandbox，绝不在请求处理过程中创建或删除 `SandboxClaim`。

这实现 DeepAgents 的 assistant-scoped 语义：同一 Agent 的所有 conversation 共享一个运行环境；会话文件仍在环境内部按 staff 和 conversation 分隔。

```text
DeepAgent API
  └─ Sandbox Router
       └─ Sandbox/deepagent-sandbox-{env} (replicas: 1)
            └─ /workspace
                 ├─ skill-packages/                 # 镜像内置，只读
                 └─ staff-workspaces/
                      └─ {staff_id}/{conversation_id}/
                           ├─ work/
                           └─ output/
```

## Provider

| provider | 用途 | 文件位置 |
| --- | --- | --- |
| `filesystem` | 本地只读验证 Skill | 本地 `skill-packages/`；无执行和 artifact |
| `gke_backend` | dev / prod | 一个固定 GKE Sandbox 的 `/workspace/staff-workspaces/<staff_id>/<conversation_id>` |

## 路径契约

Agent 继续使用逻辑路径：

```text
/work/<file>
/output/<file>
```

`GkeSandboxBackend` 从可信运行上下文的 `staff_id` 与 LangGraph `thread_id`（即 `conversation_id`）映射真实路径：

```text
/work/a.json
→ /workspace/staff-workspaces/{staff_id}/{conversation_id}/work/a.json

/output/report.xlsx
→ /workspace/staff-workspaces/{staff_id}/{conversation_id}/output/report.xlsx
```

脚本的工作目录是该 conversation 的 `work/`，故同一会话的多个脚本可用相对路径复用中间文件。`staff_id` 必须由后端认证上下文给出，并仅允许安全目录字符；`conversation_id` 是 UUID。

## 代码职责

`GkeSandboxBackend` 是唯一的 GKE Backend：

- 连接配置中固定的 `sandbox_name`；
- 解析当前 `staff_id` / `conversation_id`；
- 创建当前目录的 `work/` 和 `output/`；
- 映射文件、artifact 与执行 cwd；
- 调用 GKE Router 的命令和文件 API。

不再使用 `WorkspaceManager`、`WorkspaceSessionStore`、provider 抽象、按 conversation 的 Sandbox session，或应用侧 Claim 生命周期。
`agent_factory` 直接选择 `FilesystemBackend` 或固定的 `GkeSandboxBackend`；`GkeWorkspaceService` 负责产物读取、目录删除和 TTL 清理。

`thread_id` 仍是 conversation ID，仅用于 LangGraph checkpoint、消息历史与 HITL resume；它不再决定 Sandbox 的身份。

## 生命周期

- 基础设施通过 GitOps / Kubernetes 部署固定 `kind: Sandbox`，名称例如 `deepagent-sandbox-prod`，`replicas: 1`。
- 应用启动与请求处理只检查、连接该 Sandbox；不会调用 `create_sandbox()` 或 `terminate()`。
- 每个 conversation workspace 的最后活动时间保存到数据库。定时任务每小时清理超过 `workspace_retention_seconds`（默认 172800，即两天）的目录；artifact 记录按同一过期时间在读取时拒绝访问，并随 conversation 删除级联删除。
- 不挂 PVC 时，Sandbox Pod 被删除并重建会清空全部 runtime workspace；这是本方案的预期行为。若未来需要跨 Pod 重启保留文件，再挂载 PVC。
- conversation 删除只删除自己的 workspace 目录，绝不影响固定 Sandbox。

## execute 与安全边界

`gke_backend` 保留 DeepAgents 原生 `execute`。`execute_requires_confirmation=true` 时进入现有 HITL 流程。

目录隔离避免正常业务流程中文件重名和混淆；它不是任意 shell 的 Linux 权限边界。当前方案建立在只发布、审核过的 Skill 与受控运行环境的前提上。若以后要禁止模型通过任意绝对路径访问其他 workspace，需要另行引入受控执行器。

## Artifact

Agent 将最终文件写入 `/output` 后调用 `publish_artifact`。记录保存逻辑输出路径和 conversation 归属；下载时后端重新映射到当前 staff/conversation 的 output 目录。Workspace 被清理、Sandbox 重建或文件丢失时下载返回 `410 Gone`。

## 扩展边界

一个 assistant 对应一个有状态 Sandbox replica。不能简单增加同一个 Sandbox 的副本：不同副本的本地文件系统不同，后续脚本可能读不到前一步产物。增加 GKE 节点没有影响；Router 继续路由到固定 Sandbox 的当前 Pod。

多 Sandbox 扩展需要未来单独设计分片映射或共享存储，本方案不包含该能力。
