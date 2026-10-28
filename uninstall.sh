#!/bin/bash

# GitHub PR to Feishu Bot 卸载脚本
#
#   sudo ./uninstall.sh          停止并删除服务和代码，保留 data/（配置、卡片记录、用户映射）
#   sudo ./uninstall.sh --purge  连 data/ 一起删除

set -e

# ========== 顶端配置：安装位置（仅当无 systemd 配置时用作回退） ==========
INSTALL_DIR="./output"
SERVICE="github-feishu-bot"
# ================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
die() { echo -e "${RED}[ERROR]${NC} $1" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "此脚本需要 root 权限运行，请使用: sudo $0"

unit_file="/etc/systemd/system/$SERVICE.service"

get_install_dir() {
    local wd
    if [[ -f "$unit_file" ]]; then
        wd=$(grep '^WorkingDirectory=' "$unit_file" | cut -d= -f2)
        # 新布局 WorkingDirectory 是 <安装目录>/app
        [[ "$(basename "$wd")" == "app" ]] && dirname "$wd" || echo "$wd"
    else
        local script_dir
        script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
        (cd "$script_dir" && cd "$INSTALL_DIR" 2>/dev/null && pwd)
    fi
}

main() {
    local base
    base=$(get_install_dir)

    log_info "停止并删除服务..."
    systemctl stop "$SERVICE" 2>/dev/null || true
    systemctl disable "$SERVICE" 2>/dev/null || true
    rm -f "$unit_file"
    systemctl daemon-reload

    [[ -n "$base" && -d "$base" ]] || { log_info "卸载完成"; return; }
    if [[ "$1" == "--purge" ]]; then
        log_info "删除安装目录 $base ..."
        rm -rf "$base"
    else
        log_info "删除代码与虚拟环境，保留 $base/data ..."
        # 旧版布局的数据直接在安装目录下，也一并保留
        find "$base" -mindepth 1 -maxdepth 1 ! -name data ! -name config.json \
            ! -name .pr_event_store ! -name .user_map.json -exec rm -rf {} +
    fi
    log_info "卸载完成"
}

main "$@"
