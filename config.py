"""
WyzeGuardi Configuration Manager
Loads configuration from database (priority) or .env file (fallback).
"""

import os
import logging
from typing import Optional
from dotenv import load_dotenv
import database as db

logger = logging.getLogger(__name__)

# Load .env file
load_dotenv()


class ConfigManager:
    """Manages application configuration with DB-first, .env-second priority."""

    def __init__(self):
        """Initialize config manager and load settings."""
        self.config = {}
        self.load_config()

    def is_setup_complete(self) -> bool:
        """
        Check if initial setup wizard has been completed.

        Returns:
            bool: True if setup is complete
        """
        return db.is_setup_complete()

    def load_config(self):
        """Load configuration from database (priority) or environment variables (fallback)."""

        # If setup not complete, use defaults only
        if not self.is_setup_complete():
            self._load_defaults()
            return

        # Load from database (with decryption)
        try:
            db_settings = db.get_all_settings_decrypted()
        except Exception as e:
            logger.error(f"Failed to load settings from database: {e}")
            db_settings = {}

        # Helper function to get value with fallback priority
        def get_value(key: str, env_var: str, default: any) -> any:
            # Priority: Database > Environment > Default
            db_value = db_settings.get(key)
            if db_value is not None and db_value != '':
                return db_value

            env_value = os.getenv(env_var)
            if env_value is not None:
                return env_value

            return default

        # Wyze credentials
        self.config['wyze_email'] = get_value('wyze_email', 'WYZE_EMAIL', '')
        self.config['wyze_password'] = get_value('wyze_password', 'WYZE_PASSWORD', '')
        self.config['wyze_api_key'] = get_value('wyze_api_key', 'WYZE_API_KEY', '')
        self.config['wyze_api_id'] = get_value('wyze_api_id', 'WYZE_API_ID', '')
        self.config['wyze_totp_key'] = get_value('wyze_totp_key', 'WYZE_TOTP_KEY', '')

        # Security
        self.config['webhook_secret'] = get_value('webhook_secret', 'WEBHOOK_SECRET', '')

        # Server
        self.config['flask_port'] = int(get_value('flask_port', 'FLASK_PORT', 5000))
        self.config['flask_host'] = get_value('flask_host', 'FLASK_HOST', '0.0.0.0')

        # Thresholds
        self.config['home_threshold'] = int(get_value('home_threshold', 'HOME_THRESHOLD', 10))
        self.config['away_threshold'] = int(get_value('away_threshold', 'AWAY_THRESHOLD', 30))
        self.config['manual_override_duration'] = int(get_value('manual_override_duration', 'MANUAL_OVERRIDE_DURATION', 2))
        self.config['state_machine_interval'] = int(get_value('state_machine_interval', 'STATE_MACHINE_INTERVAL', 5))

        # Schedule settings
        self.config['weekday_home_start'] = int(get_value('weekday_home_start', 'WEEKDAY_HOME_START', 8))
        self.config['weekday_home_end'] = int(get_value('weekday_home_end', 'WEEKDAY_HOME_END', 18))
        self.config['weekend_home_start'] = int(get_value('weekend_home_start', 'WEEKEND_HOME_START', 9))
        self.config['weekend_home_end'] = int(get_value('weekend_home_end', 'WEEKEND_HOME_END', 23))

        # System
        self.config['timezone'] = get_value('timezone', 'TZ', 'America/New_York')
        self.config['log_level'] = get_value('log_level', 'LOG_LEVEL', 'INFO')
        self.config['log_file'] = get_value('log_file', 'LOG_FILE', 'app.log')

    def _load_defaults(self):
        """Load default configuration values (when setup not complete)."""
        self.config = {
            'wyze_email': '',
            'wyze_password': '',
            'wyze_api_key': '',
            'wyze_api_id': '',
            'wyze_totp_key': '',
            'webhook_secret': '',
            'flask_port': int(os.getenv('FLASK_PORT', 5000)),
            'flask_host': os.getenv('FLASK_HOST', '0.0.0.0'),
            'home_threshold': int(os.getenv('HOME_THRESHOLD', 10)),
            'away_threshold': int(os.getenv('AWAY_THRESHOLD', 30)),
            'manual_override_duration': int(os.getenv('MANUAL_OVERRIDE_DURATION', 2)),
            'state_machine_interval': int(os.getenv('STATE_MACHINE_INTERVAL', 5)),
            'weekday_home_start': int(os.getenv('WEEKDAY_HOME_START', 8)),
            'weekday_home_end': int(os.getenv('WEEKDAY_HOME_END', 18)),
            'weekend_home_start': int(os.getenv('WEEKEND_HOME_START', 9)),
            'weekend_home_end': int(os.getenv('WEEKEND_HOME_END', 23)),
            'timezone': os.getenv('TZ', 'America/New_York'),
            'log_level': os.getenv('LOG_LEVEL', 'INFO'),
            'log_file': os.getenv('LOG_FILE', 'app.log')
        }

    def get(self, key: str, default: any = None) -> any:
        """
        Get configuration value by key.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        return self.config.get(key, default)

    def get_all(self) -> dict:
        """
        Get all configuration values.

        Returns:
            dict: All configuration values
        """
        return self.config.copy()

    def save_config(self, new_config: dict) -> bool:
        """
        Save configuration to database.

        Args:
            new_config: Dictionary of configuration values

        Returns:
            bool: True if successful
        """
        try:
            # Encrypted settings (must match database.py:884-891)
            encrypted_keys = ['wyze_email', 'wyze_password', 'wyze_api_key', 'wyze_api_id', 'wyze_totp_key', 'webhook_secret']

            for key, value in new_config.items():
                if key in encrypted_keys:
                    db.set_encrypted_setting(key, str(value))
                else:
                    db.set_setting(key, str(value))

            # Mark setup as complete
            db.mark_setup_complete()

            # Reload configuration
            self.load_config()

            return True

        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
            return False

    def has_wyze_credentials(self) -> bool:
        """
        Check if Wyze credentials are configured.

        Returns:
            bool: True if all credentials are set
        """
        return all([
            self.config.get('wyze_email'),
            self.config.get('wyze_password'),
            self.config.get('wyze_api_key'),
            self.config.get('wyze_api_id')
        ])


# Global instance
_config_instance = None


def get_config() -> ConfigManager:
    """
    Get global ConfigManager instance (singleton pattern).

    Returns:
        ConfigManager: Config manager instance
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = ConfigManager()
    return _config_instance


def reload_config():
    """Reload configuration from database (call after settings change)."""
    global _config_instance
    if _config_instance is not None:
        _config_instance.load_config()
