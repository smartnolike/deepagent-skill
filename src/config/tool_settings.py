"""自定义应用 Tool 的 YAML 配置模型。"""

# 外部 API 地址必须来自受控 YAML，不能由模型自由提供 URL，避免 SSRF 风险。

from pathlib import Path

from pydantic import BaseModel, ConfigDict, HttpUrl, field_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ToolSettings(BaseModel):
    """应用自定义 Tool 的外部 API 与 CA 证书配置。"""

    model_config = ConfigDict(validate_default=True)

    danaan_json_schema_url: HttpUrl | None = None
    root_ca_path: Path = Path("build/root.cer")

    @field_validator("root_ca_path", mode="after")
    @classmethod
    def resolve_root_ca_path(cls, value: Path) -> Path:
        """将相对证书路径固定解析到项目根目录，而不是启动工作目录。"""
        if value.is_absolute():
            return value
        return (PROJECT_ROOT / value).resolve()
