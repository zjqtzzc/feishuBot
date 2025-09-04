#!/bin/bash

# GitHub PR to Feishu Bot 安装脚本
# 注册为systemd服务并自动启动

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
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

# 检查是否为root用户
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "此脚本需要root权限运行"
        log_info "请使用: sudo $0"
        exit 1
    fi
}

# 获取当前目录
get_current_dir() {
    local script_dir=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
    echo "$script_dir"
}

# 检查应用是否已安装
check_app_installed() {
    local current_dir=$(get_current_dir)
    
    if [ ! -d "$current_dir/venv" ]; then
        log_error "虚拟环境不存在，请先运行 ./install.sh"
        exit 1
    fi
    
    if [ ! -f "$current_dir/app.py" ]; then
        log_error "应用文件不存在，请先运行 ./install.sh"
        exit 1
    fi
    
    if [ ! -f "$current_dir/config.json" ]; then
        log_error "配置文件不存在，请先运行 ./install.sh"
        exit 1
    fi
    
    log_info "应用检查通过"
}

# 配置systemd服务
setup_systemd() {
    local current_dir=$(get_current_dir)
    log_info "配置systemd服务..."
    
    # 创建systemd服务文件
    cat > /etc/systemd/system/github-feishu-bot.service << EOF
[Unit]
Description=GitHub PR to Feishu Bot Service
After=network.target
Wants=network.target

[Service]
Type=exec
User=$(whoami)
Group=$(id -gn)
WorkingDirectory=$current_dir
Environment=PATH=$current_dir/venv/bin
ExecStart=$current_dir/venv/bin/python app.py
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=github-feishu-bot

[Install]
WantedBy=multi-user.target
EOF
    
    systemctl daemon-reload
    systemctl enable github-feishu-bot
    
    log_info "systemd服务配置完成"
}

# 启动服务
start_service() {
    log_info "启动服务..."
    
    systemctl start github-feishu-bot
    sleep 3
    
    if systemctl is-active --quiet github-feishu-bot; then
        log_info "服务启动成功"
    else
        log_error "服务启动失败"
        systemctl status github-feishu-bot
        exit 1
    fi
}

# 显示服务信息
show_service_info() {
    local current_dir=$(get_current_dir)
    local server_ip=$(hostname -I | awk '{print $1}')
    
    echo ""
    echo "=== 服务注册完成 ==="
    echo "应用目录: $current_dir"
    echo "Webhook URL: http://${server_ip}:8080/webhook"
    echo "健康检查: http://${server_ip}:8080/health"
    echo ""
    echo "服务管理命令:"
    echo "sudo systemctl start github-feishu-bot     # 启动服务"
    echo "sudo systemctl stop github-feishu-bot      # 停止服务"
    echo "sudo systemctl restart github-feishu-bot   # 重启服务"
    echo "sudo systemctl status github-feishu-bot    # 查看状态"
    echo "sudo journalctl -u github-feishu-bot -f    # 查看日志"
    echo ""
    echo "服务已设置为开机自启动"
}

# 主函数
main() {
    log_info "开始注册 GitHub PR to Feishu Bot 系统服务..."
    check_root
    check_app_installed
    setup_systemd
    start_service
    show_service_info
    log_info "服务注册完成！"
}

# 运行主函数
main "$@"
