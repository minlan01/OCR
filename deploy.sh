#!/bin/bash
# ============================================================
# ScanStruct 服务器部署脚本 — Ubuntu
# ============================================================
# 使用方法:
#   chmod +x deploy.sh
#   ./deploy.sh              # 完整部署（首次）
#   ./deploy.sh --update     # 更新代码后重新构建
#   ./deploy.sh --stop       # 停止所有服务
#   ./deploy.sh --status     # 查看运行状态
#   ./deploy.sh --logs       # 查看实时日志
# ============================================================

set -e

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "\n${BLUE}==>${NC} $1"; }

# 项目目录（脚本所在目录）
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

ENV_FILE=".env.production"

# ============================================================
# 函数定义
# ============================================================

check_docker() {
    log_step "检查 Docker 环境..."
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装"
        log_info "安装 Docker..."
        curl -fsSL https://get.docker.com | sh
        systemctl start docker
        systemctl enable docker
        log_info "Docker 安装完成"
    fi

    if ! docker compose version &> /dev/null && ! docker-compose version &> /dev/null; then
        log_error "Docker Compose 未安装"
        log_info "安装 Docker Compose 插件..."
        apt-get update && apt-get install -y docker-compose-plugin 2>/dev/null || yum install -y docker-compose-plugin 2>/dev/null
    fi

    # 检测使用 docker compose 还是 docker-compose
    if docker compose version &> /dev/null; then
        DC="docker compose"
    else
        DC="docker-compose"
    fi
    log_info "使用: $DC"
}

check_env() {
    log_step "检查环境配置..."
    if [ ! -f "$ENV_FILE" ]; then
        log_error "找不到 $ENV_FILE"
        log_info "请先创建 .env.production 配置文件"
        exit 1
    fi

    # 检查关键密码是否还是默认值
    if grep -q "change_me" "$ENV_FILE" 2>/dev/null; then
        log_warn "检测到 API_KEY 还是默认值 'change_me'，请修改为强密码!"
    fi
}

create_volumes() {
    log_step "创建 Docker volumes（如果不存在）..."
    docker volume create ocrscanstruct_scanstruct_pgdata 2>/dev/null || true
    docker volume create ocrscanstruct_scanstruct_redisdata 2>/dev/null || true
    docker volume create ocrscanstruct_scanstruct_miniodata 2>/dev/null || true
    docker volume create ocrscanstruct_scanstruct_templates 2>/dev/null || true
    log_info "Volumes 就绪"
}

build_and_start() {
    log_step "构建并启动服务..."
    $DC --env-file "$ENV_FILE" up -d --build
    log_info "服务已启动"
}

init_database() {
    log_step "初始化数据库..."
    # 等待 PostgreSQL 就绪
    log_info "等待 PostgreSQL 启动..."
    sleep 5

    # 运行数据库迁移
    $DC --env-file "$ENV_FILE" exec -T -w /app/db/migrations api \
        python -m alembic -c alembic.ini upgrade head

    # 初始化种子数据
    $DC --env-file "$ENV_FILE" exec -T api python scripts/init_db.py

    log_info "数据库初始化完成"
}

configure_firewall() {
    log_step "配置防火墙..."
    if command -v ufw &> /dev/null; then
        ufw allow 8900/tcp 2>/dev/null || true
        log_info "已开放 8900 端口 (ufw)"
    elif command -v firewall-cmd &> /dev/null; then
        firewall-cmd --permanent --add-port=8900/tcp 2>/dev/null || true
        firewall-cmd --reload 2>/dev/null || true
        log_info "已开放 8900 端口 (firewalld)"
    elif command -v iptables &> /dev/null; then
        iptables -I INPUT -p tcp --dport 8900 -j ACCEPT 2>/dev/null || true
        log_info "已开放 8900 端口 (iptables)"
    else
        log_warn "未检测到防火墙，请确保阿里云安全组开放了 8900 端口"
    fi
}

show_status() {
    log_step "服务状态..."
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" --filter "name=scanstruct"
    echo ""
    log_info "访问地址: http://$(hostname -I | awk '{print $1}'):8900"
}

show_logs() {
    $DC --env-file "$ENV_FILE" logs -f --tail=100
}

stop_services() {
    log_step "停止服务..."
    $DC --env-file "$ENV_FILE" down
    log_info "服务已停止"
}

# ============================================================
# 主流程
# ============================================================

case "${1:-deploy}" in
    deploy)
        log_info "======== ScanStruct 完整部署 ========"
        check_docker
        check_env
        create_volumes
        build_and_start
        init_database
        configure_firewall
        show_status
        echo ""
        log_info "======== 部署完成! ========"
        log_info "访问地址: http://121.40.53.229:8900"
        log_info "管理命令: ./deploy.sh --status / --logs / --stop / --update"
        ;;
    --update)
        check_docker
        log_info "======== 更新部署 ========"
        $DC --env-file "$ENV_FILE" up -d --build api worker
        log_info "更新完成"
        show_status
        ;;
    --stop)
        stop_services
        ;;
    --status)
        show_status
        ;;
    --logs)
        show_logs
        ;;
    --init-db)
        init_database
        ;;
    *)
        echo "Usage: $0 {deploy|--update|--stop|--status|--logs|--init-db}"
        exit 1
        ;;
esac
