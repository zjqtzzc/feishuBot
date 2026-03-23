#!/bin/bash

# GitHub PR to Feishu Bot 安装脚本
# 复制工程到安装目录，注册为 systemd 服务并自启动

set -e

# ========== 顶端配置：安装位置（可修改） ==========
INSTALL_DIR="./output"
# ================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "此脚本需要 root 权限运行"
        log_info "请使用: sudo $0"
        exit 1
    fi
}

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
install_dir=$(cd "$script_dir" && mkdir -p "$INSTALL_DIR" && cd "$INSTALL_DIR" && pwd)
run_user="${SUDO_USER:-root}"
run_group=$(id -gn "$run_user")

copy_project() {
    log_info "复制工程到 $install_dir ..."
    mkdir -p "$install_dir"
    if [[ "$script_dir" == "$install_dir" ]]; then
        log_error "安装目录不能与脚本所在目录相同"
        exit 1
    fi
    rsync -a --exclude='venv' --exclude='__pycache__' --exclude='.git' --exclude="$(basename "$install_dir")" "$script_dir/" "$install_dir/"
}

set_normal_permissions() {
    log_info "设置普通文件权限..."
    chown -R "$run_user:$run_group" "$install_dir"
    find "$install_dir" -not -path "*/venv/*" -type d -exec chmod 755 {} +
    find "$install_dir" -not -path "*/venv/*" -type f -exec chmod 644 {} +
}

setup_venv() {
    local src_venv="$script_dir/venv"
    local dst_venv="$install_dir/venv"

    if [[ ! -d "$src_venv" ]] || [[ ! -x "$src_venv/bin/python" ]]; then
        log_error "源目录 venv 不存在或不可用，请先运行 setup.sh"
        exit 1
    fi

    # 若 output/venv 是真实目录则删除，若是旧软链接也删除
    if [[ -d "$dst_venv" ]] && [[ ! -L "$dst_venv" ]]; then
        log_warn "output/venv 是独立虚拟环境，将替换为软链接以复用源 venv"
        rm -rf "$dst_venv"
    elif [[ -L "$dst_venv" ]]; then
        rm -f "$dst_venv"
    fi

    ln -s "$src_venv" "$dst_venv"
    log_info "已链接 venv: $dst_venv -> $src_venv"
}

check_config() {
    if [[ ! -f "$install_dir/config.json" ]]; then
        if [[ -f "$install_dir/config.json.example" ]]; then
            cp "$install_dir/config.json.example" "$install_dir/config.json"
            log_warn "已从 config.json.example 复制，请编辑 $install_dir/config.json 填写实际配置"
        else
            log_error "config.json 不存在且无 config.json.example"
            exit 1
        fi
    fi
}

stop_existing_service() {
    # 若之前已安装并启动过，则先停掉并禁用，避免后续启动再次抢端口
    if systemctl is-active --quiet github-feishu-bot 2>/dev/null; then
        log_info "检测到 github-feishu-bot 正在运行，准备停止..."
        systemctl stop github-feishu-bot 2>/dev/null || true
    fi
    systemctl disable github-feishu-bot 2>/dev/null || true
    systemctl reset-failed github-feishu-bot 2>/dev/null || true
    sleep 1
}

ensure_port_released() {
    # 仅当 config.json 可用时才尝试释放端口，避免在没配置时误杀
    if [[ ! -f "$install_dir/config.json" ]]; then
        return 0
    fi
    if ! command -v jq &> /dev/null; then
        return 0
    fi

    local port
    port=$(jq -r '.github_webhook_port' "$install_dir/config.json" 2>/dev/null || echo "")
    [[ -z "$port" || "$port" == "null" ]] && return 0

    local i line pid cmd
    for i in {1..10}; do
        # awk：若发现了 LISTEN 行(NR>1)则返回 1；若未发现则返回 0（端口已释放）
        if ss -ltnp "sport = :${port}" 2>/dev/null | awk 'NR>1{exit 1} END{exit 0}'; then
            return 0
        fi

        line=$(ss -ltnp "sport = :${port}" 2>/dev/null | awk 'NR==2{print; exit}')
        pid=$(printf '%s' "$line" | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p')
        if [[ -n "$pid" ]]; then
            cmd=$(ps -p "$pid" -o args= 2>/dev/null || echo "")
            if [[ "$cmd" == *"app.py"* && "$cmd" == *"$install_dir"* ]]; then
                log_warn "端口 ${port} 仍被占用(pid=${pid})，尝试终止以避免 bind 失败..."
                kill -9 "$pid" 2>/dev/null || true
                sleep 1
                continue
            else
                log_error "端口 ${port} 被非本服务占用: pid=${pid} cmd=${cmd}"
                return 1
            fi
        fi
        sleep 1
    done

    log_error "端口 ${port} 在超时后仍未释放，无法继续安装"
    return 1
}

setup_systemd() {
    log_info "注册 systemd 服务..."
    cat > /etc/systemd/system/github-feishu-bot.service << UNIT
[Unit]
Description=GitHub PR to Feishu Bot Service
After=network.target
Wants=network.target

[Service]
Type=exec
User=$run_user
Group=$run_group
WorkingDirectory=$install_dir
Environment=PATH=$install_dir/venv/bin:/usr/local/bin:/usr/bin
ExecStart=$install_dir/venv/bin/python app.py
Restart=always
RestartSec=10

# 方案A：加固停止/重启时的清理，避免旧进程仍在 LISTEN 导致新实例 bind 失败
TimeoutStopSec=10
KillSignal=SIGTERM
FinalKillSignal=SIGKILL
KillMode=control-group
StandardOutput=journal
StandardError=journal
SyslogIdentifier=github-feishu-bot

[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload
}

enable_and_start() {
    log_info "设置自启动并启动服务..."
    systemctl enable github-feishu-bot
    systemctl start github-feishu-bot
    sleep 2
    if systemctl is-active --quiet github-feishu-bot; then
        log_info "服务启动成功"
    else
        log_error "服务启动失败"
        systemctl status github-feishu-bot --no-pager
        exit 1
    fi
}

show_info() {
    local port
    port=$(jq -r '.github_webhook_port' "$install_dir/config.json")
    echo ""
    echo "=== 安装完成 ==="
    echo "安装目录: $install_dir"
    echo "使用 venv: $script_dir/venv"
    echo ""
    echo "管理命令:"
    echo "  sudo systemctl start github-feishu-bot"
    echo "  sudo systemctl stop github-feishu-bot"
    echo "  sudo systemctl restart github-feishu-bot"
    echo "  sudo journalctl -u github-feishu-bot -f"
}

main() {
    log_info "开始安装 GitHub PR to Feishu Bot ..."
    check_root
    stop_existing_service
    copy_project
    setup_venv
    set_normal_permissions
    check_config
    ensure_port_released
    setup_systemd
    enable_and_start
    show_info
}

main "$@"
