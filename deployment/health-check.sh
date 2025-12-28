#!/bin/bash
################################################################################
# WyzeGuardi Health Check Script
#
# Checks service status and HTTP endpoint health.
# Restarts service if unhealthy.
# Runs via cron every 5 minutes.
################################################################################

SERVICE_NAME="wyze-automation"
ENDPOINT="http://localhost:5000/status"
LOG_FILE="/opt/wyze-automation/health-check.log"
MAX_RETRIES=3

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Check if service is running
if ! systemctl is-active --quiet $SERVICE_NAME; then
    log "ERROR: Service $SERVICE_NAME is not running. Starting..."
    systemctl start $SERVICE_NAME
    sleep 5

    if systemctl is-active --quiet $SERVICE_NAME; then
        log "SUCCESS: Service started successfully."
    else
        log "CRITICAL: Failed to start service. Manual intervention required."
        exit 1
    fi
fi

# Check HTTP endpoint
response=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 $ENDPOINT 2>/dev/null || echo "000")

if [ "$response" = "200" ]; then
    log "OK: Health check passed (HTTP $response)"
    exit 0
else
    log "WARNING: Health check failed (HTTP $response). Retrying..."

    # Retry logic
    for i in $(seq 1 $MAX_RETRIES); do
        sleep 2
        response=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 $ENDPOINT 2>/dev/null || echo "000")

        if [ "$response" = "200" ]; then
            log "OK: Health check passed after retry $i"
            exit 0
        fi

        log "WARNING: Retry $i failed (HTTP $response)"
    done

    # All retries failed, restart service
    log "ERROR: All retries failed. Restarting service..."
    systemctl restart $SERVICE_NAME
    sleep 5

    response=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 $ENDPOINT 2>/dev/null || echo "000")

    if [ "$response" = "200" ]; then
        log "SUCCESS: Service restarted successfully"
        exit 0
    else
        log "CRITICAL: Service restart failed. Manual intervention required."
        exit 1
    fi
fi
