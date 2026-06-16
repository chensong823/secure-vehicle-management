# -*- coding: utf-8 -*-
"""
Vehicle Client Node
===================

Simulates a vehicle that connects to the secure vehicle management system.
Handles secure communication with the gateway using TLS/mTLS and
RSA-AES hybrid encryption.

Features:
- TLS 1.3 mutual authentication
- RSA-OAEP key exchange for AES key
- AES-128 (Fernet) symmetric encryption
- SHA-256 message integrity verification
"""

import argparse
import logging
import os
import socket
import ssl
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import Config, get_config
from src.utils.crypto import (
    create_ssl_context,
    load_rsa_public_key,
    generate_aes_key,
    encrypt_aes,
    decrypt_aes,
    rsa_encrypt,
    sha256_hash,
)
from src.utils.parsing import wrap_data, create_signed_message

logger = logging.getLogger(__name__)


class VehicleClient:
    """
    Vehicle client node that connects to the gateway.

    Implements secure communication with:
    - TLS/mTLS for transport layer security
    - RSA-AES hybrid encryption for data protection
    - SHA-256 for message integrity
    """

    def __init__(
        self,
        node_id: str,
        node_name: str,
        host: str,
        port: int,
        gateway_host: str,
        gateway_port: int,
        certfile: str,
        keyfile: str,
        admin_certfile: str,
        rsa_public_key_path: str,
        location: str = "Unknown",
    ):
        """
        Initialize vehicle client.

        Args:
            node_id: Unique vehicle identifier
            node_name: Human-readable vehicle name
            host: Local bind address
            port: Local listen port
            gateway_host: Gateway server address
            gateway_port: Gateway server port
            certfile: Vehicle SSL certificate
            keyfile: Vehicle SSL private key
            admin_certfile: Admin/Gateway certificate for verification
            rsa_public_key_path: Path to RSA public key
            location: Initial vehicle location
        """
        self.node_id = node_id
        self.node_name = node_name
        self.host = host
        self.port = port
        self.gateway_host = gateway_host
        self.gateway_port = gateway_port
        self.location = location
        self.lock_status = False

        # SSL/TLS configuration
        self.certfile = certfile
        self.keyfile = keyfile
        self.admin_certfile = admin_certfile

        # Create SSL context for mutual TLS
        self.ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        self.ssl_context.verify_mode = ssl.CERT_REQUIRED
        self.ssl_context.load_cert_chain(certfile, keyfile)
        self.ssl_context.load_verify_locations(admin_certfile)
        self.ssl_context.check_hostname = False

        # AES key for symmetric encryption
        self.aes_key = generate_aes_key()
        self.cipher_suite = None  # Will be set after key exchange

        # RSA public key for key exchange
        self.rsa_public_key = load_rsa_public_key(rsa_public_key_path)

        # Connection state
        self.server_conn: Optional[ssl.SSLSocket] = None
        self.bindsocket: Optional[socket.socket] = None

        logger.info(f"Vehicle {node_name} initialized at {host}:{port}")

    def connect_to_gateway(self) -> bool:
        """
        Establish secure connection to the gateway.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Create socket
            self.bindsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            logger.info("Socket created successfully")

            # Wrap with SSL
            conn = self.ssl_context.wrap_socket(
                self.bindsocket, server_hostname=self.gateway_host
            )

            # Connect to gateway
            conn.connect((self.gateway_host, self.gateway_port))
            logger.info(
                f"Connected to gateway at {self.gateway_host}:{self.gateway_port}"
            )

            # Perform key exchange
            self._perform_key_exchange(conn)

            # Set cipher suite
            self.cipher_suite = self.aes_key

            # Receive connection confirmation
            self._receive_connection_response(conn)

            self.server_conn = conn
            return True

        except ssl.SSLError as e:
            logger.error(f"SSL connection failed: {e}")
            return False
        except socket.error as e:
            logger.error(f"Socket connection failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Connection failed: {e}\n{traceback.format_exc()}")
            return False

    def _perform_key_exchange(self, conn: ssl.SSLSocket) -> None:
        """
        Exchange AES key with gateway using RSA encryption.

        Args:
            conn: SSL connection to gateway
        """
        # Create key exchange message
        key_exchange_msg, _ = create_signed_message(
            self.node_name, "KeyExchange", self.aes_key.decode("utf-8")
        )

        # Encrypt AES key with RSA
        encrypted_key = rsa_encrypt(self.rsa_public_key, key_exchange_msg)
        conn.send(encrypted_key.encode("utf-8"))

        logger.info("AES key sent to gateway via RSA encryption")

    def _receive_connection_response(self, conn: ssl.SSLSocket) -> None:
        """
        Receive and process connection response from gateway.

        Args:
            conn: SSL connection to gateway
        """
        data = conn.recv(4096)
        if data:
            decrypted = decrypt_aes(self.aes_key, data)
            if decrypted:
                logger.info(f"Received: {decrypted.decode('utf-8')}")

    def send_location(self, location: Optional[str] = None) -> bool:
        """
        Send vehicle location to server.

        Args:
            location: Location string. If None, uses current location.

        Returns:
            True if sent successfully
        """
        if not self.server_conn:
            logger.error("Not connected to server")
            return False

        location = location or self.location
        self.location = location

        try:
            # Create signed message
            msg_bytes, _ = create_signed_message(
                self.node_name, "Location", location
            )

            # Encrypt with AES
            encrypted = encrypt_aes(self.aes_key, msg_bytes)
            self.server_conn.send(encrypted)

            logger.info(f"Location sent: {location}")
            return True

        except Exception as e:
            logger.error(f"Failed to send location: {e}")
            return False

    def send_lock_status(self, locked: bool) -> bool:
        """
        Send lock status to server.

        Args:
            locked: True if locked, False if unlocked

        Returns:
            True if sent successfully
        """
        if not self.server_conn:
            logger.error("Not connected to server")
            return False

        self.lock_status = locked
        status = "locked" if locked else "unlocked"

        try:
            msg_bytes, _ = create_signed_message(
                self.node_name, "LockStatus", status
            )
            encrypted = encrypt_aes(self.aes_key, msg_bytes)
            self.server_conn.send(encrypted)

            logger.info(f"Lock status sent: {status}")
            return True

        except Exception as e:
            logger.error(f"Failed to send lock status: {e}")
            return False

    def lock(self) -> bool:
        """
        Lock the vehicle and notify server.

        Returns:
            True if successful
        """
        return self.send_lock_status(True)

    def unlock(self) -> bool:
        """
        Unlock the vehicle and notify server.

        Returns:
            True if successful
        """
        return self.send_lock_status(False)

    def update_location(self, location: str) -> bool:
        """
        Update vehicle location and notify server.

        Args:
            location: New location string

        Returns:
            True if successful
        """
        self.location = location
        return self.send_location(location)

    def close(self) -> None:
        """Close the connection gracefully."""
        if self.server_conn:
            try:
                self.server_conn.shutdown(socket.SHUT_RDWR)
                self.server_conn.close()
            except Exception as e:
                logger.warning(f"Error closing connection: {e}")


def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="Start the vehicle client node with specified configuration."
    )
    parser.add_argument(
        "--host", type=str, default="127.0.0.1", help="Local host address"
    )
    parser.add_argument("--port", type=int, default=10011, help="Local port number")
    parser.add_argument("--node_id", type=str, default="1", help="Node ID")
    parser.add_argument(
        "--node_name", type=str, default="vehicle_a", help="Node name"
    )
    parser.add_argument(
        "--gateway_host", type=str, default="127.0.0.1", help="Gateway host address"
    )
    parser.add_argument(
        "--gateway_port", type=int, default=10001, help="Gateway port"
    )
    parser.add_argument("--location", type=str, help="Initial location")
    parser.add_argument(
        "--config", type=str, help="Path to config file"
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point for vehicle client."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    args = parse_arguments()

    # Load configuration
    config = get_config()

    # Determine paths
    base_dir = Path(__file__).parent.parent
    cert_dir = base_dir / "certs"

    # Create client
    client = VehicleClient(
        node_id=args.node_id,
        node_name=args.node_name,
        host=args.host,
        port=args.port,
        gateway_host=args.gateway_host,
        gateway_port=args.gateway_port,
        certfile=str(cert_dir / "vehicle_a_cert.pem"),
        keyfile=str(cert_dir / "vehicle_a_key.pem"),
        admin_certfile=str(cert_dir / "admin_cert.pem"),
        rsa_public_key_path=str(cert_dir / "rsa_public_key.pem"),
        location=args.location or config.client.location,
    )

    # Connect to gateway
    if not client.connect_to_gateway():
        logger.error("Failed to connect to gateway")
        sys.exit(1)

    # Start command loop
    logger.info("Vehicle client started. Enter commands:")
    while True:
        try:
            user_input = input("> ")
            if user_input == "lock":
                client.lock()
            elif user_input == "unlock":
                client.unlock()
            elif user_input == "location":
                location_input = input("Enter new location: ")
                client.update_location(location_input)
            elif user_input == "status":
                print(f"Location: {client.location}")
                print(f"Lock Status: {'Locked' if client.lock_status else 'Unlocked'}")
            elif user_input == "quit":
                print("Shutting down...")
                client.close()
                break
            else:
                print("Commands: lock, unlock, location, status, quit")
        except KeyboardInterrupt:
            print("\nShutting down...")
            client.close()
            break
        except Exception as e:
            logger.error(f"Error: {e}")


if __name__ == "__main__":
    main()