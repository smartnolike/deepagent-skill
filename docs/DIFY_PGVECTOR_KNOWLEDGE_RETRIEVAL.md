# Dify PGVector 知识库只读检索方案

> 状态：设计提案。本文定义 DeepAgent Platform 读取 Dify 自托管知识库的边界；不实现 Dify 上传、解析、切块或向量化流程。

## 1. 决策

知识入库统一由 Dify 完成，本项目不提供上传接口、不重复保存原文件，也不重建 Dify 的向量索引。本项目在用户提问时，通过一个受控的只读 Tool 检索 Dify 的 PGVector 数据，并把检索片段及来源交给 DeepAgent。

```text
资料上传/同步 → Dify 知识库 → 文档解析、切块、Embedding → PGVector
                                                        ↓
用户消息 → DeepAgent → search_dify_knowledge Tool ────┘
                         ↓
                    命中文本 + 可追溯来源
                         ↓
                       Agent 回复
```

该方案的优点是只有 Dify 负责文档生命周期和索引构建，避免同一份资料在两个系统内重复切块与向量化。

## 2. 适用前提与边界

本方案仅适用于以下条件：

- 使用**自托管** Dify；
- Dify 的 `VECTOR_STORE` 配置为 `pgvector`；
- 本服务能够以网络方式连接 Dify 的 PGVector PostgreSQL 实例；
- 已知需要检索的 Dify knowledge base（dataset）ID；
- 本服务能够使用与该 dataset 完全相同的 Embedding 模型、模型版本、向量维度及归一化方式生成查询向量。

若 Dify 改用 Qdrant、Milvus、Elasticsearch 等其他向量后端，不能继续查询 PGVector 表，必须实现对应后端的 Repository。Dify 支持通过独立的 `PGVECTOR_*` 配置连接 PGVector；这并不等同于本项目自身的业务 PostgreSQL。参考 [Dify PGVector 配置示例](https://github.com/langgenius/dify/blob/main/api/.env.example)。

下列能力明确不在第一期范围内：

- 在本项目上传、解析、切块、删除或重建 Dify 文档；
- 修改 Dify 的表结构、向量表、索引或 Dify 管理的元数据；
- 对任意 dataset 自动全量搜索；
- 将检索命中自动写入长期记忆。

## 3. 连接和权限模型

应用需要两条逻辑上独立的数据库连接：

| 连接 | 用途 | 权限 |
| --- | --- | --- |
| 本项目业务 PostgreSQL | Conversation、Agent Run、Danaan、LangGraph | 按现有应用权限 |
| Dify PGVector / 元数据 PostgreSQL | 读取向量和文档元数据 | 专用账号，仅 `CONNECT`、schema `USAGE`、涉及对象 `SELECT` |

禁止复用 Dify 管理员账号或本项目业务写账号。Dify 连接字符串、数据库密码与 Embedding API Key 均使用 `SecretStr` / Secret Manager 管理，日志中不得输出。

建议新增独立配置块；具体类和 YAML 由实现阶段落地：

```yaml
dify_knowledge:
  enabled: true
  dataset_ids:
    - ${DIFY_KB_DATASET_ID}
  pgvector:
    host: ${DIFY_PGVECTOR_HOST}
    port: 5432
    database: ${DIFY_PGVECTOR_DATABASE}
    user: ${DIFY_PGVECTOR_READONLY_USER}
    password: ${DIFY_PGVECTOR_READONLY_PASSWORD}
    sslmode: require
  embedding:
    provider: openai_compatible
    model: ${DIFY_EMBEDDING_MODEL}
    base_url: ${DIFY_EMBEDDING_BASE_URL}
    api_key: ${DIFY_EMBEDDING_API_KEY}
  retrieval:
    top_k: 8
    candidate_k: 20
    min_score: 0.35
```

`dataset_ids` 是服务端白名单，不能由模型或 HTTP 调用者直接提供。不同部门或租户使用不同的白名单配置或可靠的身份到 dataset 映射。

## 4. Dify 内部存储的兼容性约束

Dify 的数据集、文档和分段元数据由 `datasets`、`documents`、`document_segments` 等内部模型维护；向量索引的物理表、字段及命名规则属于 Dify 实现细节，可能随版本和切块模式变化。当前实现中分段与 dataset/document ID 有关联，且检索流程会返回 dataset、document、segment 等来源元数据。参考 [Dify Dataset 模型](https://github.com/langgenius/dify/blob/main/api/models/dataset.py) 与 [Dify 检索实现](https://github.com/langgenius/dify/blob/main/api/core/rag/retrieval/dataset_retrieval.py)。

因此：

1. 不在业务代码中散落 Dify SQL；
2. 仅由 `DifyKnowledgeRepository` 知道当前已验证的 Dify 表、向量距离操作符和 join 关系；
3. 连接启动时执行只读兼容性检查：Dify 版本、目标 dataset、必要表/视图、Embedding 维度和一条固定 smoke query；
4. Dify 升级前在预发环境运行该兼容性检查和回归测试；
5. 若检查失败，禁用检索 Tool 并返回受控错误，不能退化为全库扫描或猜测表名。

不要在 Dify 管理的 `document_segments` 或向量表上添加自定义列、触发器、索引或 migration。它们的生命周期完全归 Dify 所有。

## 5. 检索 Tool 设计

注册一个应用内只读 Tool：

```text
search_dify_knowledge(query: str, runtime: ToolRuntime[AgentContext]) -> JSON
```

Tool 的执行步骤：

1. 从受信任的 runtime context 取得 `staff_id` 和授权后的 dataset 白名单；不接受模型传入 staff、tenant、表名或 dataset ID；
2. 用 Dify 同款 Embedding 配置计算 `query` 向量；
3. 对每个允许的 dataset 做参数化 PGVector 相似度检索，先取 `candidate_k` 个候选；
4. 通过 Dify 元数据过滤不可用内容：dataset 存在、document/segment 已完成、启用且未归档；
5. 依据相似度阈值、去重和每文档最大命中数取 `top_k`；
6. 返回最少必要的片段、分数和来源；不返回数据库连接信息、内部物理表名或未授权内容。

推荐返回结构：

```json
{
  "query": "如何申请 Cloud SQL",
  "results": [
    {
      "content": "……",
      "score": 0.86,
      "source": {
        "dataset_id": "...",
        "dataset_name": "云资源规范",
        "document_id": "...",
        "document_name": "Cloud SQL 开通指南.pdf",
        "segment_id": "...",
        "segment_position": 12,
        "source_url": null
      }
    }
  ]
}
```

Tool 只读取，不需要用户确认。查询、dataset ID、命中数量、耗时和错误类型可写审计日志；文档片段正文、向量、API Key、数据库凭据不得写日志。

## 6. Agent 与 Skill 边界

当前根 Agent 被限制为只处理启用的 Skill。要开放知识问答，需要新增 `skill-packages/knowledge-base-qa/SKILL.md` 并在 `agent.enabled_skills` 中启用；只增加 Tool 不足以让 Agent 处理通用知识库问题。

该 Skill 至少应要求：

- 回答前先调用 `search_dify_knowledge`；
- 仅基于 Tool 返回的内容作答；
- 没有足够命中时明确说明“知识库中未找到依据”，不得补写事实；
- 每个结论附带文档名称及可用时的页码/分段位置；
- 不将完整文档、命中片段或包含敏感数据的答案写入 MemoryService。

### 6.1 `knowledge-base-qa` Skill 模板

创建 `skill-packages/knowledge-base-qa/SKILL.md`，并将 `knowledge-base-qa` 加入 `agent.enabled_skills`。当前根 Agent 只处理已启用 Skill 所覆盖的请求，因此只注册检索 Tool 不会开放通用知识库问答。

```md
---
name: knowledge-base-qa
description: Answer factual questions using only the approved Dify knowledge bases. Always retrieve before answering and cite returned sources.
allowed-tools: search_dify_knowledge
metadata:
  version: "1.0.0"
---

# Knowledge Base Q&A

## Response language contract

Use the runtime `response_language` for all user-facing natural-language responses.
Keep tool names, JSON keys, IDs, URLs, and document names verbatim.

## Scope

Use this Skill only for questions that can be answered from the approved Dify knowledge bases.

Do not use this Skill to:
- create, modify, or delete cloud resources;
- perform actions in external systems;
- answer from unstated model knowledge when a factual answer is requested.

Requests for Danaan cloud-resource creation must use the `danaan-cloud-resource` Skill.

## Retrieval procedure

1. For every factual question in scope, call:

   `search_dify_knowledge(query="<user question>")`

2. Use only the returned `results` as the factual basis of the answer.

3. Treat a result as insufficient when:
   - `results` is empty;
   - results do not directly support the requested conclusion; or
   - returned sources conflict and the conflict cannot be resolved from the results.

4. When evidence is insufficient, say that no reliable answer was found in the knowledge base. Do not guess, invent a policy, or supplement with model knowledge.

5. Do not expose database details, vector scores, internal table names, credentials, or content from sources not returned by the Tool.

## Answer format

- Give the direct answer first.
- Clearly distinguish facts, procedures, prerequisites, and uncertainty.
- Cite every factual conclusion using the returned document metadata.

Use this citation format:

`[<document_name> · section <segment_position>]`

If a source URL is returned, use:

`[<document_name>](<source_url>)`

- Keep quotes short. Prefer concise paraphrases.
- If multiple documents disagree, identify the disagreement and cite both sources.
```

对应 YAML：

```yaml
agent:
  enabled_skills:
    - danaan-cloud-resource
    - knowledge-base-qa
```

职责必须保持分离：Skill 决定何时检索、如何基于证据作答和如何引用；`search_dify_knowledge` Tool 负责生成查询向量、访问 Dify PGVector、执行权限过滤及返回结果。知识问答 Skill 不应拥有创建资源等副作用 Tool。

### 6.2 Tool 描述要求

Tool 描述要让模型清楚这是一个有数据边界的事实检索能力：

```text
Search approved Dify knowledge bases for factual answers. Access scope is injected from trusted runtime context; callers cannot select datasets or tenants.
```

这项约束同时防止模型把 dataset ID、staff ID、tenant ID 或物理表名当成可调用参数。

## 7. Markdown 表格资料的入库规范

Markdown 表格可以被 Dify 作为文本处理，但“表格可以显示”不等于“问答时能稳定按行列还原”。Dify 的分段链路最终使用通用文本分段逻辑；其知识库管线可以配置分隔符、最大块长度和重叠，但不会对 Markdown 表格承诺行/列的原子性。参考 [Dify 文本分段实现](https://github.com/langgenius/dify/blob/main/api/core/rag/splitter/text_splitter.py) 与 [Dify 分段管线配置](https://github.com/langgenius/dify/blob/main/api/services/rag_pipeline/transform/file-general-high-quality.yml)。

### 7.1 适用性判断

| 数据类型 | 推荐方式 |
| --- | --- |
| 少量、窄且静态的表格 | 直接 Markdown 表格，上传后人工检查 Chunk Preview |
| 宽表、大表或字段对应严格的表格 | 表格保留给人阅读，同时添加每行一条的行式检索副本 |
| 高频更新、需要筛选/聚合、精确计算的数据 | 使用业务数据库查询 Tool；不要只放入 RAG |

### 7.2 推荐 Markdown 格式

保留原表格，同时在其后写出可独立检索的记录。每条记录都应带完整业务上下文，不能只列裸数值。

```md
## Cloud SQL 规格

| Region | Environment | Tier | HA |
| --- | --- | --- | --- |
| ASP | prod | db-custom-2-7680 | Yes |
| EUR | dev | db-custom-1-3840 | No |

## Cloud SQL 规格：可检索记录

- Cloud SQL specification: Region=ASP; Environment=prod;
  Tier=db-custom-2-7680; High Availability=Yes.
- Cloud SQL specification: Region=EUR; Environment=dev;
  Tier=db-custom-1-3840; High Availability=No.
```

中文资料也采用同样形式：

```md
- Cloud SQL 规格：区域=ASP；环境=prod；规格=db-custom-2-7680；高可用=是。
```

行式记录让向量检索可以召回完整的“字段—值”事实，而不是依赖模型从可能已被分段切开的 Markdown 管道表格中拼接行和列。

### 7.3 分段与质量规则

1. 一个逻辑表尽量不跨 chunk；大表按业务主题、日期或每 20–50 行拆为多个独立小表；
2. 每个表和每组行式记录前都添加具体标题，例如“2026 年生产环境 Cloud SQL 配额”；
3. 选择 Dify 自定义分段规则，合理设定最大块长度和重叠；不要只依赖默认规则；
4. Dify 上传后必须检查 Chunk Preview，确认表头/上下文仍和数据行在同一 chunk，且没有在半行截断；
5. 对产品 ID、错误码、工单号等精确字串，在行式记录中保持原文并在二期通过全文检索补强；
6. 不使用 HTML 注释隐藏检索文本；应将行式副本作为正常 Markdown 内容写出，确保其进入解析结果；
7. 文档内容或表格变更后，等待 Dify 索引状态为 completed 再进行检索验证。

### 7.4 评测标准

不存在可脱离资料、模型和问题集的通用“表格识别率”。上线前应建立至少 20–50 条真实测试问题，覆盖：

- 单字段查询，例如“ASP 的生产环境使用什么 Tier？”；
- 多条件筛选，例如“EUR 且 dev 环境是否启用高可用？”；
- 精确编号、产品名和错误码；
- 表中不存在的组合或值；
- 需要区分不同版本、日期或环境的数据。

每条问题标注期望 document、segment 和答案。分别评估 Top-K 召回率、最终答案正确性、引用正确性和“无依据时拒答”的正确性。未达到目标时，先修正文档结构和 chunk，再调整检索参数；不要仅通过扩大 Top-K 掩盖表格被错误切分的问题。

## 8. PostgreSQL 全文检索与混合排序（二期）

PostgreSQL 原生支持全文检索：`tsvector`、`tsquery`、`GIN` 索引和 `ts_rank_cd`。它适合精确关键词、错误码、产品名、工单号等场景；PGVector 更擅长语义相似问题。

但不应直接在 Dify 内部表上增加全文索引。二期创建本项目拥有的只读检索投影表，例如 `ai_agent_dify_kb_search_projection`：

```text
segment_id (PK) | dataset_id | document_id | document_name | content | content_tsv | updated_at
```

投影由受控同步任务从 Dify 的已完成且启用分段增量同步；删除、禁用和归档同样同步。该表可以安全地建立全文索引：

```sql
CREATE INDEX ai_agent_dify_kb_projection_fts_idx
ON ai_agent_dify_kb_search_projection USING GIN (content_tsv);
```

中文不能只用 PostgreSQL 的 `simple` 配置，因为它不做中文分词。实施时选定并固定一种分词方案（例如 `pg_jieba`、`zhparser`，或应用层预分词），写入和查询必须使用同一方案。对短 ID、错误码和近似拼写可额外使用 `pg_trgm`。

混合排序流程如下：

```text
向量 Top 20 ─┐
             ├→ RRF 融合 → 去重/阈值 → 最终 Top 5–8
全文 Top 20 ─┘
```

第一期不做混合排序；先验证纯向量命中的可用性。二期采用 RRF（Reciprocal Rank Fusion），避免直接混合不同量纲的向量距离和全文分数。

## 9. 实施顺序与验收

### 第一期：Dify PGVector 只读向量检索

1. 新增 `DifyKnowledgeSettings`，在 local/dev/prod 配置 Secret 引用；
2. 创建只读 Dify 数据源与连接健康检查；
3. 实现 `DifyKnowledgeRepository`、`DifyKnowledgeService`、`search_dify_knowledge` Tool；
4. 新增并启用 `knowledge-base-qa` Skill；
5. 为检索服务补充单元测试、真实 PGVector 集成测试和 Dify 升级 smoke test；
6. 将命中来源以 SSE 事件或最终回答引用形式提供给前端。

验收标准：

- Dify 上传一份文档并显示索引完成后，可在本项目中检索到对应分段；
- 禁用/归档 Dify 文档后，该文档不再返回；
- 非白名单 dataset 的内容永不返回；
- 相同 query 在 Dify 和本项目使用相同 embedding 时，候选结果可解释地一致或差异可审计；
- Dify 连接不可用或 schema 不兼容时，服务安全失败，且不影响 Danaan 现有流程；
- 日志、SSE 和错误响应中不存在向量、凭据或未授权文档正文。

### 第二期：全文检索投影与 RRF

仅在第一期检索质量测试显示确有必要时实施。验收包括中文分词覆盖、精确编号召回、同步延迟指标以及混合排序相对于纯向量的离线评测提升。

## 10. 上线前需要确认的信息

实施前必须从实际 Dify 部署确认：

1. Dify 版本、部署方式及 `VECTOR_STORE=pgvector`；
2. PGVector 主机、端口、数据库、SSL/CA 要求，以及可建立的只读账号；
3. 要授权给本项目的 dataset ID、租户和部门访问规则；
4. 每个 dataset 使用的 Embedding provider、模型、维度、归一化和 API 凭据获取方式；
5. Dify 的实际物理表/collection 结构及一份脱敏的 schema dump；
6. 文档来源链接是否能由 DeepAgent 前端直接访问，以及是否需要 Dify 签名 URL；
7. 中文检索质量目标，是否需要第二期全文检索。
