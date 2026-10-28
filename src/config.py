# -*- coding: utf-8 -*-
"""配置：从数据目录的 config.json 加载。

数据目录（config.json、卡片记录、用户映射）默认是项目根目录，可用环境变量 BOT_DATA_DIR 指定。
"""

import json
import os
from dataclasses import MISSING, dataclass, fields

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.abspath(os.environ.get("BOT_DATA_DIR") or _ROOT)

CONFIG_PATH = os.path.join(_DATA_DIR, "config.json")


@dataclass
class Config:
    github_webhook_port: int
    github_token: str
    app_id: str
    app_secret: str
    chat_id: str
    github_webhook_secret: str = ""


def load_config() -> Config:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise RuntimeError(f"读取配置失败 {CONFIG_PATH}: {e}") from e
    missing = [f.name for f in fields(Config) if f.default is MISSING and f.name not in raw]
    if missing:
        raise RuntimeError(f"配置缺少必填项: {', '.join(missing)}")
    return Config(**{f.name: raw[f.name] for f in fields(Config) if f.name in raw})


def data_dir() -> str:
    return _DATA_DIR
