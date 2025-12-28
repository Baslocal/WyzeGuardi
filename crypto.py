"""
WyzeGuardi Cryptography Module
Handles encryption and decryption of sensitive data.
"""

import os
from cryptography.fernet import Fernet


class CryptoManager:
    """Manages encryption/decryption using Fernet symmetric encryption."""

    def __init__(self, key_file='.db_key'):
        """
        Initialize crypto manager.

        Args:
            key_file: Path to encryption key file (relative to script dir)
        """
        # Get absolute path to script directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.key_file = os.path.join(script_dir, key_file)

        self.key = self.load_or_create_key()
        self.cipher = Fernet(self.key)

    def load_or_create_key(self):
        """
        Load encryption key from file, or create new one if doesn't exist.

        Returns:
            bytes: Encryption key
        """
        if os.path.exists(self.key_file):
            with open(self.key_file, 'rb') as f:
                return f.read()
        else:
            # Generate new key
            key = Fernet.generate_key()

            # Save to file
            with open(self.key_file, 'wb') as f:
                f.write(key)

            # Set permissions to owner-only
            os.chmod(self.key_file, 0o600)

            return key

    def get_key_hex(self):
        """
        Get encryption key as hex string (for display to user).

        Returns:
            str: Hex representation of key
        """
        return self.key.hex()

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt plaintext string.

        Args:
            plaintext: String to encrypt

        Returns:
            str: Encrypted string (base64 encoded)
        """
        if not plaintext:
            return ''

        encrypted_bytes = self.cipher.encrypt(plaintext.encode('utf-8'))
        return encrypted_bytes.decode('utf-8')

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt ciphertext string.

        Args:
            ciphertext: Encrypted string (base64 encoded)

        Returns:
            str: Decrypted plaintext string
        """
        if not ciphertext:
            return ''

        try:
            decrypted_bytes = self.cipher.decrypt(ciphertext.encode('utf-8'))
            return decrypted_bytes.decode('utf-8')
        except Exception:
            # If decryption fails, return empty string
            return ''


# Global instance
_crypto_instance = None


def get_crypto():
    """
    Get global CryptoManager instance (singleton pattern).

    Returns:
        CryptoManager: Crypto manager instance
    """
    global _crypto_instance
    if _crypto_instance is None:
        _crypto_instance = CryptoManager()
    return _crypto_instance
