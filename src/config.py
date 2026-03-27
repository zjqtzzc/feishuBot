# -*- coding: utf-8 -*-
"""配置：从项目根目录的 config.json 加载"""

import json
import os
from dataclasses import dataclass, fields

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_PATHS = [os.path.join(_ROOT, "config.json")]


@dataclass
class Config:
    github_webhook_port: int
    github_token: str
    app_id: str
    app_secret: str
    chat_id: str
    github_webhook_secret: str = ""


def load_config(paths: list[str] | None = None) -> Config:
    paths = paths or DEFAULT_PATHS
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                raise RuntimeError(f"读取配置失败 {p}: {e}") from e
            for field in fields(Config):
                if field.name == "github_webhook_secret":
                    continue
                if field.name not in raw:
                    raise RuntimeError(f"配置缺少必填项: {field.name}")
            return Config(
                github_webhook_port=int(raw["github_webhook_port"]),
                github_token=raw["github_token"],
                app_id=raw["app_id"],
                app_secret=raw["app_secret"],
                chat_id=raw["chat_id"],
                github_webhook_secret=str(raw.get("github_webhook_secret", "")),
            )
    raise FileNotFoundError(f"未找到配置文件，已尝试: {paths}")


def project_root() -> str:
    return _ROOT
