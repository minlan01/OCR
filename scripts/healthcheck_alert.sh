#!/bin/bash
# ============================================================
# ScanStruct 健康检查 + 自动重启脚本
# ============================================================
# 用法:
#   1. 放到服务器 /root/OCR/scripts/ 目录
#   2. 添加 cron 任务（每5分钟执行一次）:
#      crontab -e
#      */5 * * * * /root/OCR/scripts/healthcheck_alert.sh >> /root/OCR/logs/healthcheck.log 2>&1
#
# 功能:
#   - 检查 API health 端点
#   - 连续3次失败则自动重启 api + worker 容器
#   - 支持企业微信/钉钉 webhook 通知（可选）
# ============================================================

set -euo pipefail

# ─── 配置 ──────────────────────────────────────────────────────────────────

HEALTH_URL="http://localhost:8900/api/v1/health"
COMPOSE_DIR="/root/OCR"
ENV_FILE=".env.production"
MAX_RETRIES=3
RETRY_INTERVAL=30  # 秒

# 通知 webhook（可选，留空则不通知）
# 企业微信: https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY
# 钉钉: https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN
ALERT_WEBHOOK="${ALERT_WEBHOOK:-}"

# ─── 函数 ──────────────────────────────────────────────────────────────────

send_alert() {
    local message="$1"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ALERT: $message"

    if [ -n "$ALERT_WEBHOOK" ]; then
        curl -sf "$ALERT_WEBHOOK" \
            -H 'Content-Type: application/json' \
            -d "{\"msgtype\":\"text\",\"text\":{\"content\":\"⚠️ ScanStruct 告警: $message\"}}" \
            > /dev/null 2>&1 || true
    fi
}

restart_services() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 重启 API + Worker..."
    cd "$COMPOSE_DIR"
    docker compose --env-file "$ENV_FILE" restart api worker
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 重启完成"

    # 等待 30 秒后验证
    sleep 30
    if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
        send_alert "服务重启成功，API health 恢复正常"
    else
        send_alert "服务重启后仍不健康，请人工介入！"
    fi
}

# ─── 主逻辑 ────────────────────────────────────────────────────────────────

fail_count=0

for i in $(seq 1 $MAX_RETRIES); do
    if curl -sf --max-time 10 "$HEALTH_URL" > /dev/null 2>&1; then
        # 健康检查通过
        if [ "$i" -gt 1 ]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Health OK (attempt $i/$MAX_RETRIES)"
        fi
        exit 0
    fi

    fail_count=$((fail_count + 1))
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Health check failed ($fail_count/$MAX_RETRIES)"

    if [ "$fail_count" -lt "$MAX_RETRIES" ]; then
        sleep "$RETRY_INTERVAL"
    fi
done

# 连续 MAX_RETRIES 次失败
send_alert "API 连续 ${MAX_RETRIES} 次健康检查失败，正在自动重启..."
restart_services
