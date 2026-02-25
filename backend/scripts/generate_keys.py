#!/usr/bin/env python3
"""
AIRA Backend - Key Generation Script

This script generates various security keys needed for the backend:
- Master Key: AES-256-GCM encryption key (32 bytes, base64 encoded)
- JWT Secret: For signing JWT tokens
- Admin Password: Secure random password

Usage:
    python scripts/generate_keys.py
    python scripts/generate_keys.py --master-key-only
    python scripts/generate_keys.py --output .env.generated
"""

import argparse
import base64
import os
import secrets
import string
import sys
from pathlib import Path


def generate_master_key() -> str:
    """Generate a 32-byte AES-256 master key, base64-urlsafe encoded."""
    key_bytes = os.urandom(32)
    return base64.urlsafe_b64encode(key_bytes).decode("utf-8")


def generate_jwt_secret(length: int = 64) -> str:
    """Generate a secure JWT secret key."""
    return secrets.token_urlsafe(length)


def generate_secure_password(length: int = 16) -> str:
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    # Ensure at least one of each character type
    password = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*"),
    ]
    # Fill the rest
    password.extend(secrets.choice(alphabet) for _ in range(length - 4))
    # Shuffle
    secrets.SystemRandom().shuffle(password)
    return "".join(password)


def main():
    parser = argparse.ArgumentParser(description="Generate security keys for AIRA Backend")
    parser.add_argument(
        "--master-key-only",
        action="store_true",
        help="Only generate and print the master key",
    )
    parser.add_argument(
        "--jwt-only",
        action="store_true",
        help="Only generate and print the JWT secret",
    )
    parser.add_argument(
        "--password-only",
        action="store_true",
        help="Only generate and print a secure password",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file to write generated keys (e.g., .env.generated)",
    )
    parser.add_argument(
        "--create-master-key-file",
        type=str,
        default=None,
        help="Create master key file at specified path",
    )

    args = parser.parse_args()

    # Single key generation modes
    if args.master_key_only:
        print(generate_master_key())
        return 0

    if args.jwt_only:
        print(generate_jwt_secret())
        return 0

    if args.password_only:
        print(generate_secure_password())
        return 0

    # Generate all keys
    master_key = generate_master_key()
    jwt_secret = generate_jwt_secret()
    admin_password = generate_secure_password()

    # Print to console
    print("=" * 60)
    print("AIRA Backend - Generated Security Keys")
    print("=" * 60)
    print()
    print("Master Key (AES-256-GCM, base64):")
    print(f"  ADMIN_MASTER_KEY_B64={master_key}")
    print()
    print("JWT Secret Key:")
    print(f"  JWT_SECRET_KEY={jwt_secret}")
    print()
    print("Admin Password:")
    print(f"  ADMIN_PASSWORD={admin_password}")
    print()
    print("=" * 60)
    print()

    # Create master key file if requested
    if args.create_master_key_file:
        key_path = Path(args.create_master_key_file)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(master_key, encoding="utf-8")
        os.chmod(key_path, 0o600)
        print(f"✓ Master key file created: {key_path}")
        print()

    # Write to output file if specified
    if args.output:
        output_path = Path(args.output)
        content = f"""# Generated keys for AIRA Backend
# Generated at: {os.popen("date").read().strip()}
# WARNING: Keep these values secret!

ADMIN_MASTER_KEY_B64={master_key}
JWT_SECRET_KEY={jwt_secret}
ADMIN_PASSWORD={admin_password}
"""
        output_path.write_text(content, encoding="utf-8")
        os.chmod(output_path, 0o600)
        print(f"✓ Keys written to: {output_path}")
        print()

    print("IMPORTANT:")
    print("  1. Copy the relevant values to your .env file")
    print("  2. Never commit .env or key files to version control")
    print("  3. Store backup copies of keys securely")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
