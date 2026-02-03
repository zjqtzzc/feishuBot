# -*- coding: utf-8 -*-
"""配置读取：从多路径查找 config.json，未找到或解析失败则抛错"""

import json
import os
from dataclasses import dataclass, fields


@dataclass
class Config:
    github_webhook_port: int
    github_token: str
    app_id: str
    app_secret: str
    chat_id: str


DEFAULT_PATHS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
]


def load_config(paths: list[str] = DEFAULT_PATHS) -> Config:
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                raise RuntimeError(f"读取配置失败 {p}: {e}") from e
            for f in fields(Config):
                if f.name not in raw:
                    raise RuntimeError(f"配置缺少必填项: {f.name}")
            return Config(
                github_webhook_port=int(raw["github_webhook_port"]),
                github_token=raw["github_token"],
                app_id=raw["app_id"],
                app_secret=raw["app_secret"],
                chat_id=raw["chat_id"],
            )
    raise FileNotFoundError(f"未找到配置文件，已尝试: {paths}")
