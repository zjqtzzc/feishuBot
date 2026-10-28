#!/bin/bash

# GitHub PR to Feishu Bot 安装 / 升级脚本（首次安装和升级都用它）
#
#   sudo ./install.sh            安装或升级到当前源码
#   sudo ./install.sh rollback   回退到上一版代码
#
# 安装目录结构：
#   output/app/       当前代码（每次升级整体替换）
#   output/app.prev/  上一版代码，用于回滚
#   output/venvs/     按 requirements.txt 哈希区分的虚拟环境，依赖没变就复用
#   output/venv       → 当前使用的 venvs/<哈希>
#   output/data/      config.json、卡片记录、用户映射；升级永不覆盖
#
# 升级流程：新代码和依赖先装到旁边并验证（缺配置项等会在这一步失败，线上不受影响）
# → 停服务 → 替换代码 → 启动 → 检查端口；启动失败自动回滚到上一版。

set -e

# ========== 顶端配置（可修改） ==========
INSTALL_DIR="./output"
SERVICE="github-feishu-bot"
# 额外的 pip 参数，例如国内镜像：PIP_ARGS="-i https://pypi.tuna.tsinghua.edu.cn/simple"
PIP_ARGS=""
# =======================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
die() { echo -e "${RED}[ERROR]${NC} $1" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "此脚本需要 root 权限运行，请使用: sudo $0"

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
base=$(cd "$script_dir" && mkdir -p "$INSTALL_DIR" && cd "$INSTALL_DIR" && pwd)
[[ "$base" != "$script_dir" ]] || die "安装目录不能与源码目录相同"
run_user="${SUDO_USER:-root}"
run_group=$(id -gn "$run_user")
unit_file="/etc/systemd/system/$SERVICE.service"
data="$base/data"

check_dependencies() {
    command -v python3 &> /dev/null || die "未安装 python3: sudo apt install python3"
    python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "需要 Python 3.10 及以上"
    python3 -m venv --help &> /dev/null || die "未安装 python3-venv: sudo apt install python3-venv"
    command -v rsync &> /dev/null || die "未安装 rsync: sudo apt install rsync"
}

stage_code() {
    log_info "准备新代码 $base/app.new ..."
    rsync -a --delete \
        --exclude='.git' \
        --exclude='venv' \
        --exclude='__pycache__' \
        --exclude="$(basename "$base")" \
        --exclude='config.json' \
        --exclude='.pr_event_store*' \
        --exclude='.user_map.json' \
        --exclude='.feishu_token' \
        --exclude='*.log' \
        "$script_dir/" "$base/app.new/"
}

prepare_venv() {
    req_hash=$(sha256sum "$base/app.new/requirements.txt" | cut -c1-12)
    new_venv="$base/venvs/$req_hash"
    if [[ -x "$new_venv/bin/python" && -f "$new_venv/.ok" ]]; then
        log_info "依赖未变化，复用虚拟环境 venvs/$req_hash"
        return
    fi
    log_info "创建虚拟环境 venvs/$req_hash ..."
    rm -rf "$new_venv"
    mkdir -p "$base/venvs"
    python3 -m venv "$new_venv"
    # shellcheck disable=SC2086
    "$new_venv/bin/python" -m pip install -q --disable-pip-version-check $PIP_ARGS -r "$base/app.new/requirements.txt"
    touch "$new_venv/.ok"
}

# 首次安装没有配置：生成模板并退出
ensure_config() {
    [[ -f "$data/config.json" ]] && return 0
    mkdir -p "$data"
    cp "$base/app.new/config.json.example" "$data/config.json"
    chown -R "$run_user:$run_group" "$data"
    chmod 600 "$data/config.json"
    die "已生成 $data/config.json，请填写实际配置后重新运行本脚本"
}

validate() {
    log_info "验证新代码与配置..."
    (cd "$base/app.new" && BOT_DATA_DIR="$data" "$new_venv/bin/python" -c "import app") \
        || die "新版本验证失败（见上方报错），线上服务未做任何改动"
    check_port_owner "$data/config.json"
}

config_port() {
    python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['github_webhook_port'])" "$1"
}

# 端口若被本服务以外的进程占着（如手动启动的旧进程），新服务会 bind 失败，而检查时却能看到端口在监听
check_port_owner() {
    command -v ss &> /dev/null || return 0
    local port holder main
    port=$(config_port "$1")
    holder=$(ss -ltnp "sport = :$port" | awk 'NR>1' | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | head -1)
    [[ -n "$holder" ]] || return 0
    main=$(systemctl show -p MainPID --value "$SERVICE" 2>/dev/null || true)
    [[ "$holder" == "$main" ]] && return 0
    die "端口 $port 被本服务以外的进程占用（pid=$holder: $(ps -p "$holder" -o args= 2>/dev/null)），请先停掉它；线上服务未做任何改动"
}

stop_service() {
    if [[ -f "$unit_file" ]]; then
        log_info "停止服务..."
        systemctl stop "$SERVICE" 2>/dev/null || true
    fi
}

switch_code() {
    log_info "替换代码..."
    if [[ -d "$base/app" ]]; then
        rm -rf "$base/app.prev"
        mv "$base/app" "$base/app.prev"
        [[ -L "$base/venv" ]] && readlink "$base/venv" > "$base/app.prev/.venv"
    fi
    mv "$base/app.new" "$base/app"
    ln -sfn "venvs/$req_hash" "$base/venv"
}

write_unit() {
    cat > "$unit_file" << UNIT
[Unit]
Description=GitHub PR to Feishu Bot Service
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=$run_user
Group=$run_group
WorkingDirectory=$base/app
Environment=BOT_DATA_DIR=$data
ExecStart=$base/venv/bin/python $base/app/app.py
Restart=always
RestartSec=10
TimeoutStopSec=10
KillMode=control-group
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$SERVICE

[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload
    systemctl enable --quiet "$SERVICE"
}

port_listening() {
    command -v ss &> /dev/null || return 0
    ss -ltn "sport = :$1" | grep -q LISTEN
}

# 启动后在 15 秒内看到端口监听才算成功
start_and_check() {
    chown -R "$run_user:$run_group" "$base"
    chmod 600 "$data/config.json"
    systemctl start "$SERVICE" || true
    local port i
    port=$(config_port "$data/config.json")
    for i in {1..15}; do
        sleep 1
        if systemctl is-active --quiet "$SERVICE" && port_listening "$port"; then
            log_info "服务已启动，端口 $port"
            return 0
        fi
    done
    return 1
}

rollback() {
    [[ -d "$base/app.prev" && -f "$base/app.prev/.venv" ]] || die "没有可回滚的上一版"
    log_warn "回滚到上一版..."
    systemctl stop "$SERVICE" 2>/dev/null || true
    rm -rf "$base/app.failed"
    [[ -d "$base/app" ]] && mv "$base/app" "$base/app.failed"
    mv "$base/app.prev" "$base/app"
    ln -sfn "$(cat "$base/app/.venv")" "$base/venv"
    if start_and_check; then
        log_warn "已回滚到上一版；被替换的版本保留在 $base/app.failed"
    else
        die "回滚后仍启动失败，请查看: journalctl -u $SERVICE -n 100"
    fi
}

prune_venvs() {
    local keep_cur keep_prev d
    keep_cur=$(readlink "$base/venv")
    keep_prev=$(cat "$base/app.prev/.venv" 2>/dev/null || true)
    for d in "$base"/venvs/*; do
        [[ -d "$d" ]] || continue
        [[ "venvs/$(basename "$d")" == "$keep_cur" || "venvs/$(basename "$d")" == "$keep_prev" ]] && continue
        rm -rf "$d"
    done
}

main() {
    check_dependencies
    if [[ "$1" == "rollback" ]]; then
        rollback
        return
    fi
    log_info "安装 / 升级 GitHub PR to Feishu Bot 到 $base"
    stage_code
    prepare_venv
    ensure_config
    validate
    stop_service
    switch_code
    write_unit
    if ! start_and_check; then
        journalctl -u "$SERVICE" -n 30 --no-pager || true
        if [[ -f "$base/app.prev/.venv" ]]; then
            rollback
            exit 1
        fi
        die "启动失败，且没有可自动回滚的版本，请查看: journalctl -u $SERVICE -n 100"
    fi
    prune_venvs
    echo ""
    echo "=== 完成 ==="
    echo "代码: $base/app    数据与配置: $data"
    echo "日志: sudo journalctl -u $SERVICE -f"
    echo "回滚: sudo $0 rollback"
}

main "$@"
