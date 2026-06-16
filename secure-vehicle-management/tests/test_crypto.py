# -*- coding: utf-8 -*-
"""
Test Suite for Secure Vehicle Management System
"""

import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.utils.crypto import (
    sha256_hash,
    rsa_encrypt,
    rsa_decrypt,
    generate_aes_key,
    encrypt_aes,
    decrypt_aes,
    load_rsa_public_key,
    load_rsa_private_key,
)
from src.utils.parsing import parse_data, wrap_data, create_signed_message


class TestCryptoUtils:
    """Tests for cryptographic utilities."""

    def test_sha256_hash(self):
        """Test SHA-256 hash function."""
        result = sha256_hash("hello")
        assert len(result) == 64  # SHA-256 produces 64 hex characters
        assert result == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    def test_sha256_hash_empty(self):
        """Test SHA-256 with empty string."""
        result = sha256_hash("")
        assert len(result) == 64
        assert result == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_sha256_hash_different_inputs(self):
        """Test SHA-256 produces different hashes for different inputs."""
        hash1 = sha256_hash("lock")
        hash2 = sha256_hash("unlock")
        assert hash1 != hash2

    def test_generate_aes_key(self):
        """Test AES key generation."""
        key = generate_aes_key()
        assert isinstance(key, bytes)
        assert len(key) == 44  # Fernet keys are URL-safe base64-encoded 32-byte keys

    def test_aes_encrypt_decrypt(self):
        """Test AES encryption and decryption."""
        key = generate_aes_key()
        original_data = b"Hello, Vehicle!"

        encrypted = encrypt_aes(key, original_data)
        assert encrypted != original_data

        decrypted = decrypt_aes(key, encrypted)
        assert decrypted == original_data

    def test_aes_encrypt_different_keys(self):
        """Test that different keys produce different ciphertext."""
        key1 = generate_aes_key()
        key2 = generate_aes_key()
        data = b"Test message"

        encrypted1 = encrypt_aes(key1, data)
        encrypted2 = encrypt_aes(key2, data)

        assert encrypted1 != encrypted2


class TestParsingUtils:
    """Tests for message parsing utilities."""

    def test_wrap_data(self):
        """Test data wrapping."""
        result = wrap_data("vehicle_a", "LockStatus", "locked", "abc123")
        assert isinstance(result, bytes)
        decoded = result.decode("utf-8")
        assert "vehicle_a" in decoded
        assert "LockStatus" in decoded
        assert "locked" in decoded
        assert "abc123" in decoded

    def test_parse_data_valid(self):
        """Test parsing valid message."""
        # Create a signed message
        msg_bytes, hash_code = create_signed_message("vehicle_a", "Location", "Ottawa")
        decoded = msg_bytes.decode("utf-8")

        result = parse_data(decoded, verify_hash=True)
        assert result is not None
        assert result["client"] == "vehicle_a"
        assert result["action"] == "Location"
        assert result["message"] == "Ottawa"

    def test_parse_data_invalid_hash(self):
        """Test parsing with invalid hash."""
        # Create message with wrong hash
        msg_bytes = wrap_data("vehicle_a", "LockStatus", "locked", "invalid_hash")
        decoded = msg_bytes.decode("utf-8")

        result = parse_data(decoded, verify_hash=True)
        assert result is None

    def test_parse_data_wrong_format(self):
        """Test parsing with wrong format."""
        result = parse_data("invalid data format", verify_hash=True)
        assert result is None

    def test_create_signed_message(self):
        """Test signed message creation."""
        node_name = "vehicle_a"
        action = "Location"
        message = "Ottawa, ON"

        msg_bytes, hash_code = create_signed_message(node_name, action, message)

        assert isinstance(msg_bytes, bytes)
        assert len(hash_code) == 64

        # Verify the message can be parsed
        parsed = parse_data(msg_bytes.decode("utf-8"), verify_hash=True)
        assert parsed is not None
        assert parsed["message"] == message


class TestDataIntegrity:
    """Tests for data integrity verification."""

    def test_message_integrity_verification(self):
        """Test that tampered messages are detected."""
        # Create valid message
        msg_bytes, _ = create_signed_message("vehicle_a", "LockStatus", "unlocked")
        decoded = msg_bytes.decode("utf-8")

        # Verify original
        result = parse_data(decoded, verify_hash=True)
        assert result is not None

        # Tamper with message
        tampered = decoded.replace("unlocked", "locked")
        # Note: The hash won't match because we didn't update it

        # Verify tampered message is rejected
        result = parse_data(tampered, verify_hash=True)
        assert result is None

    def test_avalanche_effect(self):
        """Test that small changes produce big hash changes."""
        hash1 = sha256_hash("lock")
        hash2 = sha256_hash("locka")  # One character difference

        # Count different characters
        diff_count = sum(c1 != c2 for c1, c2 in zip(hash1, hash2))
        assert diff_count > 30  # More than ~46% of 64 characters should differ


class TestEndToEnd:
    """End-to-end integration tests."""

    def test_full_message_flow(self):
        """Test complete message creation and verification flow."""
        # Client creates message
        node_name = "vehicle_a"
        action = "Location"
        message = "1125 Colonel By Dr, Ottawa"

        msg_bytes, hash_code = create_signed_message(node_name, action, message)

        # Simulate transmission
        transmitted = msg_bytes.decode("utf-8")

        # Server receives and verifies
        parsed = parse_data(transmitted, verify_hash=True)

        assert parsed is not None
        assert parsed["client"] == node_name
        assert parsed["action"] == action
        assert parsed["message"] == message

    def test_encrypted_message_flow(self):
        """Test encrypted message creation and decryption."""
        # Client generates key and encrypts
        aes_key = generate_aes_key()
        original_msg = b"[vehicle_a] - [Location] - Ottawa - abc123"

        encrypted = encrypt_aes(aes_key, original_msg)
        assert encrypted != original_msg

        # Server decrypts
        decrypted = decrypt_aes(aes_key, encrypted)
        assert decrypted == original_msg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])