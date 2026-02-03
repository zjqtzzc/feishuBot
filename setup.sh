#!/bin/bash
# 构建 venv 并配置 config.json（以 config.json.example 为模板）

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

script_dir=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
cd "$script_dir"

check_dependencies() {
    log_info "检查系统依赖..."
    command -v python3 &> /dev/null || log_error "未安装 python3: sudo apt install python3"
    command -v pip3 &> /dev/null || log_error "未安装 pip3: sudo apt install python3-pip"
    python3 -m venv --help &> /dev/null || log_error "未安装 python3-venv: sudo apt install python3-venv"
    log_info "系统依赖检查通过"
}

setup_venv() {
    log_info "创建 Python 虚拟环境..."
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi
    source venv/bin/activate
    pip install -U pip
    pip install -r requirements.txt
    log_info "虚拟环境就绪"
}

setup_config() {
    log_info "配置 config.json..."
    local config_file="$script_dir/config.json"
    local example="$script_dir/config.json.example"
    if [ ! -f "$config_file" ]; then
        [ ! -f "$example" ] && log_error "config.json 不存在且未找到 config.json.example"
        cp "$example" "$config_file"
        log_info "已从 config.json.example 复制生成 $config_file，请按需修改"
    fi
    if command -v jq &> /dev/null; then
        echo ""
        read -p "GitHub token (留空跳过): " gh_token
        [ -n "$gh_token" ] && jq --arg t "$gh_token" '.github_token = $t' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"
        read -p "飞书 app_id (留空跳过): " app_id
        [ -n "$app_id" ] && jq --arg a "$app_id" '.app_id = $a' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"
        read -p "飞书 app_secret (留空跳过): " app_secret
        [ -n "$app_secret" ] && jq --arg a "$app_secret" '.app_secret = $a' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"
        read -p "飞书 chat_id (留空跳过): " chat_id
        [ -n "$chat_id" ] && jq --arg c "$chat_id" '.chat_id = $c' "$config_file" > "$config_file.tmp" && mv "$config_file.tmp" "$config_file"
    else
        log_warn "未安装 jq，请手动编辑 $config_file（参考 config.json.example）"
    fi
    log_info "配置完成"
}

test_setup() {
    log_info "验证配置与导入..."
    source venv/bin/activate
    python3 -c "from config import load_config; load_config(); print('config OK')" || log_error "config 加载失败，请检查 config.json 必填项"
    python3 -c "import app; print('app OK')" || log_error "app 导入失败"
    log_info "验证通过"
}

main() {
    log_info "开始 setup（venv + config）..."
    check_dependencies
    setup_venv
    setup_config
    test_setup
    log_info "完成。运行: source venv/bin/activate && python app.py"
}

main "$@"
