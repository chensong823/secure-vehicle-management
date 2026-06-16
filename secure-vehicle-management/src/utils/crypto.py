# -*- coding: utf-8 -*-
"""
Cryptography Utilities
=====================

Provides cryptographic functions for the secure vehicle management system:
- RSA encryption/decryption with OAEP padding
- AES symmetric encryption using Fernet
- SHA-256 hashing for message integrity
"""

import base64
import hashlib
import logging
from pathlib import Path
from typing import Optional, Union

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey, RSAPrivateKey
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)


def rsa_encrypt(public_key: RSAPublicKey, message: str) -> str:
    """
    Encrypt a message using RSA public key with OAEP padding.

    Args:
        public_key: RSA public key object
        message: Plain text message to encrypt

    Returns:
        Base64-encoded encrypted message
    """
    encrypted = public_key.encrypt(
        message.encode("utf-8"),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(encrypted).decode("utf-8")


def rsa_decrypt(private_key: RSAPrivateKey, encrypted_message: str) -> str:
    """
    Decrypt a message using RSA private key with OAEP padding.

    Args:
        private_key: RSA private key object
        encrypted_message: Base64-encoded encrypted message

    Returns:
        Decrypted plain text message
    """
    encrypted_bytes = base64.b64decode(encrypted_message)
    decrypted = private_key.decrypt(
        encrypted_bytes,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return decrypted.decode("utf-8")


def sha256_hash(string: str) -> str:
    """
    Compute SHA-256 hash of a string.

    Args:
        string: Input string to hash

    Returns:
        Hexadecimal hash digest
    """
    hash_object = hashlib.sha256(string.encode("utf-8"))
    return hash_object.hexdigest()


def generate_aes_key() -> bytes:
    """
    Generate a new Fernet-compatible AES key.

    Returns:
        32-byte key suitable for Fernet encryption
    """
    return Fernet.generate_key()


def encrypt_aes(key: bytes, data: bytes) -> bytes:
    """
    Encrypt data using AES Fernet.

    Args:
        key: Fernet key (32 bytes)
        data: Plain text data to encrypt

    Returns:
        Encrypted data
    """
    cipher = Fernet(key)
    return cipher.encrypt(data)


def decrypt_aes(key: bytes, encrypted_data: bytes) -> Optional[bytes]:
    """
    Decrypt data using AES Fernet.

    Args:
        key: Fernet key (32 bytes)
        encrypted_data: Encrypted data

    Returns:
        Decrypted data or None if decryption fails
    """
    try:
        cipher = Fernet(key)
        return cipher.decrypt(encrypted_data)
    except InvalidToken:
        logger.error("AES decryption failed: Invalid token")
        return None


def load_rsa_public_key(key_path: Optional[str] = None) -> RSAPublicKey:
    """
    Load RSA public key from PEM file.

    Args:
        key_path: Path to public key file. If None, uses default path.

    Returns:
        RSA public key object
    """
    if key_path is None:
        key_path = str(
            Path(__file__).parent.parent.parent / "certs" / "rsa_public_key.pem"
        )

    with open(key_path, "rb") as f:
        return serialization.load_pem_public_key(f.read())


def load_rsa_private_key(
    key_path: Optional[str] = None, password: Optional[bytes] = None
) -> RSAPrivateKey:
    """
    Load RSA private key from PEM file.

    Args:
        key_path: Path to private key file. If None, uses default path.
        password: Optional password for encrypted key file

    Returns:
        RSA private key object
    """
    if key_path is None:
        key_path = str(
            Path(__file__).parent.parent.parent / "certs" / "rsa_private_key.pem"
        )

    with open(key_path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=password)


def generate_rsa_keypair(
    public_key_path: Optional[str] = None, private_key_path: Optional[str] = None
) -> tuple:
    """
    Generate a new RSA keypair and save to PEM files.

    Args:
        public_key_path: Path to save public key
        private_key_path: Path to save private key

    Returns:
        Tuple of (public_key, private_key) objects
    """
    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    public_key = private_key.public_key()

    # Save private key
    if private_key_path:
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with open(private_key_path, "wb") as f:
            f.write(private_pem)

    # Save public key
    if public_key_path:
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        with open(public_key_path, "wb") as f:
            f.write(public_pem)

    return public_key, private_key


def create_ssl_context(
    certfile: str,
    keyfile: Optional[str] = None,
    is_server: bool = True,
    verify_locations: Optional[str] = None,
) -> "ssl.SSLContext":
    """
    Create an SSL context for secure communication.

    Args:
        certfile: Path to certificate file
        keyfile: Path to private key file
        is_server: True for server context, False for client
        verify_locations: CA certificate file for verifying peer

    Returns:
        Configured SSL context
    """
    import ssl

    if is_server:
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        if keyfile:
            context.load_cert_chain(certfile, keyfile)
        else:
            context.load_cert_chain(certfile)
    else:
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        if verify_locations:
            context.load_verify_locations(verify_locations)
        context.verify_mode = ssl.CERT_REQUIRED

    context.check_hostname = False
    return context