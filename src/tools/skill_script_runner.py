"""Confirmation-gated execution of reviewed Skill scripts in ephemeral GKE sandboxes."""
import asyncio
import json
import uuid
from pathlib import PurePosixPath
from typing import Any

from google.cloud import storage
from langchain_core.runnables.config import ensure_config
from langchain_core.tools import StructuredTool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config.sandbox_settings import GkeAgentSandboxSettings
from database.models.agent.script_artifact import ScriptArtifact
from repositories.script_artifact_repository import ScriptArtifactRepository
from skills.script_catalog import ScriptCatalog

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class GkeSkillScriptRunner:
    def __init__(self, settings: GkeAgentSandboxSettings, catalog: ScriptCatalog, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._settings, self._catalog, self._session_factory = settings, catalog, session_factory

    def tool(self) -> StructuredTool:
        async def run_skill_script(skill_id: str, script_name: str, arguments: dict[str, object]) -> dict[str, object]:
            entry = self._catalog.resolve(skill_id, script_name)
            config = ensure_config(); thread_id = (config.get("configurable") or {}).get("thread_id")
            if not isinstance(thread_id, str): raise RuntimeError("run_skill_script requires a conversation thread")
            return await self._run(uuid.UUID(thread_id), entry.runtime_path, skill_id, script_name, arguments)
        return StructuredTool.from_function(coroutine=run_skill_script, name="run_skill_script", description="Run an enabled, reviewed Skill Python script in an isolated GKE sandbox. Use only the documented Skill script and JSON arguments.")

    async def _run(self, conversation_id: uuid.UUID, runtime_path: str, skill_id: str, script_name: str, arguments: dict[str, object]) -> dict[str, object]:
        from k8s_agent_sandbox import SandboxClient
        from k8s_agent_sandbox.models import SandboxDirectConnectionConfig, SandboxLocalTunnelConnectionConfig
        execution_id = str(uuid.uuid4())
        if self._settings.connection_mode == "tunnel":
            connection = SandboxLocalTunnelConnectionConfig(server_port=self._settings.runtime_port, router_namespace=self._settings.router_namespace)
        else:
            connection = SandboxDirectConnectionConfig(api_url=self._settings.router_url, server_port=self._settings.runtime_port)
        client = await asyncio.to_thread(SandboxClient, connection_config=connection)
        sandbox = None
        try:
            sandbox = await asyncio.to_thread(client.create_sandbox, self._settings.warm_pool_name, self._settings.namespace, self._settings.startup_timeout_seconds, None, shutdown_after_seconds=self._settings.command_timeout_seconds + 60)
            if self._settings.router_auth_token is not None:
                sandbox.connector.session.headers["Authorization"] = f"Bearer {self._settings.router_auth_token.get_secret_value()}"
            job_dir = f"/workspace/jobs/{execution_id}"
            await asyncio.to_thread(sandbox.files.write, f"{job_dir}/input.json", json.dumps(arguments).encode(), self._settings.command_timeout_seconds)
            command = f"mkdir -p {job_dir}/output && python {runtime_path} --input {job_dir}/input.json --output-dir {job_dir}/output"
            result = await asyncio.to_thread(sandbox.commands.run, command, self._settings.command_timeout_seconds)
            artifacts = await self._collect_artifacts(sandbox, conversation_id, skill_id, script_name, job_dir)
            return {"exit_code": result.exit_code, "stdout": result.stdout, "stderr": result.stderr, "artifacts": artifacts}
        finally:
            if sandbox is not None: await asyncio.to_thread(sandbox.terminate)

    async def _collect_artifacts(self, sandbox: Any, conversation_id: uuid.UUID, skill_id: str, script_name: str, job_dir: str) -> list[dict[str, object]]:
        if not self._settings.artifact_bucket: return []
        files = await asyncio.to_thread(sandbox.files.list, f"{job_dir}/output", self._settings.command_timeout_seconds)
        results: list[dict[str, object]] = []
        for item in files:
            filename = PurePosixPath(item.name).name
            if item.type != "file" or not filename.endswith(".xlsx") or item.size > 20 * 1024 * 1024: continue
            content = await asyncio.to_thread(sandbox.files.read, f"{job_dir}/output/{filename}", self._settings.command_timeout_seconds)
            object_key = f"{self._settings.artifact_prefix}/{conversation_id}/{uuid.uuid4()}/{filename}"
            await asyncio.to_thread(self._upload, object_key, content)
            async with self._session_factory() as session:
                artifact = await ScriptArtifactRepository(session).create(ScriptArtifact(conversation_id=conversation_id, skill_id=skill_id, script_name=script_name, object_key=object_key, filename=filename, content_type=_XLSX_MIME, size_bytes=len(content)))
            results.append({"artifact_id": str(artifact.id), "filename": filename, "size_bytes": len(content)})
        return results

    def _upload(self, object_key: str, content: bytes) -> None:
        bucket = storage.Client().bucket(self._settings.artifact_bucket)
        bucket.blob(object_key).upload_from_string(content, content_type=_XLSX_MIME)
