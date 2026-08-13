"""自定义应用 Tool 的 YAML 配置模型。"""

# 外部 API 地址必须来自受控 YAML，不能由模型自由提供 URL，避免 SSRF 风险。

from pathlib import Path

from pydantic import BaseModel, HttpUrl


class ToolSettings(BaseModel):
    """应用自定义 Tool 的外部 API 与 CA 证书配置。"""

    external_status_url: HttpUrl | None = None
    root_ca_path: Path = Path("build/root.cer")
