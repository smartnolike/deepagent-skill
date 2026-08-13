# DeepAgent Platform MVP

Copy a YAML template and provide a local static API token:

```bash
cp config/local.example.yaml config/local.yaml
export APP_ENV=local
```

YAML 可以引用启动环境变量，例如 `api_auth_token: ${API_AUTH_TOKEN}` 或 MCP header
`Authorization: Bearer ${TICKETING_MCP_TOKEN}`。未提供且没有默认值的引用会使启动失败。

应用内自定义 Tool 位于 `src/tools/`。如启用 `tools.external_status_url`，服务会复用专用的
`httpx.AsyncClient` 并强制以 `build/root.cer` 校验外部 API TLS 证书。该证书当前必须由部署环境
提供有效 PEM/CA 内容；空文件或缺失文件会使启用外部 Tool 的应用启动失败。

Start PostgreSQL, migrate, and run the API:

```bash
docker run --name deepagent-postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=deepagent -p 5432:5432 postgres:16
alembic upgrade head
uvicorn src.main:app --reload
```

All `/api/*` calls require `Authorization: Bearer <api_auth_token>`. The default local configuration
uses the deterministic mock ticketing harness; it supports a bucket request end to end. To enable the
single-root DeepAgent harness, set `agent.model` (for example `openai:gpt-5.5`) and add its provider
credential through a YAML environment-variable reference. Skills are enabled through `agent.enabled_skills`.
