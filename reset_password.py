#!/usr/bin/env python3
"""
WyzeGuardi Password Reset Utility
Allows command-line password reset for admin users.
"""

import sys
import sqlite3
import getpass
from pathlib import Path

# Import auth module for password hashing
try:
    import auth
except ImportError:
    print("Error: auth.py module not found in current directory")
    sys.exit(1)

DB_PATH = 'wyzeguardi.db'


def list_users():
    """List all users in the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT username, created_at, last_login FROM users ORDER BY created_at")
        users = cursor.fetchall()
        conn.close()

        if not users:
            print("No users found in database.")
            return []

        print("\nCurrent users:")
        print("-" * 60)
        for user in users:
            print(f"  Username: {user['username']}")
            print(f"  Created:  {user['created_at']}")
            print(f"  Last login: {user['last_login'] or 'Never'}")
            print("-" * 60)

        return [user['username'] for user in users]

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return []
    except Exception as e:
        print(f"Error listing users: {e}")
        return []


def reset_password(username, new_password=None):
    """
    Reset password for specified user.

    Args:
        username: Username to reset
        new_password: New password (if None, will prompt)

    Returns:
        bool: Success status
    """
    try:
        # Check if user exists
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()

        if not user:
            conn.close()
            print(f"\nError: User '{username}' not found.")
            print("Note: Username is case-sensitive.")
            return False

        # Get new password if not provided
        if new_password is None:
            print(f"\nResetting password for user: {username}")
            print("Password requirements:")
            print("  - Minimum 8 characters")
            print("  - No maximum length")
            print()

            while True:
                new_password = getpass.getpass("Enter new password: ")

                if len(new_password) < 8:
                    print("Error: Password must be at least 8 characters.")
                    continue

                confirm_password = getpass.getpass("Confirm new password: ")

                if new_password != confirm_password:
                    print("Error: Passwords do not match. Try again.")
                    continue

                break
        else:
            # Validate provided password
            if len(new_password) < 8:
                print("Error: Password must be at least 8 characters.")
                conn.close()
                return False

        # Hash new password
        password_hash = auth.hash_password(new_password)

        # Update password
        cursor.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (password_hash, username)
        )
        conn.commit()
        conn.close()

        print(f"\n✓ Password reset successfully for user: {username}")
        print("You can now login with the new password.")
        return True

    except Exception as e:
        print(f"\nError resetting password: {e}")
        return False


def main():
    """Main function."""
    print("=" * 60)
    print("WyzeGuardi Password Reset Utility")
    print("=" * 60)

    # Check if database exists
    if not Path(DB_PATH).exists():
        print(f"\nError: Database file '{DB_PATH}' not found.")
        print("Make sure you're running this from the WyzeGuardi directory.")
        sys.exit(1)

    # List all users
    usernames = list_users()

    if not usernames:
        print("\nNo users to reset. Create a user first via /register.")
        sys.exit(1)

    # Get username
    if len(sys.argv) > 1:
        # Username provided as argument
        username = sys.argv[1]
    else:
        # Prompt for username
        print("\nEnter the username to reset password for.")
        print("Note: Username is case-sensitive (e.g., 'Admin' not 'admin')")
        username = input("Username: ").strip()

    if not username:
        print("Error: Username cannot be empty.")
        sys.exit(1)

    # Reset password
    success = reset_password(username)

    if success:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
