#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP 服务：GitHub Webhook 验签归类后立即返回，卡片刷新交给后台 worker"""

import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from src.card_store import CARD_STORE_FILENAME, CardStore
from src.config import data_dir, load_config
from src.feishu_ws import start_ws_client
from src.github_api import GitHubAPI
from src.handlers import HANDLED_EVENTS, handle
from src.user_map import USER_MAP_FILENAME, UserMap
from src.webhook_logging import ctx_tag, setup_logging
from src.worker import CardWorker

log = logging.getLogger(__name__)

MAX_BODY = 10 * 1024 * 1024
REQUEST_TIMEOUT = 30


def _setup():
    root = data_dir()
    cfg = load_config()
    user_map = UserMap(os.path.join(root, USER_MAP_FILENAME))
    store = CardStore(os.path.join(root, CARD_STORE_FILENAME))
    worker = CardWorker(cfg, GitHubAPI(token=cfg.github_token), store, user_map)
    return cfg, user_map, worker


class Handler(BaseHTTPRequestHandler):
    cfg, user_map, worker = _setup()

    def do_POST(self):
        if urlparse(self.path).path not in ("/", "/webhook"):
            self._json(404, {"error": "Not Found"})
            return
        n = int(self.headers.get("Content-Length", 0))
        if n < 0 or n > MAX_BODY:
            self._json(400, {"error": "Invalid Content-Length"})
            return
        self.connection.settimeout(REQUEST_TIMEOUT)
        raw = self.rfile.read(n) if n else b""
        event_type = self.headers.get("X-GitHub-Event", "")
        delivery = (self.headers.get("X-GitHub-Delivery") or "")[:8]

        data = None
        if event_type in HANDLED_EVENTS:
            try:
                data = json.loads(raw.decode("utf-8")) if raw else None
            except json.JSONDecodeError:
                self._json(400, {"error": "Invalid JSON"})
                return

        tag, gh_action = ctx_tag(event_type, data)
        t0 = time.monotonic()
        res = handle(
            raw,
            self.headers.get("X-Hub-Signature-256", ""),
            event_type,
            data,
            self.cfg,
        )
        if res.trigger:
            self.worker.submit(res.trigger)
        elapsed = time.monotonic() - t0
        log.info(
            "[%s] %s action=%s -> HTTP %s %s %s %.3fs delivery=%s",
            tag,
            event_type,
            gh_action or "-",
            res.code,
            res.status,
            res.detail or "-",
            elapsed,
            delivery or "-",
        )
        self._json(res.code, {"status" if res.code == 200 else "error": res.status})

    def _json(self, status: int, body: dict):
        b = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(b))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *args):
        pass


class QuietHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        exc_type, exc_value, _ = sys.exc_info()
        if exc_type in (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            log.debug("client closed %s:%s", client_address[0], client_address[1])
            return
        super().handle_error(request, client_address)


def main():
    setup_logging()
    port = Handler.cfg.github_webhook_port

    threading.Thread(target=Handler.worker.run, daemon=True, name="card-worker").start()
    threading.Thread(
        target=start_ws_client,
        args=(Handler.cfg, Handler.user_map),
        daemon=True,
        name="feishu-ws",
    ).start()

    try:
        QuietHTTPServer(("0.0.0.0", port), Handler).serve_forever()
    except OSError as e:
        if getattr(e, "errno", None) == 98:
            log.error("bind failed port=%s address already in use", port)
        raise
