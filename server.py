"""
WyzeGuardi Server
Flask application with state machine, Wyze API integration, and web dashboard.
"""

import os
import logging
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
import pytz

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_wtf.csrf import CSRFProtect
from apscheduler.schedulers.background import BackgroundScheduler
import psutil

# Import Wyze SDK
try:
    from wyze_sdk import Client as WyzeClient
    from wyze_sdk.errors import WyzeApiError
    WYZE_AVAILABLE = True
except ImportError:
    WYZE_AVAILABLE = False
    logging.warning("Wyze SDK not available. Running in mock mode.")

# Import local modules
import database as db
from config import get_config, reload_config
from crypto import get_crypto
import auth

# =============================================================================
# Configuration
# =============================================================================

# Initialize configuration manager
config = get_config()

# Flask configuration
FLASK_PORT = config.get('flask_port', 5000)
FLASK_HOST = config.get('flask_host', '0.0.0.0')

# Flask secret key (persistent across restarts)
# Load from database or generate new one
flask_secret = db.get_setting('flask_secret_key')
if not flask_secret:
    flask_secret = secrets.token_hex(32)
    db.set_setting('flask_secret_key', flask_secret, 'Flask session secret key')
SECRET_KEY = flask_secret

# Logging configuration
LOG_LEVEL = config.get('log_level', 'INFO')
LOG_FILE = config.get('log_file', 'app.log')

# Configure logging (relative to script directory)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE_PATH = os.path.join(SCRIPT_DIR, LOG_FILE)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE_PATH),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Get config values (will be empty if setup not complete)
WYZE_EMAIL = config.get('wyze_email', '')
WYZE_PASSWORD = config.get('wyze_password', '')
WYZE_API_KEY = config.get('wyze_api_key', '')
WYZE_API_ID = config.get('wyze_api_id', '')
WYZE_TOTP_KEY = config.get('wyze_totp_key', '')
WEBHOOK_SECRET = config.get('webhook_secret', '')
TIMEZONE = config.get('timezone', 'America/New_York')
HOME_THRESHOLD = config.get('home_threshold', 10)
AWAY_THRESHOLD = config.get('away_threshold', 30)
MANUAL_OVERRIDE_DURATION = config.get('manual_override_duration', 2)
STATE_MACHINE_INTERVAL = config.get('state_machine_interval', 5)
WEEKDAY_HOME_START = config.get('weekday_home_start', 8)
WEEKDAY_HOME_END = config.get('weekday_home_end', 18)
WEEKEND_HOME_START = config.get('weekend_home_start', 9)
WEEKEND_HOME_END = config.get('weekend_home_end', 23)

# Timezone setup
try:
    tz = pytz.timezone(TIMEZONE)
except Exception:
    tz = pytz.timezone('America/New_York')
    logging.warning(f"Invalid timezone {TIMEZONE}, using America/New_York")

# =============================================================================
# Flask App Initialization
# =============================================================================

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['JSON_SORT_KEYS'] = False
app.permanent_session_lifetime = timedelta(days=30)  # 30-day sessions

# Session security configuration
app.config['SESSION_COOKIE_HTTPONLY'] = True   # Prevent JavaScript access to cookies
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection
# app.config['SESSION_COOKIE_SECURE'] = True   # HTTPS only - enable when using HTTPS

# CSRF protection
csrf = CSRFProtect(app)

# Global state (cached from DB)
wyze_client = None
camera_list = []
camera_list_last_updated = None
CAMERA_CACHE_DURATION = timedelta(hours=6)

# System start time
system_start_time = datetime.now(tz=tz)

# Rate limiting for heartbeat endpoint
heartbeat_rate_limit = defaultdict(list)  # IP -> [timestamps]

def check_heartbeat_rate_limit(ip: str, max_requests: int = 60, window_minutes: int = 5) -> bool:
    """
    Check if IP has exceeded heartbeat rate limit.

    Args:
        ip: IP address to check
        max_requests: Maximum requests allowed in the time window
        window_minutes: Time window in minutes

    Returns:
        True if request is allowed, False if rate limit exceeded
    """
    now = datetime.now()
    cutoff = now - timedelta(minutes=window_minutes)

    # Clean old entries
    heartbeat_rate_limit[ip] = [t for t in heartbeat_rate_limit[ip] if t > cutoff]

    # Check limit
    if len(heartbeat_rate_limit[ip]) >= max_requests:
        return False

    # Record this request
    heartbeat_rate_limit[ip].append(now)
    return True

# =============================================================================
# Wyze API Integration
# =============================================================================

def init_wyze_client() -> bool:
    """
    Initialize Wyze API client and fetch camera list.

    Returns:
        True if successful, False otherwise
    """
    global wyze_client, camera_list, camera_list_last_updated

    if not WYZE_AVAILABLE:
        logger.warning("Wyze SDK not available - running in mock mode")
        db.add_activity_log('SYSTEM', 'warn', 'Wyze SDK not available - mock mode')
        return False

    if not config.has_wyze_credentials():
        logger.error("Wyze credentials not configured")
        db.add_activity_log('SYSTEM', 'error', 'Wyze credentials missing in configuration')
        return False

    try:
        logger.info("Initializing Wyze client...")
        start_time = datetime.now()

        # Prepare client parameters
        client_params = {
            'email': WYZE_EMAIL,
            'password': WYZE_PASSWORD,
            'key_id': WYZE_API_ID,
            'api_key': WYZE_API_KEY
        }

        # Add TOTP key if configured
        if WYZE_TOTP_KEY:
            client_params['totp_key'] = WYZE_TOTP_KEY

        wyze_client = WyzeClient(**client_params)

        # Fetch camera list - try multiple methods to get ALL cameras including Pan cameras
        cameras_raw = []

        try:
            # Method 1: Standard camera list
            standard_cams = wyze_client.cameras.list()
            logger.info(f"Standard cameras.list() returned {len(standard_cams)} cameras")
            cameras_raw.extend(standard_cams)
        except Exception as e:
            logger.warning(f"Failed to get cameras via cameras.list(): {e}")

        try:
            # Method 2: Try to get all devices and filter for cameras
            # This sometimes catches Pan cameras that cameras.list() misses
            all_devices = wyze_client.devices_list()
            logger.info(f"devices_list() returned {len(all_devices)} total devices")

            # Filter for camera-type devices
            for device in all_devices:
                # Check if it's a camera and not already in our list
                if hasattr(device, 'product') and device.product and device.product.type == 'Camera':
                    # Check if we already have this MAC
                    if not any(cam.mac == device.mac for cam in cameras_raw):
                        cameras_raw.append(device)
                        logger.info(f"Found additional camera via devices_list: {device.nickname} ({device.product.model})")
        except Exception as e:
            logger.warning(f"Failed to get devices via devices_list(): {e}")

        logger.info(f"Total cameras found after all methods: {len(cameras_raw)}")

        # Build camera list, handling both individual cameras and groups
        camera_list = []
        for cam in cameras_raw:
            # Check if this is a camera group by looking at device_params
            try:
                # If camera has device_params with camera_list, it's a group
                if hasattr(cam, 'device_params') and cam.device_params:
                    # This might be a group - try to get individual cameras
                    logger.info(f"Detected potential camera group: {cam.nickname}")
                    # For now, add the group itself - we'll expand it later
                    camera_list.append({
                        'mac': cam.mac,
                        'nickname': f"{cam.nickname} (Group)",
                        'product_model': cam.product.model,
                        'product_type': cam.product.type,
                        'is_group': True
                    })
                else:
                    # Regular individual camera
                    camera_list.append({
                        'mac': cam.mac,
                        'nickname': cam.nickname,
                        'product_model': cam.product.model,
                        'product_type': cam.product.type,
                        'is_group': False
                    })
            except Exception as e:
                # If we can't determine, treat as individual camera
                logger.debug(f"Error checking if {cam.nickname} is group: {e}")
                camera_list.append({
                    'mac': cam.mac,
                    'nickname': cam.nickname,
                    'product_model': cam.product.model,
                    'product_type': cam.product.type,
                    'is_group': False
                })

        camera_list_last_updated = datetime.now(tz=tz)

        duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        logger.info(f"Wyze client initialized successfully with {len(camera_list)} cameras ({duration_ms:.2f}ms)")

        db.add_activity_log('SYSTEM', 'info',
                           f"Wyze client initialized: {len(camera_list)} cameras found",
                           details={'camera_count': len(camera_list), 'duration_ms': duration_ms})
        db.log_api_call('list_cameras', True, int(duration_ms))

        return True

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed to initialize Wyze client: {error_msg}", exc_info=True)

        # Provide helpful error messages
        if '400' in error_msg or 'Bad Request' in error_msg:
            totp_status = "TOTP key configured" if WYZE_TOTP_KEY else "NO TOTP key (required if 2FA enabled)"
            logger.error(f"Wyze authentication failed with 400 Bad Request. {totp_status}")
            db.add_activity_log('SYSTEM', 'error', f"Wyze auth failed (400): {totp_status}")
        else:
            db.add_activity_log('SYSTEM', 'error', f"Wyze client initialization failed: {error_msg}")

        db.log_api_call('list_cameras', False, error_message=error_msg)
        return False


def refresh_camera_list_if_needed():
    """Refresh camera list if cache is stale."""
    global camera_list_last_updated

    if not wyze_client:
        return

    if camera_list_last_updated is None or \
       (datetime.now(tz=tz) - camera_list_last_updated) > CAMERA_CACHE_DURATION:
        logger.info("Camera list cache expired, refreshing...")
        init_wyze_client()


def execute_camera_control(action: str, reason: str, trigger_type: str) -> Tuple[bool, List[Dict]]:
    """
    Execute camera control action (turn on/off all cameras).

    Args:
        action: 'on' or 'off'
        reason: Human-readable reason for action
        trigger_type: 'manual', 'presence', or 'schedule'

    Returns:
        Tuple of (success: bool, results: List[Dict])
    """
    if not wyze_client or not camera_list:
        logger.warning("Cannot control cameras: Wyze client not initialized")
        db.add_activity_log('CAMERA', 'warn', f"Camera control failed: Client not initialized (action: {action})")
        return False, []

    logger.info(f"Executing camera control: {action} (trigger: {trigger_type}, reason: {reason})")

    results = []
    overall_success = False

    for camera in camera_list:
        camera_id = camera['mac']
        camera_name = camera['nickname']
        camera_model = camera['product_model']

        start_time = datetime.now()
        success = False
        error_message = None

        try:
            # Attempt to control camera with retry logic
            for attempt in range(3):
                try:
                    if action == 'on':
                        wyze_client.cameras.turn_on(device_mac=camera_id, device_model=camera_model)
                    elif action == 'off':
                        wyze_client.cameras.turn_off(device_mac=camera_id, device_model=camera_model)
                    else:
                        raise ValueError(f"Invalid action: {action}")

                    success = True
                    overall_success = True
                    break

                except WyzeApiError as e:
                    error_message = str(e)
                    if attempt < 2:
                        wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s
                        logger.warning(f"Camera {camera_name} control failed (attempt {attempt+1}/3), retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Camera {camera_name} control failed after 3 attempts: {e}")

        except Exception as e:
            error_message = str(e)
            logger.error(f"Unexpected error controlling camera {camera_name}: {e}")

        # Calculate response time
        response_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        # Log camera action
        db.log_camera_action(
            camera_id=camera_id,
            camera_name=camera_name,
            action=action,
            trigger_type=trigger_type,
            success=success,
            error_message=error_message,
            response_time_ms=response_time_ms
        )

        # Log API call
        db.log_api_call(
            endpoint=f'camera_turn_{action}',
            success=success,
            response_time_ms=response_time_ms,
            error_message=error_message
        )

        results.append({
            'camera_id': camera_id,
            'camera_name': camera_name,
            'action': action,
            'success': success,
            'error': error_message,
            'response_time_ms': response_time_ms
        })

    # Update system state
    if overall_success:
        db.save_system_state({
            'cameras': action,
            'last_camera_action': datetime.now(tz=tz).isoformat()
        })

        # Log activity
        success_count = sum(1 for r in results if r['success'])
        db.add_activity_log(
            'CAMERA',
            'info',
            f"Cameras turned {action.upper()} ({success_count}/{len(results)} successful) - {reason}",
            details={'trigger_type': trigger_type, 'results': results}
        )
    else:
        db.add_activity_log(
            'CAMERA',
            'error',
            f"All cameras failed to turn {action.upper()} - {reason}",
            details={'trigger_type': trigger_type, 'results': results}
        )

    return overall_success, results


# =============================================================================
# State Machine
# =============================================================================

def state_machine_tick():
    """
    State machine logic - runs every 1 minute.

    Decision flow:
    1. Check manual override (if active, maintain state and exit)
    2. Evaluate presence (heartbeat-based)
    3. Fallback to schedule (time-based)
    4. Apply desired state if changed
    """
    try:
        logger.debug("State machine tick starting...")

        # Get current state
        state = db.get_system_state()
        current_mode = state.get('mode', 'schedule')
        current_cameras = state.get('cameras', 'unknown')
        current_presence_status = state.get('presence_status', 'UNKNOWN')
        last_heartbeat = state.get('last_heartbeat')

        now = datetime.now(tz=tz)

        # Step 1: Check manual override
        manual_override_until = state.get('manual_override_until')
        if manual_override_until:
            try:
                override_time = datetime.fromisoformat(manual_override_until)
                if override_time.tzinfo is None:
                    override_time = tz.localize(override_time)

                if now < override_time:
                    logger.debug(f"Manual override active until {override_time}")
                    # Update mode to manual (if not already)
                    if current_mode != 'manual':
                        db.save_system_state({'mode': 'manual'})
                    return  # Exit early, no state change
                else:
                    # Override expired
                    logger.info("Manual override expired, resuming normal operation")
                    db.save_system_state({'manual_override_until': None})
                    db.add_activity_log('SYSTEM', 'info', 'Manual override expired')
            except Exception as e:
                logger.error(f"Error parsing manual override time: {e}")

        # Step 2: Evaluate presence using device-based detection
        desired_state = None
        new_mode = None
        presence_status = 'UNKNOWN'
        reason = None

        try:
            # Check for online devices (within HOME_THRESHOLD minutes)
            online_devices = db.get_online_devices(minutes=HOME_THRESHOLD)

            if online_devices:
                # At least one device is online - user is HOME
                presence_status = 'HOME'
                desired_state = 'off'
                new_mode = 'presence'
                device_names = ', '.join([d['device_name'] for d in online_devices[:3]])  # Show up to 3 device names
                if len(online_devices) > 3:
                    device_names += f', +{len(online_devices) - 3} more'
                reason = f'Presence: HOME ({len(online_devices)} device{"s" if len(online_devices) > 1 else ""} online: {device_names})'
                logger.info(f"Presence detected: {len(online_devices)} online devices - {device_names}")

                # Log to activity log if presence status changed to HOME
                if current_presence_status != 'HOME':
                    db.add_activity_log('PRESENCE', 'info', f'Detected HOME - {len(online_devices)} device(s) online',
                                       details={'devices': [d['device_name'] for d in online_devices]})
            else:
                # No devices online - check if we have any registered devices at all
                all_devices = db.get_all_devices()

                if all_devices:
                    # Check if using pure ARP mode (no grace period)
                    arp_modes = ['arp', 'arp_3x']
                    all_using_arp = all(d.get('detection_method') in arp_modes for d in all_devices)

                    if all_using_arp:
                        # Pure ARP mode: No grace period, immediate AWAY confirmation
                        presence_status = 'AWAY_CONFIRMED'
                        desired_state = 'on'
                        new_mode = 'presence'
                        reason = f'ARP CONFIRMED AWAY: No devices detected via ARP'
                        logger.info(f"ARP mode: Immediate away confirmation (no grace period)")

                        # Log to activity
                        db.add_activity_log('PRESENCE', 'info',
                                          f'ARP CONFIRMED AWAY - No devices online',
                                          details={'devices': [d['device_name'] for d in all_devices]})
                    else:
                        # Mixed modes or non-ARP: Use existing grace period logic
                        # We have devices but none are online - check if we're in grace period
                        # Get the most recent device activity
                        most_recent_device = max(all_devices, key=lambda d: d['last_seen'])
                        last_seen_time = datetime.fromisoformat(most_recent_device['last_seen'])
                        if last_seen_time.tzinfo is None:
                            last_seen_time = tz.localize(last_seen_time)

                        minutes_since_last_seen = (now - last_seen_time).total_seconds() / 60

                        if minutes_since_last_seen < AWAY_THRESHOLD:
                            # In grace period - don't change camera state
                            presence_status = 'GRACE'
                            new_mode = 'presence_grace'
                            reason = f'Presence: GRACE PERIOD ({int(minutes_since_last_seen)} min since last device)'
                            logger.info(f"Presence: GRACE PERIOD - {int(minutes_since_last_seen)} min since {most_recent_device['device_name']}")

                            # Log to activity log when entering grace period (only once)
                            if current_presence_status != 'GRACE':
                                db.add_activity_log('PRESENCE', 'info', f'Entered GRACE PERIOD - {int(minutes_since_last_seen)} min since last device',
                                                   details={'device': most_recent_device['device_name'], 'last_seen': most_recent_device['last_seen']})

                            db.save_system_state({'presence_status': presence_status, 'mode': new_mode, 'reason': reason})
                            return
                        else:
                            # Away confirmed - turn cameras on
                            presence_status = 'AWAY_CONFIRMED'
                            desired_state = 'on'
                            new_mode = 'presence'
                            reason = f'Presence: AWAY CONFIRMED ({int(minutes_since_last_seen)} min since last device)'
                            logger.info(f"Presence: AWAY CONFIRMED - {int(minutes_since_last_seen)} min since {most_recent_device['device_name']}")

                            # Log to activity log when presence changes to AWAY (only once)
                            if current_presence_status != 'AWAY_CONFIRMED':
                                db.add_activity_log('PRESENCE', 'info', f'Detected AWAY - {int(minutes_since_last_seen)} min since last device',
                                                   details={'device': most_recent_device['device_name'], 'last_seen': most_recent_device['last_seen']})
                # else: no devices registered, fall through to schedule-based logic

        except Exception as e:
            logger.error(f"Error evaluating device-based presence: {e}")
            presence_status = 'UNKNOWN'

        # Step 3: Schedule fallback (if presence unknown)
        if desired_state is None:
            new_mode = 'schedule'
            presence_status = 'UNKNOWN'

            current_time = now.strftime('%H:%M')
            day_of_week = now.weekday()  # 0=Monday, 6=Sunday

            # Check for custom schedules first
            active_schedules = db.get_active_schedules_for_time(day_of_week, current_time)

            if active_schedules:
                # Use first matching custom schedule (schedules are ordered by start_time)
                schedule = active_schedules[0]
                desired_state = schedule['cameras_state']
                reason = f'Custom Schedule: {schedule["name"]} (cameras {desired_state.upper()})'
                logger.debug(f"Using custom schedule: {schedule['name']}")
            else:
                # Fall back to default weekday/weekend schedule
                current_hour = now.hour
                is_weekday = day_of_week < 5  # Monday=0, Sunday=6

                if is_weekday:
                    # Weekday schedule (configurable)
                    if WEEKDAY_HOME_START <= current_hour < WEEKDAY_HOME_END:
                        desired_state = 'off'
                        reason = f'Default Schedule: Weekday home hours ({WEEKDAY_HOME_START}:00 - {WEEKDAY_HOME_END}:00)'
                    else:
                        desired_state = 'on'
                        reason = f'Default Schedule: Weekday away hours ({WEEKDAY_HOME_END}:00 - {WEEKDAY_HOME_START}:00)'
                else:
                    # Weekend schedule (configurable)
                    if WEEKEND_HOME_START <= current_hour < WEEKEND_HOME_END:
                        desired_state = 'off'
                        reason = f'Default Schedule: Weekend home hours ({WEEKEND_HOME_START}:00 - {WEEKEND_HOME_END}:00)'
                    else:
                        desired_state = 'on'
                        reason = f'Default Schedule: Weekend away hours ({WEEKEND_HOME_END}:00 - {WEEKEND_HOME_START}:00)'

        # Step 4: Apply desired state if changed
        if desired_state != current_cameras:
            logger.info(f"State change detected: {current_cameras} -> {desired_state} (mode: {new_mode}, reason: {reason})")

            # Execute camera control
            success, results = execute_camera_control(desired_state, reason, new_mode)

            if success:
                # Log state transition
                db.log_state_transition(
                    from_mode=current_mode,
                    to_mode=new_mode,
                    from_cameras=current_cameras,
                    to_cameras=desired_state,
                    presence_status=presence_status,
                    reason=reason
                )

                # Update system state
                db.save_system_state({
                    'mode': new_mode,
                    'cameras': desired_state,
                    'presence_status': presence_status,
                    'reason': reason,
                    'last_state_change': now.isoformat()
                })
            else:
                logger.error(f"Failed to change camera state to {desired_state}")
                db.add_activity_log('SYSTEM', 'error',
                                   f"State machine failed to execute camera control: {desired_state}")
        else:
            # No change needed, just update metadata
            db.save_system_state({
                'mode': new_mode,
                'presence_status': presence_status,
                'reason': reason
            })
            logger.debug(f"No state change needed. Current: {current_cameras}, Mode: {new_mode}")

    except Exception as e:
        logger.error(f"State machine tick failed: {e}", exc_info=True)
        db.add_activity_log('SYSTEM', 'error', f"State machine error: {e}")


# =============================================================================
# Flask Context Processors
# =============================================================================

@app.context_processor
def inject_timezone():
    """Make timezone available to all templates."""
    timezone = config.get('timezone', 'America/New_York')
    return {'tz': timezone}


# =============================================================================
# Flask Routes - Authentication
# =============================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page and handler."""
    # If already logged in, redirect to dashboard
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            flash('Username and password required', 'error')
            return render_template('login.html', show_registration=False)

        # Authenticate
        success, user = auth.authenticate_user(username, password)

        if success:
            # Set session
            session['user_id'] = user['id']
            session['username'] = user['username']
            session.permanent = True  # Remember login

            logger.info(f"User logged in: {username}")

            # Redirect to next page or dashboard
            next_page = request.args.get('next')
            if next_page and next_page.startswith('/'):
                return redirect(next_page)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')
            return render_template('login.html', show_registration=False)

    # GET request - show login form
    return render_template('login.html', show_registration=False)


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Registration page - only works if no users exist."""
    # Check if users already exist
    if auth.has_users():
        flash('Registration is closed. Admin account already exists.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')

        # Validate
        if not username or not password:
            flash('Username and password required', 'error')
            return render_template('login.html', show_registration=True)

        if password != password_confirm:
            flash('Passwords do not match', 'error')
            return render_template('login.html', show_registration=True)

        # Create user
        success, error_msg = auth.create_user(username, password)

        if success:
            flash('Account created successfully! Please log in.', 'success')
            logger.info(f"Admin account created: {username}")
            db.add_activity_log('SYSTEM', 'info', f'Admin account created: {username}')
            return redirect(url_for('login'))
        else:
            flash(error_msg, 'error')
            return render_template('login.html', show_registration=True)

    # GET request - show registration form
    return render_template('login.html', show_registration=True)


@app.route('/logout')
def logout():
    """Logout current user."""
    username = session.get('username', 'Unknown')
    session.clear()
    logger.info(f"User logged out: {username}")
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))


# =============================================================================
# Flask Routes - Setup Wizard
# =============================================================================

# Rate limiting for test-wyze endpoint
last_test_wyze_time = {}

@app.route('/setup')
def setup():
    """Setup wizard page (first-time configuration)."""
    # If already setup, redirect to dashboard
    if config.is_setup_complete():
        return redirect(url_for('dashboard'))

    # Generate random webhook secret for initial setup
    random_secret = secrets.token_hex(32)  # 64-character hex string
    return render_template('setup.html', random_secret=random_secret)


@app.route('/reset-setup')
def reset_setup():
    """Reset setup status to allow reconfiguration."""
    try:
        # Clear setup complete flag
        db.set_setting('setup_completed', 'false')
        logger.info("Setup reset requested - clearing setup_completed flag")
        db.add_activity_log('SYSTEM', 'info', 'System configuration reset - returning to setup wizard')

        # Redirect to setup page
        return redirect(url_for('setup'))
    except Exception as e:
        logger.error(f"Failed to reset setup: {e}", exc_info=True)
        flash(f'Error resetting setup: {e}', 'error')
        return redirect(url_for('settings'))


@app.route('/setup/save', methods=['POST'])
def setup_save():
    """Save setup wizard configuration."""
    # Security: Require authentication if users already exist
    # Allow first-time setup when no users exist
    if auth.has_users():
        if not session.get('user_id'):
            logger.warning("Unauthorized setup attempt - authentication required")
            flash('Please log in to access setup', 'error')
            return redirect(url_for('login', next=request.url))

    try:
        # Get form data
        form_data = request.form.to_dict()

        # Set schedule defaults if not provided
        form_data.setdefault('weekday_home_start', '8')
        form_data.setdefault('weekday_home_end', '18')
        form_data.setdefault('weekend_home_start', '9')
        form_data.setdefault('weekend_home_end', '23')

        # Log received data (excluding sensitive values)
        totp_provided = bool(form_data.get('wyze_totp_key'))
        logger.info(f"Setup save: TOTP key provided: {totp_provided}")

        # Validate required fields
        required_fields = ['wyze_email', 'wyze_password', 'wyze_api_key', 'wyze_api_id',
                          'webhook_secret', 'timezone', 'home_threshold', 'away_threshold',
                          'manual_override_duration', 'log_level']

        for field in required_fields:
            if not form_data.get(field):
                flash(f'Missing required field: {field}', 'error')
                return redirect(url_for('setup'))

        # Save configuration (includes optional wyze_totp_key)
        success = config.save_config(form_data)

        if not success:
            flash('Failed to save configuration', 'error')
            return redirect(url_for('setup'))

        # Get encryption key to show user
        crypto = get_crypto()
        encryption_key = crypto.get_key_hex()

        # Reload config and reinitialize Wyze client
        reload_config()
        global WYZE_EMAIL, WYZE_PASSWORD, WYZE_API_KEY, WYZE_API_ID, WYZE_TOTP_KEY, WEBHOOK_SECRET
        WYZE_EMAIL = config.get('wyze_email', '')
        WYZE_PASSWORD = config.get('wyze_password', '')
        WYZE_API_KEY = config.get('wyze_api_key', '')
        WYZE_API_ID = config.get('wyze_api_id', '')
        WYZE_TOTP_KEY = config.get('wyze_totp_key', '')
        WEBHOOK_SECRET = config.get('webhook_secret', '')

        init_wyze_client()

        # Show setup complete page with encryption key
        return render_template('setup_complete.html', encryption_key=encryption_key)

    except Exception as e:
        logger.error(f"Setup save error: {e}", exc_info=True)
        flash(f'Error saving configuration: {e}', 'error')
        return redirect(url_for('setup'))


# =============================================================================
# Flask Routes - Dashboard & Pages
# =============================================================================

@app.route('/')
@auth.login_required
def index():
    """Index route - redirects to setup or dashboard."""
    if not config.is_setup_complete():
        return redirect(url_for('setup'))
    return redirect(url_for('dashboard'))


@app.route('/dashboard')
@auth.login_required
def dashboard():
    """Main dashboard page."""
    # Redirect to setup if not complete
    if not config.is_setup_complete():
        return redirect(url_for('setup'))

    try:
        # Get system state
        state = db.get_system_state()

        # Get recent activity
        recent_logs = db.get_activity_log(limit=20)

        # Get camera list
        refresh_camera_list_if_needed()

        # Get health summary
        db_health = db.check_database_health()
        heartbeat_stats = db.get_heartbeat_stats(hours=24)
        api_stats = db.get_api_health_stats(hours=24)

        # Calculate heartbeat time ago (for template display)
        heartbeat_time_ago = None
        if heartbeat_stats.get('last_heartbeat'):
            try:
                last_hb = datetime.fromisoformat(heartbeat_stats['last_heartbeat'])
                now_time = datetime.now()
                delta = now_time - last_hb
                total_seconds = delta.total_seconds()
                hrs_ago = int(total_seconds / 3600)
                mins_ago = int((total_seconds % 3600) / 60)

                if hrs_ago > 0:
                    heartbeat_time_ago = f"{hrs_ago}h {mins_ago}m ago"
                elif mins_ago > 0:
                    heartbeat_time_ago = f"{mins_ago} min ago"
                else:
                    heartbeat_time_ago = "Just now"
            except (ValueError, TypeError):
                heartbeat_time_ago = "Unknown"

        # Calculate system status
        system_status = 'operational'
        if not db_health['connected']:
            system_status = 'degraded'
        elif api_stats['uptime_percent'] < 80:
            system_status = 'degraded'

        return render_template('dashboard.html',
                              state=state,
                              cameras=camera_list,
                              recent_logs=recent_logs,
                              db_health=db_health,
                              heartbeat_stats=heartbeat_stats,
                              heartbeat_time_ago=heartbeat_time_ago,
                              api_stats=api_stats,
                              system_status=system_status,
                              now=datetime.now(),
                              tz=TIMEZONE)

    except Exception as e:
        logger.error(f"Dashboard error: {e}", exc_info=True)
        return f"Error loading dashboard: {e}", 500


@app.route('/settings/edit')
@auth.login_required
def settings_edit():
    """Editable settings page."""
    # Redirect to setup if not complete
    if not config.is_setup_complete():
        return redirect(url_for('setup'))

    try:
        # Get all current settings (decrypted)
        current = db.get_all_settings_decrypted()

        # Add values that might not be in settings yet
        current.setdefault('wyze_email', config.get('wyze_email', ''))
        current.setdefault('wyze_password', config.get('wyze_password', ''))
        current.setdefault('wyze_api_key', config.get('wyze_api_key', ''))
        current.setdefault('wyze_api_id', config.get('wyze_api_id', ''))
        current.setdefault('wyze_totp_key', config.get('wyze_totp_key', ''))
        current.setdefault('webhook_secret', config.get('webhook_secret', ''))
        current.setdefault('timezone', config.get('timezone', 'America/New_York'))
        current.setdefault('home_threshold', config.get('home_threshold', 10))
        current.setdefault('away_threshold', config.get('away_threshold', 30))
        current.setdefault('manual_override_duration', config.get('manual_override_duration', 2))
        current.setdefault('state_machine_interval', config.get('state_machine_interval', 5))
        current.setdefault('weekday_home_start', config.get('weekday_home_start', 8))
        current.setdefault('weekday_home_end', config.get('weekday_home_end', 18))
        current.setdefault('weekend_home_start', config.get('weekend_home_start', 9))
        current.setdefault('weekend_home_end', config.get('weekend_home_end', 23))
        current.setdefault('log_level', config.get('log_level', 'INFO'))

        return render_template('settings_edit.html', current=current)

    except Exception as e:
        logger.error(f"Settings edit page error: {e}", exc_info=True)
        return f"Error loading settings editor: {e}", 500


@app.route('/settings/save', methods=['POST'])
@auth.login_required
def settings_save():
    """Save updated settings."""
    try:
        # Get form data
        form_data = request.form.to_dict()

        # Log received data (excluding sensitive values)
        totp_provided = bool(form_data.get('wyze_totp_key'))
        logger.info(f"Settings save: TOTP key provided: {totp_provided}")

        # Validate required fields
        required_fields = ['wyze_email', 'wyze_password', 'wyze_api_key', 'wyze_api_id',
                          'webhook_secret', 'timezone', 'home_threshold', 'away_threshold',
                          'manual_override_duration', 'state_machine_interval', 'weekday_home_start', 'weekday_home_end',
                          'weekend_home_start', 'weekend_home_end', 'log_level']

        for field in required_fields:
            if not form_data.get(field):
                flash(f'Missing required field: {field}', 'error')
                return redirect(url_for('settings_edit'))

        # Save configuration
        success = config.save_config(form_data)

        if not success:
            flash('Failed to save configuration', 'error')
            return redirect(url_for('settings_edit'))

        # Reload config and reinitialize Wyze client
        reload_config()
        global WYZE_EMAIL, WYZE_PASSWORD, WYZE_API_KEY, WYZE_API_ID, WYZE_TOTP_KEY, WEBHOOK_SECRET
        global TIMEZONE, HOME_THRESHOLD, AWAY_THRESHOLD, MANUAL_OVERRIDE_DURATION, STATE_MACHINE_INTERVAL
        global WEEKDAY_HOME_START, WEEKDAY_HOME_END, WEEKEND_HOME_START, WEEKEND_HOME_END

        WYZE_EMAIL = config.get('wyze_email', '')
        WYZE_PASSWORD = config.get('wyze_password', '')
        WYZE_API_KEY = config.get('wyze_api_key', '')
        WYZE_API_ID = config.get('wyze_api_id', '')
        WYZE_TOTP_KEY = config.get('wyze_totp_key', '')
        WEBHOOK_SECRET = config.get('webhook_secret', '')
        TIMEZONE = config.get('timezone', 'America/New_York')
        HOME_THRESHOLD = config.get('home_threshold', 10)
        AWAY_THRESHOLD = config.get('away_threshold', 30)
        MANUAL_OVERRIDE_DURATION = config.get('manual_override_duration', 2)
        STATE_MACHINE_INTERVAL = config.get('state_machine_interval', 5)
        WEEKDAY_HOME_START = config.get('weekday_home_start', 8)
        WEEKDAY_HOME_END = config.get('weekday_home_end', 18)
        WEEKEND_HOME_START = config.get('weekend_home_start', 9)
        WEEKEND_HOME_END = config.get('weekend_home_end', 23)

        # Try to initialize Wyze client with new credentials
        init_wyze_client()

        flash('Settings saved successfully!', 'success')
        db.add_activity_log('SYSTEM', 'info', 'Settings updated via web interface')

        return redirect(url_for('settings'))

    except Exception as e:
        logger.error(f"Settings save error: {e}", exc_info=True)
        flash(f'Error saving settings: {e}', 'error')
        return redirect(url_for('settings_edit'))


@app.route('/settings')
@auth.login_required
def settings():
    """Settings and operational overview page."""
    # Redirect to setup if not complete
    if not config.is_setup_complete():
        return redirect(url_for('setup'))

    try:
        # Get all health metrics
        db_health = db.check_database_health()
        heartbeat_stats = db.get_heartbeat_stats(hours=24)
        camera_stats = db.get_camera_toggle_stats(hours=24)
        api_stats = db.get_api_health_stats(hours=24)
        state_stats = db.get_state_machine_stats(hours=24)

        # Get system resources
        system_resources = {
            'cpu_percent': psutil.cpu_percent(interval=1),
            'memory': psutil.virtual_memory()._asdict(),
            'disk': psutil.disk_usage('/')._asdict(),
            'uptime_seconds': (datetime.now(tz=tz) - system_start_time).total_seconds()
        }

        # Get configuration
        config_data = {
            'timezone': TIMEZONE,
            'home_threshold': HOME_THRESHOLD,
            'away_threshold': AWAY_THRESHOLD,
            'manual_override_duration': MANUAL_OVERRIDE_DURATION,
            'camera_count': len(camera_list)
        }

        return render_template('settings.html',
                              db_health=db_health,
                              heartbeat_stats=heartbeat_stats,
                              camera_stats=camera_stats,
                              api_stats=api_stats,
                              state_stats=state_stats,
                              system_resources=system_resources,
                              config=config_data)

    except Exception as e:
        logger.error(f"Settings page error: {e}", exc_info=True)
        return f"Error loading settings: {e}", 500


@app.route('/logs')
@auth.login_required
def logs():
    """Logs viewer page."""
    # Redirect to setup if not complete
    if not config.is_setup_complete():
        return redirect(url_for('setup'))

    try:
        # Get filters from query params
        log_type = request.args.get('type')
        level = request.args.get('level')
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))

        # Get logs
        logs_data = db.get_activity_log(limit=limit, log_type=log_type, level=level, offset=offset)

        return render_template('logs.html',
                              logs=logs_data,
                              current_type=log_type,
                              current_level=level,
                              limit=limit,
                              offset=offset)

    except Exception as e:
        logger.error(f"Logs page error: {e}", exc_info=True)
        return f"Error loading logs: {e}", 500


# =============================================================================
# Flask Routes - Manual Control
# =============================================================================

@app.route('/manual/off')
@auth.login_required
def manual_off():
    """Turn cameras OFF with manual override."""
    # Redirect to setup if not complete
    if not config.is_setup_complete():
        return redirect(url_for('setup'))

    try:
        override_until = datetime.now(tz=tz) + timedelta(hours=MANUAL_OVERRIDE_DURATION)

        logger.info(f"Manual override: Cameras OFF until {override_until}")

        # Execute camera control
        success, results = execute_camera_control('off', f'Manual override until {override_until.strftime("%I:%M %p")}', 'manual')

        if success:
            # Set manual override
            db.save_system_state({
                'manual_override_until': override_until.isoformat(),
                'mode': 'manual',
                'cameras': 'off',
                'reason': f'Manual override: OFF until {override_until.strftime("%I:%M %p")}'
            })

            db.add_activity_log('SYSTEM', 'info',
                               f'Manual override activated: Cameras OFF until {override_until.strftime("%I:%M %p")}')

            flash(f'Cameras turned OFF until {override_until.strftime("%I:%M %p")}', 'success')
        else:
            flash('Failed to turn cameras OFF. Check logs for details.', 'error')

        return redirect(url_for('dashboard'))

    except Exception as e:
        logger.error(f"Manual OFF error: {e}", exc_info=True)
        flash(f'Error: {e}', 'error')
        return redirect(url_for('dashboard'))


@app.route('/manual/on')
@auth.login_required
def manual_on():
    """Turn cameras ON with manual override."""
    # Redirect to setup if not complete
    if not config.is_setup_complete():
        return redirect(url_for('setup'))

    try:
        override_until = datetime.now(tz=tz) + timedelta(hours=MANUAL_OVERRIDE_DURATION)

        logger.info(f"Manual override: Cameras ON until {override_until}")

        # Execute camera control
        success, results = execute_camera_control('on', f'Manual override until {override_until.strftime("%I:%M %p")}', 'manual')

        if success:
            # Set manual override
            db.save_system_state({
                'manual_override_until': override_until.isoformat(),
                'mode': 'manual',
                'cameras': 'on',
                'reason': f'Manual override: ON until {override_until.strftime("%I:%M %p")}'
            })

            db.add_activity_log('SYSTEM', 'info',
                               f'Manual override activated: Cameras ON until {override_until.strftime("%I:%M %p")}')

            flash(f'Cameras turned ON until {override_until.strftime("%I:%M %p")}', 'success')
        else:
            flash('Failed to turn cameras ON. Check logs for details.', 'error')

        return redirect(url_for('dashboard'))

    except Exception as e:
        logger.error(f"Manual ON error: {e}", exc_info=True)
        flash(f'Error: {e}', 'error')
        return redirect(url_for('dashboard'))


@app.route('/manual/auto')
@auth.login_required
def manual_auto():
    """Clear manual override and return to automatic mode."""
    # Redirect to setup if not complete
    if not config.is_setup_complete():
        return redirect(url_for('setup'))

    try:
        # Clear manual override
        db.save_system_state({
            'manual_override_until': None,
            'mode': 'auto'
        })

        logger.info("Manual override cleared - returning to automatic mode")
        db.add_activity_log('SYSTEM', 'info', 'Manual override cleared - automatic mode resumed')

        flash('Manual override cleared. System returned to automatic mode.', 'success')
        return redirect(url_for('dashboard'))

    except Exception as e:
        logger.error(f"Manual AUTO error: {e}", exc_info=True)
        flash(f'Error: {e}', 'error')
        return redirect(url_for('dashboard'))


# =============================================================================
# Flask Routes - Heartbeat
# =============================================================================

@app.route('/heartbeat', methods=['GET', 'POST'])
def heartbeat():
    """Receive heartbeat from iPhone or other devices."""
    # Rate limiting check
    if not check_heartbeat_rate_limit(request.remote_addr):
        logger.warning(f"Rate limit exceeded for heartbeat from {request.remote_addr}")
        return jsonify({'error': 'Rate limit exceeded. Maximum 60 requests per 5 minutes.'}), 429

    # Validate token
    token = request.args.get('token') or request.form.get('token')

    if not token or token != WEBHOOK_SECRET:
        logger.warning(f"Unauthorized heartbeat attempt from {request.remote_addr}")
        db.add_activity_log('SYSTEM', 'warn', f'Unauthorized heartbeat attempt from {request.remote_addr}')
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        now = datetime.now(tz=tz)
        source_ip = request.remote_addr

        # Get optional device info from request
        device_id = request.args.get('device_id') or request.form.get('device_id')
        device_name = request.args.get('device_name') or request.form.get('device_name')
        device_type = request.args.get('device_type') or request.form.get('device_type') or 'phone'

        # Update system state
        db.save_system_state({'last_heartbeat': now.isoformat()})

        # Handle device registration/update
        if device_id:
            # Check if device exists
            existing_device = db.get_device(device_id)

            if existing_device:
                # Check if device was offline and is now coming back online
                was_offline = existing_device['device_id'] not in {d['device_id'] for d in db.get_online_devices(minutes=HOME_THRESHOLD)}

                # Update existing device's last seen time
                db.update_device_last_seen(device_id, source_ip)
                logger.info(f"Heartbeat received from {existing_device['device_name']} ({source_ip})")

                # Log to activity log when device comes back online
                if was_offline:
                    db.add_activity_log('DEVICE', 'info', f"Device '{existing_device['device_name']}' came online",
                                       details={'device_id': device_id, 'ip': source_ip})
            else:
                # Register new device
                name = device_name or f"Device {device_id[:8]}"
                db.register_device(device_id, name, device_type, source_ip)
                logger.info(f"New device registered: {name} ({device_id})")
                db.add_activity_log('DEVICE', 'info', f'New device registered: {name}',
                                   details={'device_id': device_id, 'device_type': device_type, 'ip': source_ip})

            # Log heartbeat with device ID
            db.log_heartbeat(source_ip=source_ip, device_id=device_id)
        else:
            # Log heartbeat without device ID (legacy)
            db.log_heartbeat(source_ip=source_ip)

        # Get current state
        state = db.get_system_state()

        logger.info(f"Heartbeat received from {source_ip}" + (f" (device: {device_id})" if device_id else ""))

        return jsonify({
            'status': 'success',
            'server_time': now.isoformat(),
            'current_mode': state.get('mode'),
            'cameras': state.get('cameras'),
            'presence_status': state.get('presence_status'),
            'device_registered': device_id is not None
        })

    except Exception as e:
        logger.error(f"Heartbeat error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# Legacy routes for backward compatibility
@app.route('/home')
def legacy_home():
    """Legacy route - redirects to heartbeat."""
    return heartbeat()


@app.route('/away')
def legacy_away():
    """Legacy route - log away event."""
    db.add_activity_log('PRESENCE', 'info', f'Legacy /away endpoint called from {request.remote_addr}')
    return jsonify({'status': 'logged', 'message': 'Use /heartbeat instead'})


# =============================================================================
# Flask Routes - API
# =============================================================================

@app.route('/status')
def status():
    """Simple health check endpoint."""
    try:
        db_health = db.check_database_health()
        state = db.get_system_state()

        status = 'OK' if db_health['connected'] else 'DEGRADED'

        return jsonify({
            'status': status,
            'timestamp': datetime.now(tz=tz).isoformat(),
            'mode': state.get('mode'),
            'cameras': state.get('cameras')
        })

    except Exception as e:
        return jsonify({'status': 'ERROR', 'error': str(e)}), 500


@app.route('/api/state')
@auth.login_required
def api_state():
    """Get current state machine state."""
    try:
        state = db.get_system_state()
        return jsonify(state)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/cameras')
@auth.login_required
def api_cameras():
    """Get camera list."""
    try:
        refresh_camera_list_if_needed()
        return jsonify({
            'cameras': camera_list,
            'count': len(camera_list),
            'last_updated': camera_list_last_updated.isoformat() if camera_list_last_updated else None
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/health/database')
@auth.login_required
def api_health_database():
    """Database health check."""
    try:
        health = db.check_database_health()
        return jsonify(health)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/health/wyze')
@auth.login_required
def api_health_wyze():
    """Wyze API health check."""
    try:
        stats = db.get_api_health_stats(hours=24)
        return jsonify({
            'available': wyze_client is not None,
            'stats_24h': stats,
            'camera_count': len(camera_list)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/health/system')
@auth.login_required
def api_health_system():
    """System resources health check."""
    try:
        return jsonify({
            'cpu_percent': psutil.cpu_percent(interval=1),
            'memory': psutil.virtual_memory()._asdict(),
            'disk': psutil.disk_usage('/')._asdict(),
            'uptime_seconds': (datetime.now(tz=tz) - system_start_time).total_seconds(),
            'uptime_human': str(timedelta(seconds=int((datetime.now(tz=tz) - system_start_time).total_seconds())))
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/health/all')
@auth.login_required
def api_health_all():
    """Aggregated health check."""
    try:
        return jsonify({
            'database': db.check_database_health(),
            'wyze': db.get_api_health_stats(hours=24),
            'system': {
                'cpu_percent': psutil.cpu_percent(interval=1),
                'memory': psutil.virtual_memory()._asdict(),
                'disk': psutil.disk_usage('/')._asdict(),
                'uptime_seconds': (datetime.now(tz=tz) - system_start_time).total_seconds()
            },
            'heartbeat': db.get_heartbeat_stats(hours=24),
            'cameras': db.get_camera_toggle_stats(hours=24)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats/historical')
@auth.login_required
def api_stats_historical():
    """Historical statistics."""
    try:
        hours = int(request.args.get('hours', 24))
        return jsonify({
            'heartbeats': db.get_heartbeat_stats(hours=hours),
            'camera_toggles': db.get_camera_toggle_stats(hours=hours),
            'state_machine': db.get_state_machine_stats(hours=hours),
            'api_health': db.get_api_health_stats(hours=hours)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/test-wyze', methods=['POST'])
@auth.login_required
def api_test_wyze():
    """Test Wyze API connection with provided credentials."""
    global last_test_wyze_time

    # Rate limit: 1 test per 10 seconds per IP
    user_ip = request.remote_addr
    now = time.time()

    if user_ip in last_test_wyze_time:
        if now - last_test_wyze_time[user_ip] < 10:
            return jsonify({
                'success': False,
                'message': 'Please wait 10 seconds between tests'
            }), 429

    last_test_wyze_time[user_ip] = now

    try:
        # Get credentials from request
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        api_key = data.get('api_key')
        api_id = data.get('api_id')
        totp_key = data.get('totp_key')  # Optional 2FA key

        if not all([email, password, api_key, api_id]):
            return jsonify({
                'success': False,
                'message': 'Missing required credentials'
            }), 400

        if not WYZE_AVAILABLE:
            return jsonify({
                'success': False,
                'message': 'Wyze SDK not installed'
            }), 500

        # Try to connect
        client_params = {
            'email': email,
            'password': password,
            'key_id': api_id,
            'api_key': api_key
        }

        # Add TOTP key if provided
        if totp_key:
            client_params['totp_key'] = totp_key

        test_client = WyzeClient(**client_params)

        # List cameras to verify connection
        cameras = test_client.cameras.list()
        camera_count = len(cameras)

        return jsonify({
            'success': True,
            'message': f'✓ Connected - {camera_count} camera(s) found',
            'camera_count': camera_count
        })

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Wyze test connection failed: {error_msg}", exc_info=True)

        if '429' in error_msg or 'Too Many Requests' in error_msg:
            return jsonify({
                'success': False,
                'message': '⚠ Rate limited by Wyze. Please wait 5 minutes and try again.'
            }), 429
        elif '400' in error_msg or 'Bad Request' in error_msg:
            # 400 errors often mean incorrect credentials or missing 2FA
            totp_provided = 'Yes' if totp_key else 'No'
            return jsonify({
                'success': False,
                'message': f'❌ Authentication failed (400 Bad Request). TOTP key provided: {totp_provided}. Check your credentials and ensure TOTP key is correct if 2FA is enabled.'
            }), 400
        else:
            return jsonify({
                'success': False,
                'message': f'Connection failed: {error_msg}'
            }), 500


@app.route('/api/generate-secret', methods=['POST'])
@auth.login_required
def api_generate_secret():
    """Generate a random webhook secret."""
    try:
        secret = secrets.token_hex(32)
        return jsonify({'secret': secret})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/debug/cameras')
@auth.login_required
def api_debug_cameras():
    """Debug endpoint to see raw camera data from Wyze API."""
    if not wyze_client:
        return jsonify({'error': 'Wyze client not initialized'}), 500

    try:
        # Get all cameras
        cameras = wyze_client.cameras.list()

        debug_data = {
            'total_count': len(cameras),
            'cameras': []
        }

        for cam in cameras:
            cam_info = {
                'mac': cam.mac,
                'nickname': cam.nickname,
                'product_model': cam.product.model,
                'product_type': cam.product.type,
                'type_name': type(cam).__name__,
                'has_device_params': hasattr(cam, 'device_params'),
                'attributes': dir(cam)
            }

            # Try to get device_params if it exists
            if hasattr(cam, 'device_params'):
                try:
                    cam_info['device_params'] = str(cam.device_params)
                except:
                    cam_info['device_params'] = 'Error reading device_params'

            # Try to get all attributes
            try:
                cam_info['all_data'] = {k: str(v) for k, v in cam.__dict__.items() if not k.startswith('_')}
            except:
                pass

            debug_data['cameras'].append(cam_info)

        return jsonify(debug_data)
    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


# =============================================================================
# Flask Routes - Device Management
# =============================================================================

@app.route('/devices')
@auth.login_required
def devices_page():
    """Device management page."""
    if not config.is_setup_complete():
        return redirect(url_for('setup'))

    try:
        devices = db.get_all_devices()
        online_devices = db.get_online_devices(minutes=HOME_THRESHOLD)
        online_device_ids = {d['device_id'] for d in online_devices}
        last_heartbeats = db.get_device_last_heartbeats()

        return render_template('devices.html',
                              devices=devices,
                              online_device_ids=online_device_ids,
                              last_heartbeats=last_heartbeats,
                              home_threshold=HOME_THRESHOLD)
    except Exception as e:
        logger.error(f"Devices page error: {e}", exc_info=True)
        return f"Error loading devices: {e}", 500


@app.route('/api/devices', methods=['GET'])
@auth.login_required
def api_get_devices():
    """Get all devices."""
    try:
        devices = db.get_all_devices()
        online_devices = db.get_online_devices(minutes=HOME_THRESHOLD)
        online_device_ids = {d['device_id'] for d in online_devices}

        # Add online status to each device
        for device in devices:
            device['is_online'] = device['device_id'] in online_device_ids

        return jsonify({'devices': devices})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/devices/<device_id>', methods=['GET'])
@auth.login_required
def api_get_device(device_id):
    """Get single device."""
    try:
        device = db.get_device(device_id)
        if not device:
            return jsonify({'error': 'Device not found'}), 404
        return jsonify(device)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/devices/<device_id>', methods=['PUT'])
@auth.login_required
def api_update_device(device_id):
    """Update device."""
    try:
        data = request.get_json()
        logger.info(f"UPDATE device request: device_id={device_id}, data={data}")

        allowed_fields = ['device_name', 'device_type', 'detection_method', 'enabled', 'notes']
        updates = {k: v for k, v in data.items() if k in allowed_fields}

        if not updates:
            logger.warning(f"No valid fields to update for device {device_id}")
            return jsonify({'error': 'No valid fields to update'}), 400

        success = db.update_device(device_id, updates)
        logger.info(f"Update device {device_id} result: {success}")

        if not success:
            logger.error(f"Device not found: {device_id}")
            return jsonify({'error': 'Device not found'}), 404

        return jsonify({'success': True, 'device': db.get_device(device_id)})
    except Exception as e:
        logger.error(f"Error updating device {device_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/devices/<device_id>', methods=['DELETE'])
@auth.login_required
def api_delete_device(device_id):
    """Delete device."""
    try:
        success = db.delete_device(device_id)
        if not success:
            return jsonify({'error': 'Device not found'}), 404

        db.add_activity_log('SYSTEM', 'info', f'Device deleted: {device_id}')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/devices/<device_id>/test', methods=['GET'])
@auth.login_required
def test_device_detection(device_id):
    """
    Test all detection methods for a specific device.
    Returns detailed results for ping, ARP, ARP-3X, and heartbeat checks.
    """
    try:
        # Get device info
        device = db.get_device(device_id)
        if not device:
            return jsonify({'error': 'Device not found'}), 404

        ip_address = device.get('last_ip')
        device_name = device.get('device_name', 'Unknown')
        detection_method = device.get('detection_method', 'both')

        results = {
            'device_id': device_id,
            'device_name': device_name,
            'ip_address': ip_address,
            'detection_method': detection_method,
            'tests': {}
        }

        # Test 1: Network Ping (TCP port scanning)
        logger.info(f"Testing PING for {device_name} ({ip_address})...")
        ping_start = time.time()
        ping_result = db.is_device_reachable(ip_address)
        ping_duration = time.time() - ping_start
        results['tests']['ping'] = {
            'result': ping_result,
            'duration_ms': round(ping_duration * 1000, 1),
            'method': 'TCP ports 62078, 5353, 3689'
        }

        # Test 2: ARP Detection (single attempt)
        logger.info(f"Testing ARP for {device_name} ({ip_address})...")
        arp_start = time.time()
        arp_result = db.is_device_reachable_arp(ip_address)
        arp_duration = time.time() - arp_start
        results['tests']['arp'] = {
            'result': arp_result,
            'duration_ms': round(arp_duration * 1000, 1),
            'method': 'Layer 2 ARP'
        }

        # Test 3: ARP-3X Detection (3 attempts, 2/3 threshold)
        logger.info(f"Testing ARP-3X for {device_name} ({ip_address})...")
        arp3x_start = time.time()
        arp3x_result = db.is_device_reachable_arp_3x(ip_address)
        arp3x_duration = time.time() - arp3x_start
        results['tests']['arp_3x'] = {
            'result': arp3x_result,
            'duration_ms': round(arp3x_duration * 1000, 1),
            'method': '3x ARP (2/3 threshold)'
        }

        # Test 4: Heartbeat Check
        last_seen = device.get('last_seen')
        if last_seen:
            tz = pytz.timezone(config.get('TIMEZONE', 'UTC'))
            last_seen_time = datetime.fromisoformat(last_seen)
            if last_seen_time.tzinfo is None:
                last_seen_time = tz.localize(last_seen_time)
            now = datetime.now(tz)
            minutes_ago = (now - last_seen_time).total_seconds() / 60
            heartbeat_result = minutes_ago < HOME_THRESHOLD
            results['tests']['heartbeat'] = {
                'result': heartbeat_result,
                'minutes_ago': round(minutes_ago, 1),
                'threshold_minutes': HOME_THRESHOLD,
                'last_seen': last_seen
            }
        else:
            results['tests']['heartbeat'] = {
                'result': False,
                'error': 'No heartbeat data'
            }

        # Overall recommendation
        results['recommendation'] = {
            'suggested_method': None,
            'reason': None
        }

        # Determine best detection method
        if arp3x_result:
            results['recommendation']['suggested_method'] = 'arp_3x'
            results['recommendation']['reason'] = 'ARP-3X successful (most robust)'
        elif arp_result:
            results['recommendation']['suggested_method'] = 'arp'
            results['recommendation']['reason'] = 'ARP successful (fast and reliable)'
        elif ping_result:
            results['recommendation']['suggested_method'] = 'ping'
            results['recommendation']['reason'] = 'Ping successful (fallback method)'
        elif results['tests']['heartbeat']['result']:
            results['recommendation']['suggested_method'] = 'heartbeat'
            results['recommendation']['reason'] = 'Only heartbeat available'
        else:
            results['recommendation']['suggested_method'] = 'both'
            results['recommendation']['reason'] = 'No methods successful - use hybrid mode'

        logger.info(f"Test results for {device_name}: {results['recommendation']}")
        return jsonify(results)

    except Exception as e:
        logger.error(f"Error testing device {device_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Flask Routes - Schedule Management
# =============================================================================

@app.route('/schedules')
@auth.login_required
def schedules_page():
    """Schedule management page."""
    if not config.is_setup_complete():
        return redirect(url_for('setup'))

    try:
        schedules = db.get_all_schedules()
        return render_template('schedules.html', schedules=schedules)
    except Exception as e:
        logger.error(f"Schedules page error: {e}", exc_info=True)
        return f"Error loading schedules: {e}", 500


@app.route('/api/schedules', methods=['GET'])
@auth.login_required
def api_get_schedules():
    """Get all schedules."""
    try:
        schedules = db.get_all_schedules()
        return jsonify({'schedules': schedules})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/schedules', methods=['POST'])
@auth.login_required
def api_create_schedule():
    """Create new schedule."""
    try:
        data = request.get_json()

        # Validate required fields
        required = ['name', 'days_of_week', 'start_time', 'end_time', 'cameras_state']
        for field in required:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        # Validate cameras_state
        if data['cameras_state'] not in ['on', 'off']:
            return jsonify({'error': 'cameras_state must be "on" or "off"'}), 400

        # Create schedule
        schedule_id = db.create_schedule(
            name=data['name'],
            days_of_week=data['days_of_week'],
            start_time=data['start_time'],
            end_time=data['end_time'],
            cameras_state=data['cameras_state'],
            enabled=data.get('enabled', True)
        )

        if schedule_id is None:
            return jsonify({'error': 'Failed to create schedule'}), 500

        db.add_activity_log('SYSTEM', 'info', f'Schedule created: {data["name"]}')
        return jsonify({'success': True, 'schedule_id': schedule_id, 'schedule': db.get_schedule(schedule_id)})

    except Exception as e:
        logger.error(f"Create schedule error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/schedules/<int:schedule_id>', methods=['GET'])
@auth.login_required
def api_get_schedule(schedule_id):
    """Get single schedule."""
    try:
        schedule = db.get_schedule(schedule_id)
        if not schedule:
            return jsonify({'error': 'Schedule not found'}), 404
        return jsonify(schedule)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/schedules/<int:schedule_id>', methods=['PUT'])
@auth.login_required
def api_update_schedule(schedule_id):
    """Update schedule."""
    try:
        data = request.get_json()
        allowed_fields = ['name', 'days_of_week', 'start_time', 'end_time', 'cameras_state', 'enabled']
        updates = {k: v for k, v in data.items() if k in allowed_fields}

        if not updates:
            return jsonify({'error': 'No valid fields to update'}), 400

        # Validate cameras_state if provided
        if 'cameras_state' in updates and updates['cameras_state'] not in ['on', 'off']:
            return jsonify({'error': 'cameras_state must be "on" or "off"'}), 400

        success = db.update_schedule(schedule_id, updates)
        if not success:
            return jsonify({'error': 'Schedule not found'}), 404

        db.add_activity_log('SYSTEM', 'info', f'Schedule updated: ID {schedule_id}')
        return jsonify({'success': True, 'schedule': db.get_schedule(schedule_id)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/schedules/<int:schedule_id>', methods=['DELETE'])
@auth.login_required
def api_delete_schedule(schedule_id):
    """Delete schedule."""
    try:
        schedule = db.get_schedule(schedule_id)
        if not schedule:
            return jsonify({'error': 'Schedule not found'}), 404

        success = db.delete_schedule(schedule_id)
        if not success:
            return jsonify({'error': 'Failed to delete schedule'}), 500

        db.add_activity_log('SYSTEM', 'info', f'Schedule deleted: {schedule["name"]}')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Initialization & Scheduler
# =============================================================================

def initialize_application():
    """Initialize application components."""
    logger.info("=" * 60)
    logger.info("WyzeGuardi Starting...")
    logger.info("=" * 60)

    # Initialize database
    logger.info("Initializing database...")
    db.init_db()

    # Initialize authentication database
    logger.info("Initializing authentication system...")
    auth.init_auth_db()

    # Initialize Wyze client
    logger.info("Initializing Wyze client...")
    wyze_success = init_wyze_client()

    if not wyze_success:
        logger.warning("Wyze client initialization failed - system will run in limited mode")

    # Log system start
    db.add_activity_log('SYSTEM', 'info', 'WyzeGuardi system started')

    logger.info("Application initialized successfully")
    logger.info(f"Dashboard: http://{FLASK_HOST}:{FLASK_PORT}")
    logger.info(f"Timezone: {TIMEZONE}")
    logger.info(f"Thresholds: HOME={HOME_THRESHOLD}min, AWAY={AWAY_THRESHOLD}min")
    logger.info("=" * 60)


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == '__main__':
    # Initialize application
    initialize_application()

    # Start scheduler
    scheduler = BackgroundScheduler(timezone=tz)
    scheduler.add_job(
        func=state_machine_tick,
        trigger='interval',
        minutes=STATE_MACHINE_INTERVAL,
        id='state_machine',
        name='State Machine Tick',
        replace_existing=True
    )
    scheduler.start()
    logger.info(f"Scheduler started (state machine runs every {STATE_MACHINE_INTERVAL} minute(s))")

    try:
        # Run Flask app
        app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
        scheduler.shutdown()
        db.add_activity_log('SYSTEM', 'info', 'WyzeGuardi system stopped')
        logger.info("Goodbye!")
