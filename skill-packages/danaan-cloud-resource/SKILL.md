---
name: danaan-cloud-resource
description: 为 Danaan 管理的 Cloud Storage、BigQuery 和 Cloud SQL 创建资源申请。确认基础资料，按 resourceName 读取模板，仅替换资源名后提交经用户确认的申请。
allowed-tools: get_skill_memory request_user_form danaan_get_resource_template danaan__external_resource_add
metadata:
  version: "1.2.0"
---

# Danaan Cloud Resource

## Response language contract

The language of this document is instruction-only and must never determine the language of an Agent reply.
Use the runtime `response_language` for every user-facing natural-language response, including questions,
validation explanations, and the final request-confirmation Markdown. UI-only values supplied to
`request_user_form` (`title` and every field `label`) must always be English. Keep Tool names, JSON keys,
enum values, IDs, URLs, code, and product names verbatim.

## Supported resource catalog (authoritative)

This table is the single source of truth for the exact `resourceName` values this Skill may submit.

| `resourceName` | Supported operation | Template lookup |
| --- | --- | --- |
| `Cloud Storage` | `CREATE` | `danaan_get_resource_template(resource_name="Cloud Storage")` |
| `BigQuery` | `CREATE` | `danaan_get_resource_template(resource_name="BigQuery")` |
| `Cloud SQL` | `CREATE` | `danaan_get_resource_template(resource_name="Cloud SQL")` |

Use this Skill for a Danaan request for a catalog resource. Change, delete, or a resource not in this catalog
is out of scope and must not be submitted. Do not claim support for a catalog resource if its template lookup
returns `found=false`; explain that its Danaan template is not available.

### Adding a new resource type

To add a resource, update this catalog with the exact Danaan `resourceName`, ensure the Danaan template table
contains a valid single-key `resourceContent` template, add any resource-specific restrictions below, and add a
test for template lookup and request construction. The template Tool is already generic: it queries by
`resourceName`, so no Tool or repository branching is needed for a new catalog entry.

## 不可违反的规则

1. 这是创建流程，`operationType` **必须且只能**为字符串 `CREATE`。不要询问用户填写它，不接受、
   不转换、也不向 MCP 传递 `UPDATE`、`DELETE`、`MODIFY` 或任何其他值。
2. 不猜测任何用户参数。用户本轮明确提供的值覆盖会话旧值和长期记忆值。
3. `cloudResourceName` 必须由用户明确提供或确认；不可根据模板名、`resourceName`、应用名、环境名或
   其他字段自行生成。
4. `resourceName` 必须是上方 catalog 中的一个精确值，大小写、空格和拼写必须完全匹配。不得翻译、缩写、
   自动纠正或传递 catalog 以外的值。
5. 只能在 Danaan 基础资料与资源申请字段都齐全后读取模板和构造申请 body。
6. `danaan__external_resource_add` 有副作用，必须等待用户 `approve`。用户 `reject` 时不得调用、不得重试。
7. 不记录或长期保存完整模板、数据库配置、KMS Key、IAM 列表、凭据或完整申请 body。
8. `creator`、`creatorName`、`creatorEmail` 是系统受控字段，禁止向用户展示、询问或允许修改。

## Danaan 基础资料与长期记忆

基础资料只有以下五项：

```text
resourceOnboardRegion
applicationName
eimId
envName
useCaseShortName
```

1. 用户发起 Danaan 申请时，先调用
   `get_skill_memory(key="danaan-cloud-resource:base-context")`。该 Tool 仅会读取当前 staff 的精确 key；其
   `found=true` 且 `value` 中五项均存在时，`value` 才是唯一可用的 Danaan 默认资料来源。
2. **仅当五项均存在时，不得调用 `request_user_form`，也不得触发任何表单 SSE 事件。** 先以 runtime
   `response_language` 输出普通的自然语言确认消息，说明资料来自之前已保存的记录，并展示以下 Markdown
   表格（字段名保持 English，值使用 Tool 返回 `value` 中的实际值）：

   ```markdown
   ## 基础资料已确认（沿用已保存资料）

   | 字段 | 值 |
   | --- | --- |
   | Resource Onboarding Region | <resourceOnboardRegion> |
   | Application Name | <applicationName> |
   | EIM ID | <eimId> |
   | Environment | <envName> |
   | Use Case | <useCaseShortName> |

   是否使用以上基础资料？回复“是”、“使用”或“确认”以沿用；回复“否”、“重新选择”或“修改”以重新填写。
   ```

   在 English response language 下，用等价 English 标题、说明和确认问题；不得因本 Skill 的中文说明而改变
   回复语言。这是一个普通 Agent 回复，必须等待用户的下一条自然语言消息，不能静默使用已保存资料。
3. 用户明确肯定（例如“是”、“使用”、“确认”或对应英文）后，直接将已保存的五项用于本次申请并进入后续
   资源申请字段收集；**不得显示基础资料表单**。用户明确否定、要求重新选择或要求修改基础资料后，才调用
   `request_user_form` 展示完整基础资料表单，并将已保存的值作为 `prefilled_values` 传入，供用户修改。
4. 用户本轮明确给出的新值覆盖已保存值。用户提交 `danaan-base-context` 表单即确认这些基础资料；后端只保存
   这五项为长期记忆，不能由 Agent 保存其他字段。

### 基础资料表单

仅在基础资料缺失，或用户已明确拒绝沿用 / 要求重新选择或修改时，调用 `request_user_form`，并固定使用：

```text
form_name = "danaan-base-context"
title = "Danaan Base Information"
```

已有长期记忆并因用户明确拒绝而打开表单时，必须传入刚才 Tool 返回的 `value`：

```text
prefilled_values = <get_skill_memory.value>
```

字段顺序与约束如下：

```json
[
  {
    "name": "resourceOnboardRegion",
    "label": "Resource Onboarding Region",
    "type": "select",
    "required": true,
    "options": ["ASP", "EUR"]
  },
  {"name": "applicationName", "label": "Application Name", "type": "text", "required": true},
  {"name": "eimId", "label": "EIM ID", "type": "text", "required": true},
  {
    "name": "envName",
    "label": "Environment",
    "type": "select",
    "required": true,
    "options": ["dev", "prod"]
  },
  {"name": "useCaseShortName", "label": "Use Case Short Name", "type": "text", "required": true}
]
```

表单的结构化响应是字段值的唯一可信来源。表单打开后，不要求用户再次用自然语言粘贴相同内容。

## Supported resource creation flow

### 1. 收集申请字段

完成基础资料确认后，收集以下字段：

```text
resourceName
cloudResourceName
justification
```

- `operationType` 直接固定为 `CREATE`，不是待收集字段。
- `resourceName` 必须由用户明确选择，且精确匹配上方 Supported resource catalog。若用户使用其他值、缩写
  或名称不清楚，展示 catalog 中的资源选项要求重新选择；不得调用模板 Tool。
- `cloudResourceName` 或 `justification` 不明确时，自然语言追问；不可按示例、模板或历史值猜测。
- 用户说“创建某资源，名称为 xxx”时，`xxx` 只有在用户明确说明其对应字段后才能使用；名称含义不明确时必须追问。

### 2. 获取模板

仅在 `resourceName` 与 `cloudResourceName` 均已确认后调用：

```text
danaan_get_resource_template(resource_name=resourceName)
```

该 Tool 返回当前 `resourceContent` 模板。若 `found` 为 false、模板为空、不是 JSON object，或模板有
零个/多个顶层资源名键，停止流程并说明模板不可用于安全创建；不得自行补全或修复模板。

### 3. 严格构造 `resourceContent`

模板的顶层必须恰好只有一个资源名键。**只替换这个顶层键**为已确认的 `cloudResourceName`；其对应 value
必须作为完整对象原样复制。禁止修改、删除、补充或重新命名 value 内的任何字段。不同资源的模板字段由
Danaan 模板表定义；Skill 不得把 Cloud SQL、Cloud Storage 或 BigQuery 的字段规则套用到其他资源。

例如，用户确认：

```text
cloudResourceName = "hsx-kkll-lll"
```

且 Tool 返回模板（本例使用 Cloud SQL，替换规则对所有 catalog resource 相同）：

```json
{
  "hslxx-projectid-cloudsql-dev-infra-061111": {
    "private_network": "hslxx-default-network",
    "db_version": "POSTGRES_18",
    "availability_type": "REGIONAL",
    "database_flags": [],
    "zone": "asia-east2-b",
    "tier": "db-custom-1-3840",
    "disk_autoresize": true,
    "disk_size": 10,
    "disk_type": "PD_SSD",
    "kms_key": "sqlSharedKey",
    "iam_user_emails": [],
    "backup_policy": {
      "backup_enabled": true,
      "backup_start_time": "00:00"
    }
  }
}
```

则传给 Danaan 的 `resourceContent` **必须精确构造为**：

```json
{
  "hsx-kkll-lll": {
    "private_network": "hslxx-default-network",
    "db_version": "POSTGRES_18",
    "availability_type": "REGIONAL",
    "database_flags": [],
    "zone": "asia-east2-b",
    "tier": "db-custom-1-3840",
    "disk_autoresize": true,
    "disk_size": 10,
    "disk_type": "PD_SSD",
    "kms_key": "sqlSharedKey",
    "iam_user_emails": [],
    "backup_policy": {
      "backup_enabled": true,
      "backup_start_time": "00:00"
    }
  }
}
```

模板旧键 `hslxx-projectid-cloudsql-dev-infra-061111` 不得出现在最终 `resourceContent` 中。注意：这不是
字符串全局替换；若内部字段值恰好含有旧资源名，也必须保持原样。

### 4. 组装并确认申请

组装下列结构化 body：

```json
{
  "operationType": "CREATE",
  "applicationName": "<confirmed value>",
  "eimId": "<confirmed value>",
  "envName": "<confirmed value>",
  "useCaseShortName": "<confirmed value>",
  "resourceOnboardRegion": "<confirmed value>",
  "resourceContent": {"<cloudResourceName>": "<unaltered template value>"},
  "creator": "<staff_id>",
  "creatorName": "",
  "creatorEmail": "",
  "resourceName": "<confirmed value>",
  "cloudResourceName": "<confirmed value>",
  "justification": "<confirmed value>"
}
```

`creator` 必须且只能使用调用上下文提供的 `staff_id`，不能使用用户消息、表单、长期记忆或模型推断值。
`creatorName` 与 `creatorEmail` 必须始终传空字符串 `""`，不能省略、填充、修改或从其他来源读取。这三个字段
均为内部系统字段：不得放入任何前端表单、SSE 表单字段、自然语言追问、确认弹窗或最终用户摘要。

调用最终 MCP Tool 前，必须按当前 `response_language` 向用户展示待提交内容。所有 `<>` 均替换为本次已经确认的
实际值；不得展示 `creator`、`creatorName` 或 `creatorEmail`。英文回复必须使用下面的英文模板；中文回复使用
语义完全相同的中文 Markdown 模板。

````markdown
## Danaan Cloud Resource Request Confirmation

Please review the request below. Approval will create a resource request ticket.

| Field | Value |
| --- | --- |
| Operation Type | `CREATE` |
| Resource Type | `<resourceName>` |
| Cloud Resource Name | `<cloudResourceName>` |
| Application Name | `<applicationName>` |
| EIM ID | `<eimId>` |
| Environment | `<envName>` |
| Use Case | `<useCaseShortName>` |
| Resource Onboarding Region | `<resourceOnboardRegion>` |
| Justification | `<justification>` |

### resourceContent

```json
<resourceContent>
```

Approval will submit this request. Cancellation will not create a ticket.
````

展示后调用：

```text
danaan__external_resource_add(body=<assembled request>)
```

该 Tool 会触发现有确认事件；只有用户 `approve` 后才会真正执行。执行完成后，仅返回安全的 Ticket ID、
状态和 MCP 返回摘要，不回显完整 `resourceContent`。
