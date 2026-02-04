#!/bin/bash

# GitHub PR to Feishu Bot 卸载脚本
# 关闭服务并删除相关文件

set -e

# ========== 顶端配置：安装位置（仅当无 systemd 配置时用作回退） ==========
INSTALL_DIR="./output"
# ================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "此脚本需要 root 权限运行"
        log_info "请使用: sudo $0"
        exit 1
    fi
}

get_install_dir() {
    if [[ -f /etc/systemd/system/github-feishu-bot.service ]]; then
        grep '^WorkingDirectory=' /etc/systemd/system/github-feishu-bot.service | cut -d= -f2
    else
        script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
        (cd "$script_dir" && cd "$INSTALL_DIR" && pwd)
    fi
}

install_dir=$(get_install_dir)

stop_and_disable() {
    log_info "停止并禁用服务..."
    systemctl stop github-feishu-bot 2>/dev/null || true
    systemctl disable github-feishu-bot 2>/dev/null || true
}

remove_service_file() {
    log_info "删除 systemd 服务配置..."
    rm -f /etc/systemd/system/github-feishu-bot.service
    systemctl daemon-reload
}

remove_install_dir() {
    if [[ -n "$install_dir" && -d "$install_dir" ]]; then
        log_info "删除安装目录 $install_dir ..."
        rm -rf "$install_dir"
    fi
}

main() {
    check_root
    stop_and_disable
    remove_service_file
    remove_install_dir
    log_info "卸载完成"
}

main "$@"
