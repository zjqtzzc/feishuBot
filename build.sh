#!/bin/bash

# GitHub PR to Feishu Bot 构建脚本
# 安装Python环境和配置应用

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
    
    if ! python3 -m venv --help &> /dev/null; then
        log_error "python3-venv 未安装，请先安装: sudo apt install python3-venv"
        exit 1
    fi
    
    log_info "系统依赖检查通过"
}

# 获取当前目录
get_current_dir() {
    local script_dir=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
    echo "$script_dir"
}

# 创建虚拟环境
setup_venv() {
    local current_dir=$(get_current_dir)
    log_info "创建Python虚拟环境..."
    
    cd "$current_dir"
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi
    
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    
    log_info "虚拟环境创建完成"
}

# 配置应用
setup_config() {
    local current_dir=$(get_current_dir)
    log_info "配置应用..."
    
    # 交互式输入飞书webhook URL
    echo ""
    echo "=== 配置飞书机器人 ==="
    echo "请在飞书群聊中创建自定义机器人，然后复制webhook URL"
    echo "示例: https://open.feishu.cn/open-apis/bot/v2/hook/xxx-xxx-xxx"
    echo ""
    
    while true; do
        read -p "请输入飞书webhook URL: " feishu_url
        if [[ -n "$feishu_url" ]]; then
            break
        else
            echo "URL不能为空，请重新输入"
        fi
    done
    
    # 交互式输入GitHub webhook密钥（可选）
    echo ""
    echo "=== 配置GitHub Webhook密钥（可选）==="
    echo "为了安全，建议设置GitHub webhook密钥"
    echo "如果不需要，直接按回车跳过"
    echo ""
    read -p "请输入GitHub webhook密钥: " github_secret
    
    # 更新配置文件
    local config_file="$current_dir/config.json"
    if [ -f "$config_file" ]; then
        # 使用jq更新配置文件（如果可用）
        if command -v jq &> /dev/null; then
            jq --arg url "$feishu_url" --arg secret "$github_secret" \
               '.feishu_webhook_url = $url | .github_webhook_secret = $secret' \
               "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"
        else
            # 如果没有jq，使用sed替换
            sed -i "s|\"feishu_webhook_url\": \"[^\"]*\"|\"feishu_webhook_url\": \"$feishu_url\"|g" "$config_file"
            if [[ -n "$github_secret" ]]; then
                sed -i "s|\"github_webhook_secret\": \"[^\"]*\"|\"github_webhook_secret\": \"$github_secret\"|g" "$config_file"
            fi
        fi
        log_info "配置文件已更新"
    else
        log_error "配置文件不存在: $config_file"
        exit 1
    fi
}

# 测试应用
test_app() {
    local current_dir=$(get_current_dir)
    log_info "测试应用..."
    
    cd "$current_dir"
    source venv/bin/activate
    
    # 测试配置
    if python3 -c "import app; print('配置验证:', '通过' if app.config.validate() else '失败')"; then
        log_info "配置验证通过"
    else
        log_warn "配置验证失败，请检查配置文件"
    fi
    
    # 测试导入
    if python3 -c "import app; print('应用导入成功')"; then
        log_info "应用导入成功"
    else
        log_error "应用导入失败"
        exit 1
    fi
}

# 显示安装信息
show_install_info() {
    local current_dir=$(get_current_dir)
    local server_ip=$(hostname -I | awk '{print $1}')
    
    echo ""
    echo "=== 安装完成 ==="
    echo "应用目录: $current_dir"
    echo "Webhook URL: http://${server_ip}:8080/webhook"
    echo "健康检查: http://${server_ip}:8080/health"
    echo ""
    echo "现在可以运行应用:"
    echo "1. 直接运行: python3 app.py"
    echo "2. 使用虚拟环境: source venv/bin/activate && python app.py"
    echo ""
    echo "如需注册为系统服务，请运行:"
    echo "sudo ./service.sh"
    echo ""
    echo "常用命令:"
    echo "source venv/bin/activate  # 激活虚拟环境"
    echo "python app.py            # 运行应用"
    echo "deactivate               # 退出虚拟环境"
}

# 主函数
main() {
    log_info "开始安装 GitHub PR to Feishu Bot..."
    check_dependencies
    setup_venv
    setup_config
    test_app
    show_install_info
    log_info "安装完成！"
}

# 运行主函数
main "$@"
