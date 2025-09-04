#!/bin/bash

# GitHub PR to Feishu Bot 部署脚本
# 适用于 Ubuntu 系统

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

# 检查系统依赖
check_dependencies() {
    log_info "检查系统依赖..."
    
    if ! command -v python3 &> /dev/null; then
        log_error "Python3 未安装，请先安装: sudo apt install python3"
        exit 1
    fi
    
    if ! command -v pip3 &> /dev/null; then
        log_error "pip3 未安装，请先安装: sudo apt install python3-pip"
        exit 1
    fi
    
    if ! command -v python3-venv &> /dev/null; then
        log_error "python3-venv 未安装，请先安装: sudo apt install python3-venv"
        exit 1
    fi
    
    log_info "系统依赖检查通过"
}

# 创建应用目录和用户
setup_application() {
    log_info "创建应用目录和用户..."
    mkdir -p /opt/github-feishu-bot
    
    if ! id "www-data" &>/dev/null; then
        useradd -r -s /bin/false www-data
    fi
    
    chown -R www-data:www-data /opt/github-feishu-bot
    chmod 755 /opt/github-feishu-bot
}

# 部署应用代码
deploy_application() {
    log_info "部署应用代码..."
    cp app.py config.py requirements.txt /opt/github-feishu-bot/
    
    cd /opt/github-feishu-bot
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    
    chown -R www-data:www-data /opt/github-feishu-bot
    chmod +x /opt/github-feishu-bot/app.py
}

# 配置systemd服务
setup_systemd() {
    log_info "配置systemd服务..."
    cp github-feishu-bot.service /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable github-feishu-bot
}


# 配置环境变量
setup_environment() {
    log_info "配置环境变量..."
    cat > /opt/github-feishu-bot/.env << EOF
FEISHU_WEBHOOK_URL=
GITHUB_WEBHOOK_SECRET=
PORT=8080
FLASK_ENV=production
LOG_LEVEL=INFO
EOF
    chown www-data:www-data /opt/github-feishu-bot/.env
    chmod 600 /opt/github-feishu-bot/.env
    log_warn "请编辑 /opt/github-feishu-bot/.env 设置环境变量"
}

# 启动服务
start_services() {
    log_info "启动服务..."
    systemctl start github-feishu-bot
    sleep 3
    if ! systemctl is-active --quiet github-feishu-bot; then
        log_error "服务启动失败"
        systemctl status github-feishu-bot
        exit 1
    fi
}

# 显示部署信息
show_deployment_info() {
    local server_ip=$(hostname -I | awk '{print $1}')
    local port=${PORT:-8080}
    
    echo ""
    echo "=== 部署完成 ==="
    echo "Webhook URL: http://${server_ip}:${port}/webhook"
    echo "健康检查: http://${server_ip}:${port}/health"
    echo ""
    echo "下一步:"
    echo "1. sudo nano /opt/github-feishu-bot/.env  # 设置环境变量"
    echo "2. sudo systemctl restart github-feishu-bot  # 重启服务"
    echo "3. 在GitHub仓库中配置webhook"
    echo ""
    echo "常用命令:"
    echo "sudo systemctl status github-feishu-bot  # 查看状态"
    echo "sudo journalctl -u github-feishu-bot -f  # 查看日志"
}

# 主函数
main() {
    log_info "开始部署 GitHub PR to Feishu Bot..."
    check_root
    check_dependencies
    setup_application
    deploy_application
    setup_systemd
    setup_environment
    start_services
    show_deployment_info
}

# 运行主函数
main "$@"
