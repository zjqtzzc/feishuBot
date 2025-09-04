#!/bin/bash

# GitHub PR to Feishu Bot 卸载脚本
# 停止服务、删除systemd配置、清理文件

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_question() {
    echo -e "${BLUE}[?]${NC} $1"
}

# 检查是否为root用户
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "此脚本需要root权限运行"
        log_info "请使用: sudo ./uninstall.sh"
        exit 1
    fi
}

# 获取当前目录
get_current_dir() {
    echo "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
}

# 停止并禁用服务
stop_service() {
    log_info "停止GitHub PR to Feishu Bot服务..."
    
    if systemctl is-active --quiet github-feishu-bot 2>/dev/null; then
        systemctl stop github-feishu-bot
        log_info "服务已停止"
    else
        log_warn "服务未运行"
    fi
    
    if systemctl is-enabled --quiet github-feishu-bot 2>/dev/null; then
        systemctl disable github-feishu-bot
        log_info "服务已禁用"
    else
        log_warn "服务未启用"
    fi
}

# 删除systemd服务文件
remove_service_file() {
    log_info "删除systemd服务配置..."
    
    if [[ -f /etc/systemd/system/github-feishu-bot.service ]]; then
        rm -f /etc/systemd/system/github-feishu-bot.service
        systemctl daemon-reload
        log_info "systemd服务配置已删除"
    else
        log_warn "systemd服务配置文件不存在"
    fi
}

# 删除logrotate配置
remove_logrotate_config() {
    log_info "删除logrotate配置..."
    
    if [[ -f /etc/logrotate.d/github-feishu-bot ]]; then
        rm -f /etc/logrotate.d/github-feishu-bot
        log_info "logrotate配置已删除"
    else
        log_warn "logrotate配置文件不存在"
    fi
}

# 清理日志文件
cleanup_logs() {
    local current_dir=$(get_current_dir)
    
    log_info "清理日志文件..."
    
    # 删除当前目录下的日志文件
    if [[ -f "$current_dir/github-feishu-bot.log" ]]; then
        rm -f "$current_dir/github-feishu-bot.log"*
        log_info "应用日志文件已删除"
    fi
    
    # 清理systemd日志
    if command -v journalctl >/dev/null 2>&1; then
        journalctl --vacuum-time=1s --unit=github-feishu-bot >/dev/null 2>&1 || true
        log_info "systemd日志已清理"
    fi
}

# 清理systemd日志
cleanup_systemd_logs() {
    log_info "清理systemd日志..."
    
    if command -v journalctl >/dev/null 2>&1; then
        # 清理github-feishu-bot相关的日志
        journalctl --vacuum-time=1s --unit=github-feishu-bot >/dev/null 2>&1 || true
        log_info "systemd服务日志已清理"
        
        # 清理系统日志中的相关条目
        journalctl --vacuum-time=1s --grep="github-feishu-bot" >/dev/null 2>&1 || true
        log_info "系统日志中的相关条目已清理"
    else
        log_warn "journalctl命令不可用，跳过systemd日志清理"
    fi
}

# 显示卸载摘要
show_summary() {
    log_info "卸载摘要:"
    echo "  ✓ 服务已停止并禁用"
    echo "  ✓ systemd配置已删除"
    echo "  ✓ logrotate配置已删除"
    echo "  ✓ 应用日志文件已清理"
    echo "  ✓ systemd日志已清理"
    echo ""
    log_info "GitHub PR to Feishu Bot 服务已成功卸载"
    log_info "虚拟环境和配置文件已保留"
}

# 主函数
main() {
    echo "=========================================="
    echo "GitHub PR to Feishu Bot 卸载程序"
    echo "=========================================="
    echo ""
    
    check_root
    
    log_warn "此操作将完全卸载GitHub PR to Feishu Bot服务"
    log_question "确认继续? (y/N)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        log_info "卸载已取消"
        exit 0
    fi
    
    echo ""
    
    # 执行卸载步骤
    stop_service
    remove_service_file
    remove_logrotate_config
    cleanup_logs
    cleanup_systemd_logs
    
    echo ""
    show_summary
}

# 显示帮助信息
show_help() {
    echo "GitHub PR to Feishu Bot 卸载脚本"
    echo ""
    echo "用法:"
    echo "  sudo ./uninstall.sh          # 交互式卸载"
    echo "  sudo ./uninstall.sh --help   # 显示帮助信息"
    echo ""
    echo "功能:"
    echo "  - 停止并禁用systemd服务"
    echo "  - 删除systemd服务配置"
    echo "  - 删除logrotate配置"
    echo "  - 清理应用日志文件"
    echo "  - 清理systemd日志"
    echo "  - 保留虚拟环境和配置文件"
    echo ""
    echo "注意: 此脚本需要root权限运行"
}

# 检查命令行参数
if [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
    show_help
    exit 0
fi

# 运行主函数
main
