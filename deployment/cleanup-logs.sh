#!/bin/bash
################################################################################
# WyzeGuardi Cleanup Script
#
# Performs database cleanup (removes old records) and log rotation.
# Runs via cron daily at 3 AM.
################################################################################

INSTALL_DIR="/opt/wyze-automation"
LOG_FILE="$INSTALL_DIR/cleanup.log"
PYTHON_BIN="$INSTALL_DIR/venv/bin/python3"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "=== Starting cleanup ==="

# Database cleanup
log "Running database cleanup..."
cd "$INSTALL_DIR"

$PYTHON_BIN -c "
from database import cleanup_old_data
result = cleanup_old_data()
print(f'Deleted records: {result}')
" 2>&1 | tee -a "$LOG_FILE"

# Log file rotation (keep last 30 days)
log "Rotating application logs..."

if [ -f "$INSTALL_DIR/app.log" ]; then
    APP_LOG_SIZE=$(stat -f%z "$INSTALL_DIR/app.log" 2>/dev/null || stat -c%s "$INSTALL_DIR/app.log" 2>/dev/null || echo 0)

    if [ "$APP_LOG_SIZE" -gt 10485760 ]; then  # 10 MB
        log "Application log exceeded 10 MB, rotating..."
        mv "$INSTALL_DIR/app.log" "$INSTALL_DIR/app.log.$(date +%Y%m%d-%H%M%S)"

        # Keep only last 5 rotated logs
        ls -t "$INSTALL_DIR"/app.log.* 2>/dev/null | tail -n +6 | xargs rm -f 2>/dev/null
        log "Log rotation complete"
    fi
fi

# Clean old health check logs (keep last 7 days)
if [ -f "$INSTALL_DIR/health-check.log" ]; then
    HEALTH_LOG_SIZE=$(stat -f%z "$INSTALL_DIR/health-check.log" 2>/dev/null || stat -c%s "$INSTALL_DIR/health-check.log" 2>/dev/null || echo 0)

    if [ "$HEALTH_LOG_SIZE" -gt 5242880 ]; then  # 5 MB
        log "Health check log exceeded 5 MB, rotating..."
        mv "$INSTALL_DIR/health-check.log" "$INSTALL_DIR/health-check.log.old"
        touch "$INSTALL_DIR/health-check.log"
    fi
fi

# Clean old cleanup logs (keep last 30 entries)
if [ -f "$LOG_FILE" ]; then
    tail -n 1000 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
fi

log "=== Cleanup complete ==="
