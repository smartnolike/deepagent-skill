"""Optional Langfuse observability tests."""

import uuid

from pydantic import SecretStr

from agent.harness_service import DeepAgentHarnessService
from config.langfuse_settings import LangfuseSettings
from core.runtime_secrets import RuntimeSecrets
from observability import langfuse_observability


class FakeObservability:
    """Return a marker callback without initializing the Langfuse SDK."""

    def create_callback(self) -> str:
        return "langfuse-callback"


def test_observability_masks_credential_like_fields() -> None:
    masked = langfuse_observability._mask_sensitive_data(
        data={"password": "value", "nested": {"access_token": "value"}, "api_key": "value", "safe": "value"}
    )

    assert masked == {
        "password": "***",
        "nested": {"access_token": "***"},
        "api_key": "***",
        "safe": "value",
    }


def test_harness_adds_langfuse_callback_and_trace_metadata() -> None:
    harness = DeepAgentHarnessService(object(), observability=FakeObservability())
    conversation_id = uuid.uuid4()
    agent_run_id = uuid.uuid4()

    config = harness._graph_config(conversation_id, "staff-1", agent_run_id)

    assert config["callbacks"] == ["langfuse-callback"]
    assert config["metadata"] == {
        "langfuse_session_id": str(conversation_id),
        "langfuse_user_id": "staff-1",
        "conversation_id": str(conversation_id),
        "agent_run_id": str(agent_run_id),
    }


def test_observability_initializes_sdk_with_application_environment_and_release(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def langfuse_probe(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(langfuse_observability, "Langfuse", langfuse_probe)
    langfuse_observability.LangfuseObservability(
        LangfuseSettings(enabled=True, public_key="pk", secret_key="sk", release="release-1"),
        "local",
        RuntimeSecrets(langfuse_public_key=SecretStr("pk"), langfuse_secret_key=SecretStr("sk")),
    )

    assert captured["environment"] == "local"
    assert captured["release"] == "release-1"
    assert captured["base_url"] == "https://cloud.langfuse.com"


def test_callback_uses_only_the_cross_version_public_key_argument(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def callback_probe(**kwargs: object) -> str:
        captured.update(kwargs)
        return "callback"

    monkeypatch.setattr(langfuse_observability, "CallbackHandler", callback_probe)
    observability = langfuse_observability.LangfuseObservability.__new__(langfuse_observability.LangfuseObservability)
    observability._public_key = "pk"

    assert observability.create_callback() == "callback"
    assert captured == {"public_key": "pk"}
