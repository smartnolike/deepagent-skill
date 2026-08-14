"""YAML-only settings loader."""

# 只允许 AGENT_ENV 选择 YAML 文件；业务配置均来自 YAML 或其显式环境变量引用。

import os
import re
import logging
from pathlib import Path
from typing import Any

import yaml

from .settings import Settings

logger = logging.getLogger(__name__)

_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand_environment(value: Any) -> Any:
    """Recursively resolve ${NAME} and ${NAME:-default} inside YAML values."""
    if isinstance(value, dict):
        return {key: _expand_environment(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_environment(item) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        name, default = match.groups()
        configured = os.getenv(name)
        if configured is not None:
            return configured
        if default is not None:
            return default
        raise RuntimeError(f"Missing environment variable referenced by YAML: {name}")

    return _ENV_REFERENCE.sub(replace, value)


def load_settings(config_dir: Path | None = None) -> Settings:
    """Load ``config/{AGENT_ENV}.yaml``; AGENT_ENV only selects the file."""
    app_env = os.getenv("AGENT_ENV", "local")
    base_dir = config_dir or Path(__file__).resolve().parents[2] / "config"
    config_file = base_dir / f"{app_env}.yaml"
    if not config_file.is_file():
        raise RuntimeError(f"Missing runtime configuration file: {config_file}")
    data = _expand_environment(yaml.safe_load(config_file.read_text(encoding="utf-8")) or {})
    logger.info("settings_loaded app_env=%s config_file=%s", app_env, config_file.name)
    return Settings.model_validate(data)
