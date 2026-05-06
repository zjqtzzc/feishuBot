# -*- coding: utf-8 -*-
"""飞书 WebSocket 长链接：使用 lark-oapi SDK 接收 @机器人 消息"""

from __future__ import annotations

import json
import logging
import re
import threading

from lark_oapi.event.custom import CustomizedEvent
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
from lark_oapi.ws.client import Client as WsClient

from src.config import Config
from src.feishu_api import send_interactive_card, send_text_message
from src.feishu_credential import get_tenant_access_token
from src.user_map import UserMap

log = logging.getLogger(__name__)

# ── 命令名常量 ──────────────────────────────────────────

CMD_BIND = "!bind"
CMD_UNBIND = "!unbind"
CMD_LIST = "!list"
CMD_AT = "!at"
CMD_HELP = "!help"

HELP_CARD = {
    "header": {"template": "blue", "title": {"content": "UserMap 命令", "tag": "plain_text"}},
    "elements": [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**{CMD_BIND}** `<用户名>`\n"
                    f"将自己绑定到 GitHub 用户\n\n"
                    f"**{CMD_BIND}** `<用户名>` @某人\n"
                    f"将 @某人 绑定到 GitHub 用户\n\n"
                    f"**{CMD_UNBIND}** `<用户名>`\n"
                    f"删除绑定\n\n"
                    f"**{CMD_LIST}**\n"
                    f"列出所有映射\n\n"
                    f"**{CMD_AT}** `<用户名>`\n"
                    f"测试 @mention 效果"
                ),
            },
        },
    ],
}


# 群聊中不应响应的 @ 前缀
_SKIP_MENTIONS = frozenset({"@所有人"})

# ── 消息解析 ────────────────────────────────────────────


def _strip_bot_mention(text: str) -> tuple[str, str]:
    """去掉消息开头的 @机器人 前缀，返回 (清洗后文本, 被去掉的 bot_key)。"""
    m = re.match(r"^@(\S+)\s*", text)
    if m:
        return text[m.end():].strip(), f"@{m.group(1)}"
    return text, ""


def _parse_msg_content(event_data: dict) -> tuple[str, str, bool, list[dict]]:
    """返回 (text, chat_id, is_group, mentions)。群聊需 @机器人 才响应。"""
    msg = event_data.get("message") or {}
    chat_id = msg.get("chat_id", "")
    chat_type = msg.get("chat_type", "")
    is_group = chat_type == "group"
    content_str = msg.get("content", "{}")
    try:
        content = json.loads(content_str)
    except (json.JSONDecodeError, TypeError):
        return "", chat_id, is_group, []
    raw_text = content.get("text", "").strip()
    mentions_raw = msg.get("mentions") or []
    # 群聊必须 @机器人（而非 @所有人）才响应；单聊随便
    if is_group:
        if not raw_text.startswith("@"):
            return "", chat_id, is_group, []
        text, bot_key = _strip_bot_mention(raw_text)
        if bot_key in _SKIP_MENTIONS:
            return "", chat_id, is_group, []
    else:
        text, bot_key = raw_text, ""
    mentions: list[dict] = []
    for m in mentions_raw:
        key = m.get("key", "")
        if bot_key and key == bot_key:
            continue  # 过滤掉机器人自身
        mentions.append({
            "key": key,
            "name": m.get("name", ""),
            "open_id": (m.get("id") or {}).get("open_id", ""),
        })
    return text, chat_id, is_group, mentions


def _sender_open_id(event_data: dict) -> str:
    return (event_data.get("sender") or {}).get("sender_id", {}).get("open_id", "")


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

    if cmd == CMD_BIND:
        if not args:
            send_text_message(token, chat_id, "用法: `!bind <GitHub 用户名> [@某人]`", ctx="cmd")
            return
        gh_name = args[0]
        if mentions:
            target_open_id = mentions[0]["open_id"]
            target_name = mentions[0].get("name") or mentions[0]["key"]
            user_map.bind(gh_name, target_open_id)
            send_text_message(token, chat_id, f"已将 {target_name} 绑定到 GitHub 用户 `{gh_name}`", ctx="cmd")
        else:
            user_map.bind(gh_name, sender_open_id)
            send_text_message(token, chat_id, f"已将你绑定到 GitHub 用户 `{gh_name}`", ctx="cmd")

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

    elif cmd == CMD_LIST:
        all_items = user_map.list_all()
        if not all_items:
            send_text_message(token, chat_id, "当前无绑定", ctx="cmd")
            return
        lines = ["当前绑定："]
        for gh, oid in all_items.items():
            lines.append(f"  `{gh}` → `{oid}`")
        send_text_message(token, chat_id, "\n".join(lines), ctx="cmd")

    elif cmd == CMD_AT:
        if not args:
            send_text_message(token, chat_id, "用法: `!at <GitHub 用户名>`", ctx="cmd")
            return
        gh_name = args[0]
        fid = user_map.find_by_github(gh_name)
        if fid:
            card = {
                "header": {
                    "template": "blue",
                    "title": {"content": "@mention 测试", "tag": "plain_text"},
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"<at id={fid}>{gh_name}</at>",
                        },
                    }
                ],
            }
            send_interactive_card(token, chat_id, card, ctx="cmd")
        else:
            send_text_message(token, chat_id, f"未找到 `{gh_name}` 的绑定", ctx="cmd")

    elif cmd == CMD_HELP:
        send_interactive_card(token, chat_id, HELP_CARD, ctx="cmd")

    else:
        log.debug("Unknown command: %s", cmd)
        send_text_message(token, chat_id, f"未知命令 `{cmd}`，输入 `!help` 查看可用命令", ctx="cmd")


# ── 事件回调 ────────────────────────────────────────────


def _make_event_handler(user_map: UserMap, cfg: Config, token_file: str) -> EventDispatcherHandler:
    def on_im_message(event: CustomizedEvent) -> None:
        event_data = event.event or {}
        text, chat_id, _is_group, mentions = _parse_msg_content(event_data)
        sender_oid = _sender_open_id(event_data)
        if text and chat_id:
            log.info("WS message: chat=%s sender=%s text=%s", chat_id[:12], sender_oid[:12], text[:60])
            _dispatch(text, chat_id, sender_oid, mentions, user_map, cfg, token_file)

    _noop = lambda _: None
    return (
        EventDispatcherHandler
        .builder("", "")  # WebSocket 不需要 encrypt_key / verification_token
        .register_p2_customized_event("im.message.receive_v1", on_im_message)
        .register_p2_customized_event("im.chat.access_event.bot_p2p_chat_entered_v1", _noop)
        .build()
    )


# ── 线程入口 ────────────────────────────────────────────


def start_ws_client(cfg: Config, token_file: str, user_map: UserMap) -> None:
    """启动 WebSocket 客户端（阻塞）。应在独立线程中调用。"""
    event_handler = _make_event_handler(user_map, cfg, token_file)
    client = WsClient(
        app_id=cfg.app_id,
        app_secret=cfg.app_secret,
        event_handler=event_handler,
        auto_reconnect=True,
    )
    client.start()
