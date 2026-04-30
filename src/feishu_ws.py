# -*- coding: utf-8 -*-
"""飞书 WebSocket 长链接：接收 @机器人 消息，CRUD 用户映射"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone

try:
    from websocket import WebSocketApp, WebSocketConnectionClosedException
except ImportError:
    WebSocketApp = None  # type: ignore[assignment]

from src.config import Config
from src.feishu_api import send_text_message
from src.feishu_credential import get_tenant_access_token
from src.user_map import UserMap

log = logging.getLogger(__name__)

WS_URL = "wss://open.feishu.cn/open-apis/event/v1"
RECONNECT_INTERVAL = 60  # seconds
TOKEN_REFRESH_SECONDS = 7000  # refresh token before expiry (~2h)

_CLEAN_EXIT = False

# ── 命令名常量 ──────────────────────────────────────────

CMD_BIND = "!bind"
CMD_UNBIND = "!unbind"
CMD_LIST = "!list"
CMD_WHOAMI = "!whoami"
CMD_WHOIS = "!whois"
CMD_HELP = "!help"

HELP_TEXT = (
    "UserMap 命令：\n"
    f"  `{CMD_BIND} <GitHub 用户名>`   — 将自己绑定到 GitHub 用户\n"
    f"  `{CMD_BIND} <GitHub 用户名> @某人` — 将 @某人 绑定到 GitHub 用户\n"
    f"  `{CMD_UNBIND} <GitHub 用户名>` — 删除绑定\n"
    f"  `{CMD_LIST}` — 列出所有映射\n"
    f"  `{CMD_WHOAMI}` — 查看自己的绑定\n"
    f"  `{CMD_WHOIS} @某人` — 查看某人的绑定\n"
    f"  `{CMD_HELP}` — 帮助"
)


# ── 消息解析 ────────────────────────────────────────────


def _parse_msg_content(event: dict) -> tuple[str, str, list[dict]]:
    """返回 (text, chat_id, mentions)。mentions 是 [{"key":"@xx","open_id":"ou_xxx"}]。"""
    msg = event.get("message") or {}
    chat_id = msg.get("chat_id", "")
    content_str = msg.get("content", "{}")
    try:
        content = json.loads(content_str)
    except (json.JSONDecodeError, TypeError):
        return "", chat_id, []
    text = content.get("text", "").strip()
    mentions_raw = msg.get("mentions") or []
    mentions: list[dict] = []
    for m in mentions_raw:
        mentions.append({
            "key": m.get("key", ""),
            "open_id": (m.get("id") or {}).get("open_id", ""),
        })
    return text, chat_id, mentions


def _sender_open_id(event: dict) -> str:
    return (event.get("sender") or {}).get("sender_id", {}).get("open_id", "")


# ── 命令处理 ────────────────────────────────────────────


def _dispatch(
    text: str,
    chat_id: str,
    sender_open_id: str,
    mentions: list[dict],
    user_map: UserMap,
    cfg: Config,
    token_file: str,
) -> None:
    token = get_tenant_access_token(cfg.app_id, cfg.app_secret, token_file)
    if not token:
        log.warning("No token for reply")
        return

    parts = text.split()
    if not parts:
        return
    cmd = parts[0].lower()
    args = parts[1:]

    # !bind <gh_name> [@someone] — 如果消息里 @了人则绑定被 @者，否则绑定发送者
    if cmd == CMD_BIND:
        if not args:
            send_text_message(token, chat_id, "用法: `!bind <GitHub 用户名> [@某人]`", ctx="cmd")
            return
        gh_name = args[0]
        if mentions:
            target_open_id = mentions[0]["open_id"]
            target_name = mentions[0]["key"]
            user_map.bind(gh_name, target_open_id)
            send_text_message(token, chat_id, f"已将 {target_name} 绑定到 GitHub 用户 `{gh_name}`", ctx="cmd")
        else:
            user_map.bind(gh_name, sender_open_id)
            send_text_message(token, chat_id, f"已将你绑定到 GitHub 用户 `{gh_name}`", ctx="cmd")

    # !unbind <gh_name>
    elif cmd == CMD_UNBIND:
        if not args:
            send_text_message(token, chat_id, "用法: `!unbind <GitHub 用户名>`", ctx="cmd")
            return
        gh_name = args[0]
        ok = user_map.unbind(gh_name)
        if ok:
            send_text_message(token, chat_id, f"已删除 `{gh_name}` 的绑定", ctx="cmd")
        else:
            send_text_message(token, chat_id, f"未找到 `{gh_name}` 的绑定", ctx="cmd")

    # !list
    elif cmd == CMD_LIST:
        all_items = user_map.list_all()
        if not all_items:
            send_text_message(token, chat_id, "当前无绑定", ctx="cmd")
            return
        lines = ["当前绑定："]
        for gh, oid in all_items.items():
            lines.append(f"  `{gh}` → `{oid}`")
        send_text_message(token, chat_id, "\n".join(lines), ctx="cmd")

    # !whoami
    elif cmd == CMD_WHOAMI:
        gh = user_map.find_by_open_id(sender_open_id)
        if gh:
            send_text_message(token, chat_id, f"你是 `{gh}`", ctx="cmd")
        else:
            send_text_message(token, chat_id, "你尚未绑定 GitHub 用户，使用 `!bind <用户名>` 绑定", ctx="cmd")

    # !whois @某人
    elif cmd == CMD_WHOIS:
        if not mentions:
            send_text_message(token, chat_id, "用法: `!whois @某人`", ctx="cmd")
            return
        target_open_id = mentions[0]["open_id"]
        gh = user_map.find_by_open_id(target_open_id)
        if gh:
            send_text_message(token, chat_id, f"{mentions[0]['key']} 是 `{gh}`", ctx="cmd")
        else:
            send_text_message(token, chat_id, f"{mentions[0]['key']} 尚未绑定", ctx="cmd")

    # !help
    elif cmd == CMD_HELP:
        send_text_message(token, chat_id, HELP_TEXT, ctx="cmd")

    else:
        log.debug("Unknown command: %s", cmd)


# ── WebSocket 事件处理 ───────────────────────────────────


def _handle_event(data: dict, user_map: UserMap, cfg: Config, token_file: str) -> None:
    header = data.get("header") or {}
    event_type = header.get("event_type", "")
    event = data.get("event") or {}

    if event_type == "im.message.receive_v1":
        text, chat_id, mentions = _parse_msg_content(event)
        sender_oid = _sender_open_id(event)
        if text and chat_id:
            log.info("WS message: chat=%s sender=%s text=%s", chat_id[:12], sender_oid[:12], text[:60])
            _dispatch(text, chat_id, sender_oid, mentions, user_map, cfg, token_file)
    else:
        log.debug("WS event ignored: %s", event_type)


def _on_message(ws, message: str, user_map: UserMap, cfg: Config, token_file: str) -> None:
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        log.warning("WS non-JSON message")
        return

    # 应用层 ping
    if isinstance(data, dict) and data.get("type") == "ping":
        try:
            ws.send(json.dumps({"type": "pong"}))
        except Exception as e:
            log.debug("WS pong send failed: %s", e)
        return

    _handle_event(data, user_map, cfg, token_file)


def start_ws_client(cfg: Config, token_file: str, user_map: UserMap) -> None:
    """阻塞运行 WebSocket 客户端，掉线自动重连。应在独立线程中调用。"""
    if WebSocketApp is None:
        log.error("websocket-client not installed, run: pip install websocket-client")
        return

    global _CLEAN_EXIT
    _token_refreshed_at = 0.0

    def on_open(ws):
        nonlocal _token_refreshed_at
        token = get_tenant_access_token(cfg.app_id, cfg.app_secret, token_file)
        if not token:
            log.error("WS cannot get token, closing")
            ws.close()
            return
        auth_msg = json.dumps({"type": "token", "token": token})
        ws.send(auth_msg)
        _token_refreshed_at = time.monotonic()
        log.info("WS connected and authenticated")

    def on_message(ws, message):
        _on_message(ws, message, user_map, cfg, token_file)

    def on_error(ws, error):
        log.error("WS error: %s", error)

    def on_close(ws, close_status_code, close_msg):
        log.warning("WS closed code=%s msg=%s", close_status_code, close_msg)

    while not _CLEAN_EXIT:
        ws = WebSocketApp(WS_URL, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
        try:
            ws.run_forever()
        except Exception as e:
            log.error("WS run_forever exception: %s", e)
        if _CLEAN_EXIT:
            break
        log.info("WS disconnected, reconnecting in %ds...", RECONNECT_INTERVAL)
        time.sleep(RECONNECT_INTERVAL)


def stop_ws_client() -> None:
    global _CLEAN_EXIT
    _CLEAN_EXIT = True
