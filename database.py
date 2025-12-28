"""
WyzeGuardi Database Module
SQLite-based persistence layer for system state, logs, and historical data.
"""

import sqlite3
import os
import logging
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import Optional, Dict, List, Any
import json
import pytz

# Import crypto for encrypted settings
try:
    from crypto import get_crypto
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    logging.warning("Crypto module not available - encrypted settings disabled")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Timezone configuration
TIMEZONE = pytz.timezone(os.getenv('TZ', 'America/New_York'))

# SQL Injection Prevention: Whitelists for dynamic SQL
# These define allowed table and column names to prevent SQL injection

ALLOWED_TABLES = {
    'system_state', 'activity_log', 'heartbeat_history',
    'camera_state_history', 'state_machine_history',
    'api_health_history', 'database_health_log', 'schedules', 'devices', 'users'
}

ALLOWED_SYSTEM_STATE_COLUMNS = {
    'mode', 'cameras', 'presence_status', 'manual_override_until',
    'last_heartbeat', 'cameras_last_on', 'cameras_last_off',
    'state_reason', 'updated_at'
}

ALLOWED_SCHEDULE_COLUMNS = {
    'name', 'days_of_week', 'start_time', 'end_time',
    'cameras_state', 'enabled', 'created_at', 'updated_at'
}


def validate_table_name(table: str) -> str:
    """
    Validate table name against whitelist to prevent SQL injection.

    Args:
        table: Table name to validate

    Returns:
        str: Validated table name

    Raises:
        ValueError: If table name not in whitelist
    """
    if table not in ALLOWED_TABLES:
        raise ValueError(f"Invalid table name: {table}")
    return table


def validate_column_names(columns: List[str], allowed_columns: set) -> List[str]:
    """
    Validate column names against whitelist to prevent SQL injection.

    Args:
        columns: List of column names to validate
        allowed_columns: Set of allowed column names

    Returns:
        List[str]: Validated column names

    Raises:
        ValueError: If any column name not in whitelist
    """
    for col in columns:
        if col not in allowed_columns:
            raise ValueError(f"Invalid column name: {col}")
    return columns

# Database path (relative to script directory)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(SCRIPT_DIR, 'wyze_automation.db')
DATABASE_PATH = os.getenv('DATABASE_PATH', DEFAULT_DB_PATH)

# Data retention policies (days)
RETENTION_POLICIES = {
    'heartbeat_history': 30,
    'camera_state_history': 90,
    'state_machine_history': 60,
    'api_health_history': 30,
    'database_health_log': 7,
    'activity_log': 90
}


@contextmanager
def get_db_connection():
    """Context manager for database connections with automatic commit/rollback."""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        if conn:
            conn.close()


def init_db():
    """Initialize database with all required tables and indexes."""
    logger.info(f"Initializing database at {DATABASE_PATH}")
    start_time = datetime.now()

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 1. system_state table (single row - current state)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                mode TEXT NOT NULL DEFAULT 'schedule',
                cameras TEXT NOT NULL DEFAULT 'unknown',
                presence_status TEXT DEFAULT 'UNKNOWN',
                last_heartbeat TIMESTAMP,
                manual_override_until TIMESTAMP,
                reason TEXT,
                last_state_change TIMESTAMP,
                last_camera_action TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Initialize with default state if empty
        cursor.execute('SELECT COUNT(*) FROM system_state')
        if cursor.fetchone()[0] == 0:
            cursor.execute('''
                INSERT INTO system_state (id, mode, cameras, presence_status, reason)
                VALUES (1, 'schedule', 'unknown', 'UNKNOWN', 'System initialized')
            ''')

        # 2. activity_log table (high-level events)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                type TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                details TEXT
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON activity_log(timestamp DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_type ON activity_log(type)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_level ON activity_log(level)')

        # 3. heartbeat_history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS heartbeat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                source_ip TEXT,
                device_id TEXT,
                response_time_ms INTEGER
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_heartbeat_timestamp ON heartbeat_history(timestamp DESC)')

        # 4. camera_state_history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS camera_state_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                camera_id TEXT NOT NULL,
                camera_name TEXT,
                action TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                success BOOLEAN NOT NULL,
                error_message TEXT,
                response_time_ms INTEGER
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_camera_history ON camera_state_history(timestamp DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_camera_id ON camera_state_history(camera_id)')

        # 5. state_machine_history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS state_machine_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                from_mode TEXT,
                to_mode TEXT NOT NULL,
                from_cameras TEXT,
                to_cameras TEXT NOT NULL,
                presence_status TEXT,
                reason TEXT NOT NULL
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_state_machine_timestamp ON state_machine_history(timestamp DESC)')

        # 6. api_health_history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS api_health_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                endpoint TEXT NOT NULL,
                success BOOLEAN NOT NULL,
                response_time_ms INTEGER,
                error_message TEXT
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_api_health_timestamp ON api_health_history(timestamp DESC)')

        # 7. database_health_log table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS database_health_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                operation TEXT NOT NULL,
                duration_ms INTEGER,
                success BOOLEAN NOT NULL,
                error_message TEXT
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_db_health_timestamp ON database_health_log(timestamp DESC)')

        # 8. schedules table (custom schedules)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                days_of_week TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                cameras_state TEXT NOT NULL,
                enabled BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 9. devices table (registered devices for presence detection)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY,
                device_name TEXT NOT NULL,
                device_type TEXT DEFAULT 'phone',
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_ip TEXT,
                enabled BOOLEAN DEFAULT 1,
                notes TEXT,
                detection_method TEXT DEFAULT 'both'
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_devices_last_seen ON devices(last_seen DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_devices_enabled ON devices(enabled)')

        # Add detection_method column if it doesn't exist (migration)
        try:
            cursor.execute("ALTER TABLE devices ADD COLUMN detection_method TEXT DEFAULT 'both'")
            logger.info("Added detection_method column to devices table")
        except sqlite3.OperationalError as e:
            if 'duplicate column name' not in str(e).lower():
                logger.warning(f"Could not add detection_method column: {e}")

        # 10. settings table (key-value config store)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                description TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()

    duration = (datetime.now() - start_time).total_seconds() * 1000
    logger.info(f"Database initialized successfully in {duration:.2f}ms")

    # Log database initialization
    log_database_health('init', duration, True)


# =============================================================================
# System State Functions
# =============================================================================

def get_system_state() -> Dict[str, Any]:
    """Retrieve current system state."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM system_state WHERE id = 1')
        row = cursor.fetchone()
        if row:
            return dict(row)
        return {}


def save_system_state(updates: Dict[str, Any]) -> bool:
    """
    Update system state with provided values.

    Args:
        updates: Dictionary of column names and values to update

    Returns:
        True if successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Build dynamic UPDATE query
            updates['updated_at'] = datetime.now().isoformat()

            # SQL Injection Prevention: Validate column names
            validate_column_names(list(updates.keys()), ALLOWED_SYSTEM_STATE_COLUMNS)

            columns = ', '.join([f"{k} = ?" for k in updates.keys()])
            values = list(updates.values())

            cursor.execute(f'UPDATE system_state SET {columns} WHERE id = 1', values)

            return True
    except Exception as e:
        logger.error(f"Failed to save system state: {e}")
        return False


# =============================================================================
# Activity Log Functions
# =============================================================================

def add_activity_log(log_type: str, level: str, message: str, details: Optional[Dict] = None) -> bool:
    """
    Add entry to activity log.

    Args:
        log_type: Type of event (PRESENCE, CAMERA, API, SYSTEM, MAINTENANCE)
        level: Severity level (info, warn, error)
        message: Human-readable message
        details: Optional dictionary of additional data (stored as JSON)

    Returns:
        True if successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            details_json = json.dumps(details) if details else None
            cursor.execute('''
                INSERT INTO activity_log (type, level, message, details)
                VALUES (?, ?, ?, ?)
            ''', (log_type, level, message, details_json))
            return True
    except Exception as e:
        logger.error(f"Failed to add activity log: {e}")
        return False


def get_activity_log(limit: int = 100, log_type: Optional[str] = None,
                      level: Optional[str] = None, offset: int = 0) -> List[Dict]:
    """
    Retrieve activity log entries with optional filtering.

    Args:
        limit: Maximum number of entries to return
        log_type: Filter by type (optional)
        level: Filter by level (optional)
        offset: Number of entries to skip (for pagination)

    Returns:
        List of log entries as dictionaries
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        query = 'SELECT * FROM activity_log WHERE 1=1'
        params = []

        if log_type:
            query += ' AND type = ?'
            params.append(log_type)

        if level:
            query += ' AND level = ?'
            params.append(level)

        query += ' ORDER BY timestamp DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])

        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


# =============================================================================
# Heartbeat Functions
# =============================================================================

def log_heartbeat(source_ip: str, device_id: Optional[str] = None,
                  response_time_ms: Optional[int] = None) -> bool:
    """
    Log a heartbeat event.

    Args:
        source_ip: IP address of heartbeat source
        device_id: Optional device identifier
        response_time_ms: Optional response time in milliseconds

    Returns:
        True if successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO heartbeat_history (source_ip, device_id, response_time_ms)
                VALUES (?, ?, ?)
            ''', (source_ip, device_id, response_time_ms))
            return True
    except Exception as e:
        logger.error(f"Failed to log heartbeat: {e}")
        return False


def get_heartbeat_stats(hours: int = 24) -> Dict[str, Any]:
    """
    Get heartbeat statistics for the specified time window.

    Args:
        hours: Number of hours to look back (default: 24)

    Returns:
        Dictionary with heartbeat statistics
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cutoff = datetime.now() - timedelta(hours=hours)

        # Count heartbeats
        cursor.execute('''
            SELECT COUNT(*) as count
            FROM heartbeat_history
            WHERE timestamp >= ?
        ''', (cutoff,))
        count = cursor.fetchone()[0]

        # Get last heartbeat
        cursor.execute('''
            SELECT timestamp FROM heartbeat_history
            ORDER BY timestamp DESC LIMIT 1
        ''')
        last_row = cursor.fetchone()
        last_heartbeat = last_row[0] if last_row else None

        # Calculate average interval (if > 1 heartbeat)
        avg_interval = None
        if count > 1:
            cursor.execute('''
                SELECT
                    (julianday(MAX(timestamp)) - julianday(MIN(timestamp))) * 24 * 60 / (COUNT(*) - 1) as avg_min
                FROM heartbeat_history
                WHERE timestamp >= ?
            ''', (cutoff,))
            avg_interval = cursor.fetchone()[0]

        return {
            'count': count,
            'last_heartbeat': last_heartbeat,
            'average_interval_minutes': round(avg_interval, 2) if avg_interval else None,
            'hours_analyzed': hours
        }


# =============================================================================
# Camera State Functions
# =============================================================================

def log_camera_action(camera_id: str, camera_name: str, action: str, trigger_type: str,
                       success: bool, error_message: Optional[str] = None,
                       response_time_ms: Optional[int] = None) -> bool:
    """
    Log a camera control action.

    Args:
        camera_id: Camera identifier (MAC address)
        camera_name: Human-readable camera name
        action: Action taken ('on' or 'off')
        trigger_type: What triggered this action ('manual', 'presence', 'schedule')
        success: Whether the action succeeded
        error_message: Optional error message if failed
        response_time_ms: Optional API response time

    Returns:
        True if successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO camera_state_history
                (camera_id, camera_name, action, trigger_type, success, error_message, response_time_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (camera_id, camera_name, action, trigger_type, success, error_message, response_time_ms))
            return True
    except Exception as e:
        logger.error(f"Failed to log camera action: {e}")
        return False


def get_camera_toggle_stats(hours: int = 24) -> Dict[str, Any]:
    """
    Get camera toggle statistics.

    Args:
        hours: Number of hours to look back

    Returns:
        Dictionary with toggle statistics by trigger type
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cutoff = datetime.now() - timedelta(hours=hours)

        # Total toggles
        cursor.execute('''
            SELECT COUNT(*) FROM camera_state_history
            WHERE timestamp >= ?
        ''', (cutoff,))
        total = cursor.fetchone()[0]

        # By trigger type
        cursor.execute('''
            SELECT trigger_type, COUNT(*) as count
            FROM camera_state_history
            WHERE timestamp >= ?
            GROUP BY trigger_type
        ''', (cutoff,))
        by_trigger = {row[0]: row[1] for row in cursor.fetchall()}

        # Success rate
        cursor.execute('''
            SELECT
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes,
                COUNT(*) as total
            FROM camera_state_history
            WHERE timestamp >= ?
        ''', (cutoff,))
        row = cursor.fetchone()
        success_rate = (row[0] / row[1] * 100) if row[1] > 0 else 0

        return {
            'total_toggles': total,
            'by_trigger_type': by_trigger,
            'success_rate_percent': round(success_rate, 2),
            'hours_analyzed': hours
        }


# =============================================================================
# State Machine Functions
# =============================================================================

def log_state_transition(from_mode: str, to_mode: str, from_cameras: str,
                          to_cameras: str, presence_status: str, reason: str) -> bool:
    """
    Log a state machine transition.

    Args:
        from_mode: Previous mode
        to_mode: New mode
        from_cameras: Previous camera state
        to_cameras: New camera state
        presence_status: Current presence status
        reason: Human-readable reason for transition

    Returns:
        True if successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO state_machine_history
                (from_mode, to_mode, from_cameras, to_cameras, presence_status, reason)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (from_mode, to_mode, from_cameras, to_cameras, presence_status, reason))
            return True
    except Exception as e:
        logger.error(f"Failed to log state transition: {e}")
        return False


def get_state_machine_stats(hours: int = 24) -> Dict[str, Any]:
    """
    Get state machine transition statistics.

    Args:
        hours: Number of hours to look back

    Returns:
        Dictionary with transition statistics
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cutoff = datetime.now() - timedelta(hours=hours)

        cursor.execute('''
            SELECT COUNT(*) FROM state_machine_history
            WHERE timestamp >= ?
        ''', (cutoff,))
        total_transitions = cursor.fetchone()[0]

        cursor.execute('''
            SELECT to_mode, COUNT(*) as count
            FROM state_machine_history
            WHERE timestamp >= ?
            GROUP BY to_mode
        ''', (cutoff,))
        by_mode = {row[0]: row[1] for row in cursor.fetchall()}

        return {
            'total_transitions': total_transitions,
            'by_mode': by_mode,
            'hours_analyzed': hours
        }


# =============================================================================
# API Health Functions
# =============================================================================

def log_api_call(endpoint: str, success: bool, response_time_ms: Optional[int] = None,
                 error_message: Optional[str] = None) -> bool:
    """
    Log an API call for health monitoring.

    Args:
        endpoint: API endpoint called (e.g., 'turn_on', 'turn_off')
        success: Whether the call succeeded
        response_time_ms: Optional response time
        error_message: Optional error message if failed

    Returns:
        True if successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO api_health_history (endpoint, success, response_time_ms, error_message)
                VALUES (?, ?, ?, ?)
            ''', (endpoint, success, response_time_ms, error_message))
            return True
    except Exception as e:
        logger.error(f"Failed to log API call: {e}")
        return False


def get_api_health_stats(hours: int = 24) -> Dict[str, Any]:
    """
    Get API health statistics.

    Args:
        hours: Number of hours to look back

    Returns:
        Dictionary with API health metrics
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cutoff = datetime.now() - timedelta(hours=hours)

        # Success rate
        cursor.execute('''
            SELECT
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes,
                COUNT(*) as total
            FROM api_health_history
            WHERE timestamp >= ?
        ''', (cutoff,))
        row = cursor.fetchone()
        success_rate = (row[0] / row[1] * 100) if row[1] > 0 else 0

        # Average response time (successful calls only)
        cursor.execute('''
            SELECT AVG(response_time_ms)
            FROM api_health_history
            WHERE timestamp >= ? AND success = 1 AND response_time_ms IS NOT NULL
        ''', (cutoff,))
        avg_response_time = cursor.fetchone()[0]

        # Last successful call
        cursor.execute('''
            SELECT timestamp FROM api_health_history
            WHERE success = 1
            ORDER BY timestamp DESC LIMIT 1
        ''')
        last_row = cursor.fetchone()
        last_success = last_row[0] if last_row else None

        return {
            'uptime_percent': round(success_rate, 2),
            'average_response_time_ms': round(avg_response_time, 2) if avg_response_time else None,
            'last_successful_call': last_success,
            'hours_analyzed': hours
        }


# =============================================================================
# Database Health Functions
# =============================================================================

def log_database_health(operation: str, duration_ms: float, success: bool,
                         error_message: Optional[str] = None) -> bool:
    """
    Log database health check operation.

    Args:
        operation: Type of operation ('read', 'write', 'cleanup', 'init')
        duration_ms: Duration in milliseconds
        success: Whether operation succeeded
        error_message: Optional error message

    Returns:
        True if successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO database_health_log (operation, duration_ms, success, error_message)
                VALUES (?, ?, ?, ?)
            ''', (operation, duration_ms, success, error_message))
            return True
    except Exception as e:
        logger.error(f"Failed to log database health: {e}")
        return False


def check_database_health() -> Dict[str, Any]:
    """
    Perform comprehensive database health check.

    Returns:
        Dictionary with health metrics
    """
    start_time = datetime.now()
    health = {
        'connected': False,
        'response_time_ms': None,
        'file_size_mb': None,
        'table_counts': {},
        'last_write': None,
        'errors': []
    }

    try:
        # Check connection and response time
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Simple read test
            cursor.execute('SELECT 1')
            health['connected'] = True

            # Get file size
            if os.path.exists(DATABASE_PATH):
                health['file_size_mb'] = round(os.path.getsize(DATABASE_PATH) / (1024 * 1024), 2)

            # Get table row counts
            tables = ['system_state', 'activity_log', 'heartbeat_history',
                      'camera_state_history', 'state_machine_history',
                      'api_health_history', 'database_health_log']

            for table in tables:
                # SQL Injection Prevention: Validate table name
                validated_table = validate_table_name(table)
                cursor.execute(f'SELECT COUNT(*) FROM {validated_table}')
                health['table_counts'][table] = cursor.fetchone()[0]

            # Get last write timestamp (from activity_log)
            cursor.execute('SELECT timestamp FROM activity_log ORDER BY timestamp DESC LIMIT 1')
            row = cursor.fetchone()
            health['last_write'] = row[0] if row else None

    except Exception as e:
        health['errors'].append(str(e))
        logger.error(f"Database health check failed: {e}")

    health['response_time_ms'] = round((datetime.now() - start_time).total_seconds() * 1000, 2)

    # Log the health check
    log_database_health('health_check', health['response_time_ms'], health['connected'])

    return health


# =============================================================================
# Data Cleanup Functions
# =============================================================================

def cleanup_old_data() -> Dict[str, int]:
    """
    Remove old records according to retention policies.

    Returns:
        Dictionary with counts of deleted records per table
    """
    logger.info("Starting database cleanup...")
    deleted_counts = {}

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            for table, days in RETENTION_POLICIES.items():
                # SQL Injection Prevention: Validate table name
                validated_table = validate_table_name(table)
                cutoff = datetime.now() - timedelta(days=days)
                cursor.execute(f'DELETE FROM {validated_table} WHERE timestamp < ?', (cutoff,))
                deleted_counts[table] = cursor.rowcount
                logger.info(f"Deleted {cursor.rowcount} old records from {table} (older than {days} days)")

            # Vacuum database to reclaim space
            cursor.execute('VACUUM')

        # Log cleanup operation
        total_deleted = sum(deleted_counts.values())
        add_activity_log('MAINTENANCE', 'info',
                         f"Database cleanup completed: {total_deleted} records removed",
                         details=deleted_counts)

        return deleted_counts

    except Exception as e:
        logger.error(f"Database cleanup failed: {e}")
        add_activity_log('MAINTENANCE', 'error', f"Database cleanup failed: {e}")
        return deleted_counts


# =============================================================================
# Settings Functions
# =============================================================================

def get_setting(key: str) -> Optional[str]:
    """Retrieve a setting value by key."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
            row = cursor.fetchone()
            return row[0] if row else None
    except sqlite3.OperationalError:
        # Table doesn't exist yet (database not initialized)
        return None


def set_setting(key: str, value: str, description: Optional[str] = None) -> bool:
    """
    Set or update a setting.

    Args:
        key: Setting key
        value: Setting value
        description: Optional description

    Returns:
        True if successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO settings (key, value, description, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    description = COALESCE(excluded.description, description),
                    updated_at = excluded.updated_at
            ''', (key, value, description, datetime.now().isoformat()))
            return True
    except Exception as e:
        logger.error(f"Failed to set setting {key}: {e}")
        return False


def get_all_settings() -> Dict[str, str]:
    """Retrieve all settings as a dictionary."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT key, value FROM settings')
            return {row[0]: row[1] for row in cursor.fetchall()}
    except sqlite3.OperationalError:
        # Table doesn't exist yet (database not initialized)
        return {}


def set_encrypted_setting(key: str, value: str, description: Optional[str] = None) -> bool:
    """
    Set an encrypted setting (for sensitive data like passwords).

    Args:
        key: Setting key
        value: Plaintext value to encrypt and store
        description: Optional description

    Returns:
        True if successful, False otherwise
    """
    if not CRYPTO_AVAILABLE:
        logger.error("Cannot set encrypted setting - crypto module not available")
        return False

    try:
        crypto = get_crypto()
        encrypted_value = crypto.encrypt(value)
        return set_setting(key, encrypted_value, description)
    except Exception as e:
        logger.error(f"Failed to set encrypted setting {key}: {e}")
        return False


def get_encrypted_setting(key: str) -> Optional[str]:
    """
    Retrieve and decrypt an encrypted setting.

    Args:
        key: Setting key

    Returns:
        Decrypted value, or None if not found
    """
    if not CRYPTO_AVAILABLE:
        logger.error("Cannot get encrypted setting - crypto module not available")
        return None

    encrypted_value = get_setting(key)
    if not encrypted_value:
        return None

    try:
        crypto = get_crypto()
        return crypto.decrypt(encrypted_value)
    except Exception as e:
        logger.error(f"Failed to decrypt setting {key}: {e}")
        return None


def get_all_settings_decrypted() -> Dict[str, str]:
    """
    Get all settings with encrypted ones automatically decrypted.

    Returns:
        Dictionary of all settings (encrypted ones decrypted)
    """
    settings = get_all_settings()

    if not CRYPTO_AVAILABLE:
        return settings

    # List of keys that are encrypted
    encrypted_keys = [
        'wyze_email',
        'wyze_password',
        'wyze_api_key',
        'wyze_api_id',
        'wyze_totp_key',
        'webhook_secret'
    ]

    crypto = get_crypto()
    decrypted = {}

    for key, value in settings.items():
        if key in encrypted_keys and value:
            try:
                decrypted[key] = crypto.decrypt(value)
            except Exception:
                decrypted[key] = ''  # Failed to decrypt
        else:
            decrypted[key] = value

    return decrypted


def is_setup_complete() -> bool:
    """
    Check if initial setup has been completed.

    Returns:
        True if setup is complete, False otherwise
    """
    setup_flag = get_setting('setup_completed')
    return setup_flag == 'true'


def mark_setup_complete() -> bool:
    """
    Mark setup as completed.

    Returns:
        True if successful, False otherwise
    """
    return set_setting('setup_completed', 'true', 'Setup completion flag')


# =============================================================================
# Device Management Functions
# =============================================================================

def register_device(device_id: str, device_name: str, device_type: str = 'phone',
                   last_ip: Optional[str] = None, notes: Optional[str] = None) -> bool:
    """
    Register a new device or update existing device info.

    Args:
        device_id: Unique device identifier (e.g., UUID from phone)
        device_name: Human-readable device name
        device_type: Type of device (phone, tablet, etc.)
        last_ip: Last known IP address
        notes: Optional notes about device

    Returns:
        True if successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO devices (device_id, device_name, device_type, last_ip, notes, last_seen)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    device_name = excluded.device_name,
                    device_type = excluded.device_type,
                    last_ip = excluded.last_ip,
                    notes = COALESCE(excluded.notes, notes),
                    last_seen = excluded.last_seen
            ''', (device_id, device_name, device_type, last_ip, notes, datetime.now(TIMEZONE).isoformat()))
            return True
    except Exception as e:
        logger.error(f"Failed to register device {device_id}: {e}")
        return False


def update_device_last_seen(device_id: str, last_ip: Optional[str] = None) -> bool:
    """
    Update device's last seen timestamp and IP.

    Args:
        device_id: Device identifier
        last_ip: Last known IP address

    Returns:
        True if successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE devices
                SET last_seen = ?, last_ip = ?
                WHERE device_id = ?
            ''', (datetime.now(TIMEZONE).isoformat(), last_ip, device_id))
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to update device {device_id}: {e}")
        return False


def get_all_devices() -> List[Dict[str, Any]]:
    """
    Get all registered devices.

    Returns:
        List of device dictionaries
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM devices ORDER BY last_seen DESC')
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get devices: {e}")
        return []


def get_device(device_id: str) -> Optional[Dict[str, Any]]:
    """
    Get device by ID.

    Args:
        device_id: Device identifier

    Returns:
        Device dictionary or None
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM devices WHERE device_id = ?', (device_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get device {device_id}: {e}")
        return None


def update_device(device_id: str, updates: Dict[str, Any]) -> bool:
    """
    Update device properties.

    Args:
        device_id: Device identifier
        updates: Dictionary of fields to update

    Returns:
        True if successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Build dynamic UPDATE query
            columns = ', '.join([f"{k} = ?" for k in updates.keys()])
            values = list(updates.values()) + [device_id]

            sql = f'UPDATE devices SET {columns} WHERE device_id = ?'
            logger.info(f"Executing SQL: {sql} with values: {values}")

            cursor.execute(sql, values)
            rowcount = cursor.rowcount

            logger.info(f"Update affected {rowcount} rows for device_id={device_id}")

            if rowcount > 0:
                conn.commit()
                logger.info(f"Successfully updated device {device_id}")
                return True
            else:
                logger.warning(f"No device found with device_id={device_id}")
                return False
    except Exception as e:
        logger.error(f"Failed to update device {device_id}: {e}", exc_info=True)
        return False


def delete_device(device_id: str) -> bool:
    """
    Delete a device.

    Args:
        device_id: Device identifier

    Returns:
        True if successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM devices WHERE device_id = ?', (device_id,))
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to delete device {device_id}: {e}")
        return False


def is_device_reachable(ip_address: str, timeout: int = 1) -> bool:
    """
    Check if device is reachable on the network.

    Uses TCP port scanning for iOS devices (which block ICMP ping),
    tries multiple common iOS ports.

    Args:
        ip_address: IP address to check
        timeout: Timeout in seconds per port

    Returns:
        True if device responds on any port, False otherwise
    """
    import socket

    # Common iOS ports to check
    # 62078: iPhone Continuity/AirDrop
    # 5353: mDNS/Bonjour
    # 3689: DAAP (iTunes sharing)
    # Note: We just need to see if ANYTHING responds, not actually connect
    ports_to_try = [62078, 5353, 3689]

    for port in ports_to_try:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip_address, port))
            sock.close()

            # If connection was refused (111) or succeeded (0), device is online
            # If timed out or host unreachable, device is offline
            if result in [0, 111]:  # 0=connected, 111=connection refused (port closed but host alive)
                logger.debug(f"Device {ip_address} is reachable (port {port} responded)")
                return True
        except Exception as e:
            logger.debug(f"Port check failed for {ip_address}:{port}: {e}")
            continue

    logger.debug(f"Device {ip_address} is not reachable (no ports responded)")
    return False


def is_device_reachable_arp(ip_address: str, timeout: int = 1) -> bool:
    """
    Check if device is reachable using ARP (Layer 2 detection).

    More reliable than TCP port scanning for iOS devices because:
    - Works when phone is locked/sleeping
    - Cannot be blocked by iOS firewall
    - Faster (100ms vs 3-9s for port scanning)

    Args:
        ip_address: IP address to check
        timeout: Ping timeout in seconds

    Returns:
        True if device has MAC address in ARP table, False otherwise
    """
    import subprocess

    try:
        # Step 1: Refresh ARP cache with single ping
        ping_cmd = ['ping', '-c', '1', '-W', str(timeout), ip_address]
        subprocess.run(ping_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout+1)

        # Step 2: Query ARP table for MAC address
        arp_cmd = ['arp', '-n', ip_address]
        result = subprocess.run(arp_cmd, capture_output=True, text=True, timeout=2)

        # If MAC address present (not "incomplete"), device is online
        if 'incomplete' not in result.stdout.lower() and ip_address in result.stdout:
            logger.debug(f"ARP ✓ {ip_address}")
            return True
        else:
            logger.debug(f"ARP ✗ {ip_address}")
            return False

    except Exception as e:
        logger.debug(f"ARP check failed for {ip_address}: {e}")
        return False


def is_device_reachable_arp_3x(ip_address: str) -> bool:
    """
    Check device reachability using 3 ARP attempts with 2/3 success threshold.

    More robust than single ARP check:
    - Handles transient network failures
    - Tolerates single packet drops
    - Still fast (300-600ms total)
    - 66% threshold prevents false away detections

    Args:
        ip_address: IP address to check

    Returns:
        True if ≥2 out of 3 ARP checks succeed, False otherwise
    """
    successes = 0
    attempts = 3

    for i in range(attempts):
        if is_device_reachable_arp(ip_address, timeout=1):
            successes += 1
        logger.debug(f"ARP-3X {i+1}/{attempts}: {successes}/{i+1}")

    result = successes >= 2
    logger.info(f"{ip_address}: ARP-3X {'✓' if result else '✗'} ({successes}/{attempts})")
    return result


def get_online_devices(minutes: int = 10) -> List[Dict[str, Any]]:
    """
    Get devices that are currently online.

    Respects per-device detection_method setting with priority order:
    1. "arp_3x": 3-attempt ARP (2/3 success threshold) - most robust
    2. "arp": Single ARP check - fast and reliable
    3. "ping": TCP port scanning - legacy fallback
    4. "heartbeat": Timestamp-based - passive detection

    Pure modes (arp, arp_3x, ping, heartbeat):
    - Uses ONLY specified method
    - If method fails, device is offline (no fallback)

    Hybrid modes (arp_and_heartbeat, both):
    - Tries primary method first
    - Falls back to secondary if primary fails

    Args:
        minutes: Number of minutes to consider device online (for heartbeat method)

    Returns:
        List of online device dictionaries
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM devices WHERE enabled = 1')
            all_devices = [dict(row) for row in cursor.fetchall()]

            online_devices = []
            for device in all_devices:
                is_online = False
                detection_method = device.get('detection_method', 'both')
                device_ip = device.get('last_ip')

                # Priority 1: ARP-3X (3-attempt robust mode)
                if detection_method == 'arp_3x' and device_ip:
                    is_online = is_device_reachable_arp_3x(device_ip)
                    if is_online:
                        logger.info(f"✓ '{device['device_name']}' ONLINE via ARP-3X ({device_ip})")
                        online_devices.append(device)
                        continue  # Pure mode: don't check other methods

                # Priority 2: ARP (single check)
                elif detection_method == 'arp' and device_ip:
                    is_online = is_device_reachable_arp(device_ip)
                    if is_online:
                        logger.info(f"✓ '{device['device_name']}' ONLINE via ARP ({device_ip})")
                        online_devices.append(device)
                        continue  # Pure mode: don't check other methods

                # Priority 3: Ping (TCP port scanning - legacy)
                elif detection_method == 'ping' and device_ip:
                    is_online = is_device_reachable(device_ip)
                    if is_online:
                        logger.info(f"✓ '{device['device_name']}' ONLINE via PING ({device_ip})")
                        online_devices.append(device)
                        continue  # Pure mode: don't check other methods

                # Priority 4: Heartbeat (timestamp-based)
                elif detection_method == 'heartbeat' and device.get('last_seen'):
                    cutoff = datetime.now(TIMEZONE) - timedelta(minutes=minutes)
                    last_seen = datetime.fromisoformat(device['last_seen'])
                    if last_seen >= cutoff:
                        is_online = True
                        logger.info(f"✓ '{device['device_name']}' ONLINE via HEARTBEAT")
                        online_devices.append(device)
                        continue  # Pure mode: don't check other methods

                # Hybrid mode: arp_and_heartbeat
                elif detection_method == 'arp_and_heartbeat':
                    # Try ARP first
                    if device_ip and is_device_reachable_arp(device_ip):
                        logger.info(f"✓ '{device['device_name']}' ONLINE via ARP ({device_ip})")
                        online_devices.append(device)
                        continue
                    # Fallback to heartbeat
                    if device.get('last_seen'):
                        cutoff = datetime.now(TIMEZONE) - timedelta(minutes=minutes)
                        last_seen = datetime.fromisoformat(device['last_seen'])
                        if last_seen >= cutoff:
                            logger.info(f"✓ '{device['device_name']}' ONLINE via HEARTBEAT (ARP failed, heartbeat fallback)")
                            online_devices.append(device)
                            continue

                # Legacy hybrid mode: both (ping or heartbeat)
                elif detection_method == 'both':
                    # Try ping first
                    if device_ip and is_device_reachable(device_ip):
                        logger.info(f"✓ '{device['device_name']}' ONLINE via PING ({device_ip})")
                        online_devices.append(device)
                        continue
                    # Fallback to heartbeat
                    if device.get('last_seen'):
                        cutoff = datetime.now(TIMEZONE) - timedelta(minutes=minutes)
                        last_seen = datetime.fromisoformat(device['last_seen'])
                        if last_seen >= cutoff:
                            logger.info(f"✓ '{device['device_name']}' ONLINE via HEARTBEAT (ping failed, heartbeat fallback)")
                            online_devices.append(device)
                            continue

            return online_devices
    except Exception as e:
        logger.error(f"Failed to get online devices: {e}")
        return []


def get_device_last_heartbeats() -> Dict[str, str]:
    """
    Get the last heartbeat timestamp for each device.

    Returns:
        Dictionary mapping device_id to last heartbeat timestamp
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT device_id, MAX(timestamp) as last_heartbeat
                FROM heartbeat_history
                WHERE device_id IS NOT NULL
                GROUP BY device_id
            ''')
            return {row['device_id']: row['last_heartbeat'] for row in cursor.fetchall()}
    except Exception as e:
        logger.error(f"Failed to get device last heartbeats: {e}")
        return {}


# =============================================================================
# Schedule Management Functions
# =============================================================================

def create_schedule(name: str, days_of_week: str, start_time: str, end_time: str,
                   cameras_state: str, enabled: bool = True) -> Optional[int]:
    """
    Create a new schedule.

    Args:
        name: Schedule name
        days_of_week: Comma-separated day numbers (0=Monday, 6=Sunday) e.g., "0,1,2,3,4"
        start_time: Start time in HH:MM format
        end_time: End time in HH:MM format
        cameras_state: "on" or "off"
        enabled: Whether schedule is active

    Returns:
        Schedule ID if successful, None otherwise
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO schedules (name, days_of_week, start_time, end_time, cameras_state, enabled)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (name, days_of_week, start_time, end_time, cameras_state, enabled))
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"Failed to create schedule: {e}")
        return None


def get_all_schedules() -> List[Dict[str, Any]]:
    """
    Get all schedules.

    Returns:
        List of schedule dictionaries
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM schedules ORDER BY created_at DESC')
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get schedules: {e}")
        return []


def get_schedule(schedule_id: int) -> Optional[Dict[str, Any]]:
    """
    Get schedule by ID.

    Args:
        schedule_id: Schedule ID

    Returns:
        Schedule dictionary or None
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM schedules WHERE id = ?', (schedule_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get schedule {schedule_id}: {e}")
        return None


def update_schedule(schedule_id: int, updates: Dict[str, Any]) -> bool:
    """
    Update schedule properties.

    Args:
        schedule_id: Schedule ID
        updates: Dictionary of fields to update

    Returns:
        True if successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Build dynamic UPDATE query
            # SQL Injection Prevention: Validate column names
            validate_column_names(list(updates.keys()), ALLOWED_SCHEDULE_COLUMNS)

            columns = ', '.join([f"{k} = ?" for k in updates.keys()])
            values = list(updates.values()) + [schedule_id]

            cursor.execute(f'UPDATE schedules SET {columns} WHERE id = ?', values)
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to update schedule {schedule_id}: {e}")
        return False


def delete_schedule(schedule_id: int) -> bool:
    """
    Delete a schedule.

    Args:
        schedule_id: Schedule ID

    Returns:
        True if successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM schedules WHERE id = ?', (schedule_id,))
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to delete schedule {schedule_id}: {e}")
        return False


def get_active_schedules_for_time(day_of_week: int, current_time: str) -> List[Dict[str, Any]]:
    """
    Get schedules active for a specific day and time.

    Args:
        day_of_week: Day number (0=Monday, 6=Sunday)
        current_time: Time in HH:MM format

    Returns:
        List of active schedule dictionaries
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM schedules
                WHERE enabled = 1
                ORDER BY start_time
            ''')

            all_schedules = [dict(row) for row in cursor.fetchall()]
            active = []

            for schedule in all_schedules:
                # Check if current day is in schedule's days_of_week
                days = [int(d.strip()) for d in schedule['days_of_week'].split(',')]
                if day_of_week not in days:
                    continue

                # Check if current time is within schedule window
                if schedule['start_time'] <= current_time < schedule['end_time']:
                    active.append(schedule)

            return active
    except Exception as e:
        logger.error(f"Failed to get active schedules: {e}")
        return []


# =============================================================================
# Module Initialization
# =============================================================================

if __name__ == '__main__':
    # If run directly, initialize the database
    print(f"Initializing database at {DATABASE_PATH}")
    init_db()
    print("Database initialization complete!")

    # Show database health
    health = check_database_health()
    print(f"\nDatabase Health:")
    print(f"  Connected: {health['connected']}")
    print(f"  Response Time: {health['response_time_ms']}ms")
    print(f"  File Size: {health['file_size_mb']} MB")
    print(f"  Table Counts: {health['table_counts']}")
