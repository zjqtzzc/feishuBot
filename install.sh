#!/bin/bash

# GitHub PR to Feishu Bot 安装脚本
# 复制工程到安装目录，注册为 systemd 服务并自启动

set -e

# ========== 顶端配置：安装位置（可修改） ==========
INSTALL_DIR="./output"
# ================================================

# 颜色定义
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
    find "$install_dir" -type d -exec chmod 755 {} +
    find "$install_dir" -type f -exec chmod 644 {} +
    [[ -d "$install_dir/venv/bin" ]] && find "$install_dir/venv/bin" -mindepth 1 -maxdepth 1 -exec chmod 755 {} +
}

setup_venv() {
    if [[ -d "$install_dir/venv" ]] && [[ -x "$install_dir/venv/bin/python" ]]; then
        log_info "虚拟环境已存在，跳过创建"
        if "$install_dir/venv/bin/pip" install -q -r "$install_dir/requirements.txt" --dry-run 2>/dev/null | grep -q "Would install"; then
            log_info "安装缺失依赖..."
            "$install_dir/venv/bin/pip" install -q -U pip
            "$install_dir/venv/bin/pip" install -q -r "$install_dir/requirements.txt"
        else
            log_info "依赖已满足，跳过安装"
        fi
        return
    fi
    log_info "创建虚拟环境并安装依赖..."
    python3 -m venv "$install_dir/venv"
    "$install_dir/venv/bin/pip" install -q -U pip
    "$install_dir/venv/bin/pip" install -q -r "$install_dir/requirements.txt"
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

setup_systemd() {
    log_info "注册 systemd 服务..."
    cat > /etc/systemd/system/github-feishu-bot.service << EOF
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
StandardOutput=journal
StandardError=journal
SyslogIdentifier=github-feishu-bot

[Install]
WantedBy=multi-user.target
EOF
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
    local ip=$(hostname -I | awk '{print $1}')
    echo ""
    echo "=== 安装完成 ==="
    echo "安装目录: $install_dir"
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
    copy_project
    setup_venv
    set_normal_permissions
    check_config
    setup_systemd
    enable_and_start
    show_info
}

main "$@"
