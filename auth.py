"""
WyzeGuardi Authentication Module
Handles user authentication, session management, and route protection.
"""

import bcrypt
import sqlite3
import logging
from datetime import datetime
from functools import wraps
from flask import session, redirect, url_for, request
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Database path
DB_PATH = 'wyzeguardi.db'


def hash_password(password: str) -> str:
    """
    Hash password using bcrypt.
    
    Args:
        password: Plain text password
        
    Returns:
        str: Hashed password
    """
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify password against hash.
    
    Args:
        password: Plain text password
        password_hash: Stored password hash
        
    Returns:
        bool: True if password matches
    """
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False


def create_user(username: str, password: str) -> Tuple[bool, str]:
    """
    Create new user account.
    
    Args:
        username: Username
        password: Plain text password
        
    Returns:
        Tuple[bool, str]: (Success status, Error message if any)
    """
    try:
        # Validate input
        if not username or len(username) < 3:
            return False, "Username must be at least 3 characters"
        
        if not password or len(password) < 8:
            return False, "Password must be at least 8 characters"
        
        # Check if user already exists
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            conn.close()
            return False, "User already exists"
        
        # Hash password
        password_hash = hash_password(password)
        
        # Create user
        now = datetime.utcnow().isoformat()
        cursor.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, now)
        )
        conn.commit()
        conn.close()
        
        logger.info(f"User created: {username}")
        return True, ""
        
    except Exception as e:
        logger.error(f"Create user error: {e}", exc_info=True)
        return False, f"Error creating user: {e}"


def authenticate_user(username: str, password: str) -> Tuple[bool, Optional[dict]]:
    """
    Authenticate user credentials.
    
    Args:
        username: Username
        password: Plain text password
        
    Returns:
        Tuple[bool, Optional[dict]]: (Success status, User data if successful)
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        
        if not user:
            conn.close()
            logger.warning(f"Login attempt for non-existent user: {username}")
            return False, None
        
        # Verify password
        if not verify_password(password, user['password_hash']):
            conn.close()
            logger.warning(f"Failed login attempt for user: {username}")
            return False, None
        
        # Update last login
        now = datetime.utcnow().isoformat()
        cursor.execute("UPDATE users SET last_login = ? WHERE username = ?", (now, username))
        conn.commit()
        conn.close()
        
        logger.info(f"Successful login: {username}")
        
        return True, {
            'id': user['id'],
            'username': user['username'],
            'created_at': user['created_at'],
            'last_login': now
        }
        
    except Exception as e:
        logger.error(f"Authentication error: {e}", exc_info=True)
        return False, None


def get_user_count() -> int:
    """
    Get total number of users in database.
    
    Returns:
        int: Number of users
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        logger.error(f"Get user count error: {e}")
        return 0


def has_users() -> bool:
    """
    Check if any users exist in database.
    
    Returns:
        bool: True if users exist
    """
    return get_user_count() > 0


def login_required(f):
    """
    Decorator to protect routes that require authentication.
    Redirects to login page if user not authenticated.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            logger.warning(f"Unauthorized access attempt to {request.path} from {request.remote_addr}")
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated_function


def init_auth_db():
    """
    Initialize authentication database tables.
    Creates users table if it doesn't exist.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Create users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_login TEXT
            )
        ''')
        
        # Create index
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)')
        
        conn.commit()
        conn.close()
        
        logger.info("Authentication database initialized")

    except Exception as e:
        logger.error(f"Auth DB initialization error: {e}", exc_info=True)


def has_users() -> bool:
    """
    Check if any users exist in the database.
    Used to determine if this is first-time setup.

    Returns:
        bool: True if at least one user exists, False otherwise
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users')
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    except Exception as e:
        logger.error(f"Error checking for existing users: {e}")
        # If we can't check, assume users exist (fail secure)
        return True


def change_password(username: str, old_password: str, new_password: str) -> Tuple[bool, str]:
    """
    Change user password.
    
    Args:
        username: Username
        old_password: Current password
        new_password: New password
        
    Returns:
        Tuple[bool, str]: (Success status, Error message if any)
    """
    try:
        # Validate new password
        if not new_password or len(new_password) < 8:
            return False, "New password must be at least 8 characters"
        
        # Authenticate with old password
        success, user = authenticate_user(username, old_password)
        if not success:
            return False, "Current password is incorrect"
        
        # Hash new password
        password_hash = hash_password(new_password)
        
        # Update password
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password_hash = ? WHERE username = ?", (password_hash, username))
        conn.commit()
        conn.close()
        
        logger.info(f"Password changed for user: {username}")
        return True, ""
        
    except Exception as e:
        logger.error(f"Change password error: {e}", exc_info=True)
        return False, f"Error changing password: {e}"
