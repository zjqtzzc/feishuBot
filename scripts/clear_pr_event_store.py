#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性：按 .pr_event_store 里的 message_id 逐个撤回飞书消息，成功后删除该文件。

用法（在项目根目录）:
  python scripts/clear_pr_event_store.py
  python scripts/clear_pr_event_store.py --store output/.pr_event_store
  python scripts/clear_pr_event_store.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.config import load_config
from src.feishu_api import delete_message
from src.feishu_credential import FEISHU_TOKEN_FILENAME, get_tenant_access_token


def main() -> int:
    ap = argparse.ArgumentParser(description="撤回 store 中全部飞书消息后删除该文件")
    ap.add_argument(
        "--store",
        default=os.path.join(ROOT, "output", ".pr_event_store"),
        help="默认: 项目根/output/.pr_event_store",
    )
    ap.add_argument("--dry-run", action="store_true", help="只打印将要删除的 message_id，不调用 API、不写文件")
    args = ap.parse_args()

    store_path = os.path.abspath(args.store)
    if not os.path.isfile(store_path):
        print(f"文件不存在: {store_path}", file=sys.stderr)
        return 1

    with open(store_path, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    data: dict = json.loads(raw) if raw else {}

    ids: list[tuple[str, str | None]] = []
    for key, rec in data.items():
        mid = rec.get("message_id") if isinstance(rec, dict) else None
        if mid:
            ids.append((key, mid))

    print(f"store={store_path} 共 {len(data)} 条 PR 记录，其中含 message_id 的 {len(ids)} 条")

    if args.dry_run:
        for key, mid in ids:
            print(f"  [dry-run] {key} -> {mid}")
        print("未执行删除、未清空文件")
        return 0

    cfg = load_config()
    token_file = os.path.join(ROOT, FEISHU_TOKEN_FILENAME)
    token = get_tenant_access_token(cfg.app_id, cfg.app_secret, token_file)
    if not token:
        print("获取 tenant_access_token 失败", file=sys.stderr)
        return 1

    failed = 0
    for key, mid in ids:
        ok, msg = delete_message(token, mid)
        if ok:
            print(f"ok {key} {mid}")
        else:
            failed += 1
            print(f"fail {key} {mid} -> {msg}", file=sys.stderr)

    if failed:
        print(f"有 {failed} 条撤回失败，未删除 store 文件，请处理后再运行", file=sys.stderr)
        return 1

    os.remove(store_path)
    print(f"已删除: {store_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
