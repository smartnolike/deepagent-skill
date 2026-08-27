# DeepAgent 会话工作区 Backend

本方案让 DeepAgents 的文件 Tool 与 `execute` 使用同一个 Backend。一个 `conversation_id` 对应一个
工作区；同一会话内多轮调用、多个脚本都能读取前一步生成的文件，不在应用主机与 Sandbox 之间隐式同步。

## 环境选择

| provider | 用途 | Skill 来源 | 执行与文件位置 |
| --- | --- | --- | --- |
| `filesystem` | 本地快速测试 Skill 指令 | 本地 `skill-packages/` | 只读，无 `execute`、无 artifact |
| `local_shell` | 本地完整流程测试 | 首次创建会话时复制到会话目录 | `.runtime/deepagent-workspaces/<conversation_id>` |
| `gke_backend` | dev / prod | runtime 镜像内 `/workspace/skill-packages` | 会话专属 GKE Sandbox 的 `/workspace` |

local 可通过配置切换以上三种 provider。dev/prod 示例固定使用 `gke_backend`，不设置单独 staging 方案。

## 代码职责边界

`WorkspaceManager` 只负责按当前会话选择 provider、串联 session 生命周期与 Backend 返回；它不直接执行
SQL、Kubernetes SDK 或文件系统操作。`WorkspaceSessionStore` 负责 PostgreSQL session 和 advisory lock，
`workspace_providers.py` 负责 filesystem / local shell / GKE 的资源差异，`GkeSandboxClient` 隔离固定
`v1alpha1` SDK 的连接细节，`WorkspaceArtifactService` 负责 `/output` 路径规范化和访问限制。

DeepAgents 0.7 不再接受 backend factory。因此 local shell / GKE 使用一个已初始化的
`ConversationSandboxBackend` 代理；每次文件或 `execute` 操作才从当前 LangGraph `thread_id` 解析实际会话
Workspace。filesystem 则直接使用已初始化的 `FilesystemBackend`。

## 目录契约

- `/workspace/skill-packages`：只读 Skill 发布内容；兼容别名 `/skill-packages`。
- `/workspace/work`：脚本中间文件；兼容别名 `/work`。
- `/workspace/output`：允许发布给用户下载的最终文件；兼容别名 `/output`。

仓库中的源码目录仍叫 `skill-packages`，无需迁移现有 Skill。GKE runtime 使用
`sandbox-runtime.Dockerfile` 构建：Skill 文件归 `root` 且对运行用户只读，`work` 和 `output` 归 UID 1000。

## 会话生命周期

`ai_agent_sandbox_sessions` 持久化会话与 Backend 引用。创建前使用 PostgreSQL advisory transaction lock，
保证多个应用副本同时处理同一会话时只创建一个工作区。GKE 会话优先按 claim name 重连；绝对 TTL 由
Sandbox claim lifecycle 执行，应用也按 `idle_ttl_seconds` 判定长时间未使用的引用已过期。

当前适配器使用 `k8s-agent-sandbox==0.4.6` 的 `SandboxClient`，对应现有 GKE 托管 controller/CRD 的
`v1alpha1` 接口。升级 controller 与客户端必须作为同一次平台变更验证，不能单独升到要求 `v1beta1` 的客户端。

## execute 与确认

`local_shell` 和 `gke_backend` 都把 Backend 原生 `execute` 暴露给 Agent。配置
`sandbox.execute_requires_confirmation: true` 时，它进入现有 LangGraph HITL 流程；GKE 可根据风险接受度
设为 `false`。本机 shell 模式只要启用执行，就必须保留确认。

## Artifact 下载

脚本先把最终文件写入 `/output`，再调用 `publish_artifact`。该 Tool 只记录 Sandbox 路径、文件名、类型、
大小和有效期，不复制到 GCS。流式接口发送 `artifact_created`，前端携带 API token 调用：

```text
GET /agent/api/conversations/{conversation_id}/artifacts/{artifact_id}/download?staff_id=...
```

应用校验会话归属和 artifact 记录后，通过对应 Backend 的文件读取 API 返回内容。Sandbox 已删除、文件丢失
或记录过期时返回 `410 Gone`；用户需要让 Agent 重新生成。
