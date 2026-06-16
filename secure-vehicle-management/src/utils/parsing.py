# -*- coding: utf-8 -*-
"""
Data Parsing Utilities
======================

Provides functions for parsing and formatting vehicle management messages.
Implements the message protocol with integrity verification.
"""

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# Message format: [node_name] - [action] - message - hash_code
MESSAGE_DELIMITER = " - "
FIELD_COUNT = 4


@dataclass
class ParsedMessage:
    """Parsed message data structure."""

    client: str
    action: str
    message: str
    hash_code: str

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary."""
        return {
            "client": self.client,
            "action": self.action,
            "message": self.message,
            "hash_code": self.hash_code,
        }


class DataParser:
    """
    Parser for vehicle management message protocol.

    Message Format:
        [node_name] - [action] - message - hash_code

    Example:
        [vehicle_a] - [LockStatus] - locked - a8b3c4d5...
    """

    def __init__(self, verify_hash: bool = True):
        """
        Initialize parser.

        Args:
            verify_hash: Whether to verify message integrity (default True)
        """
        self.verify_hash = verify_hash

    def parse(self, data: str) -> Optional[ParsedMessage]:
        """
        Parse and validate a log entry data.

        Args:
            data: Raw message string

        Returns:
            ParsedMessage object if valid, None otherwise
        """
        from .crypto import sha256_hash

        parts = data.strip().split(MESSAGE_DELIMITER)

        if len(parts) != FIELD_COUNT:
            logger.error(f"Invalid message format: expected {FIELD_COUNT} fields, got {len(parts)}")
            return None

        client, action, message, hash_code = parts
        client = client.strip("[]")
        action = action.strip("[]")

        if self.verify_hash:
            computed_hash = sha256_hash(message)
            if computed_hash != hash_code:
                logger.error("Hash verification failed - message integrity compromised")
                logger.debug(f"Expected: {computed_hash}, Got: {hash_code}")
                return None

        return ParsedMessage(
            client=client,
            action=action,
            message=message,
            hash_code=hash_code,
        )

    def format(
        self, node_name: str, action: str, message: str, hash_code: str
    ) -> bytes:
        """
        Format data into protocol message.

        Args:
            node_name: Name of the node
            action: Action type
            message: Message content
            hash_code: SHA-256 hash of message

        Returns:
            Formatted message as bytes
        """
        data = f"[{node_name}] - [{action}] - {message} - {hash_code}"
        return data.encode("utf-8")


def wrap_data(node_name: str, action: str, message: str, hash_code: str) -> bytes:
    """
    Format and encode data into a protocol message.

    This is a convenience function using the default parser.

    Args:
        node_name: Name of the node
        action: Action type
        message: Message content
        hash_code: SHA-256 hash of message

    Returns:
        Formatted message as bytes
    """
    parser = DataParser(verify_hash=False)
    return parser.format(node_name, action, message, hash_code)


def parse_data(data: str, verify_hash: bool = True) -> Optional[Dict[str, str]]:
    """
    Parse and validate a log entry data.

    Args:
        data: Raw message string
        verify_hash: Whether to verify message integrity

    Returns:
        Dictionary with parsed fields if valid, None otherwise
    """
    parser = DataParser(verify_hash=verify_hash)
    result = parser.parse(data)
    if result:
        return result.to_dict()
    return None


def create_signed_message(
    node_name: str, action: str, message: str
) -> tuple:
    """
    Create a message with SHA-256 integrity signature.

    Args:
        node_name: Name of the node
        action: Action type
        message: Message content

    Returns:
        Tuple of (formatted_message_bytes, hash_code)
    """
    from .crypto import sha256_hash

    hash_code = sha256_hash(message)
    formatted = wrap_data(node_name, action, message, hash_code)
    return formatted, hash_code