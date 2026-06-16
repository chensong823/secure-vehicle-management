# -*- coding: utf-8 -*-
"""
SSL/TLS Gateway Node
====================

Acts as the secure gateway between vehicle clients and the backend services.
Handles:
- TLS/mTLS mutual authentication with clients
- RSA-AES hybrid decryption for key exchange
- Message routing to RabbitMQ message queue
- Remote control commands to vehicles

Architecture:
    Client (mTLS) -> Gateway -> RabbitMQ -> Server -> Redis
"""

import argparse
import logging
import socket
import ssl
import sys
import threading
import traceback
from pathlib import Path
from typing import Dict, Optional

import pika

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import Config, get_config, RabbitMQConfig
from src.utils.crypto import (
    load_rsa_private_key,
    load_rsa_public_key,
    generate_aes_key,
    encrypt_aes,
    decrypt_aes,
    rsa_decrypt,
    sha256_hash,
)
from src.utils.parsing import wrap_data, create_signed_message, parse_data

logger = logging.getLogger(__name__)


class GatewayNode:
    """
    SSL/TLS Gateway for vehicle management system.

    Responsibilities:
    - Accept mTLS connections from clients
    - Decrypt RSA-encrypted AES keys during handshake
    - Route messages to RabbitMQ
    - Send remote control commands to vehicles
    """

    def __init__(
        self,
        host: str,
        port: int,
        certfile: str,
        keyfile: str,
        client_certfile: str,
        rsa_private_key_path: str,
        rsa_public_key_path: str,
        mq_config: RabbitMQConfig,
    ):
        """
        Initialize gateway node.

        Args:
            host: Bind address
            port: Listen port
            certfile: Gateway SSL certificate
            keyfile: Gateway SSL private key
            client_certfile: CA certificate for verifying clients
            rsa_private_key_path: Path to RSA private key
            rsa_public_key_path: Path to RSA public key
            mq_config: RabbitMQ configuration
        """
        self.node_name = "gateway"
        self.host = host
        self.port = port
        self.bindsocket: Optional[socket.socket] = None

        # SSL/TLS configuration
        self.certfile = certfile
        self.keyfile = keyfile
        self.client_certfile = client_certfile

        # Create SSL context for mutual TLS
        self.ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        self.ssl_context.verify_mode = ssl.CERT_REQUIRED
        self.ssl_context.load_cert_chain(certfile, keyfile)
        self.ssl_context.load_verify_locations(client_certfile)
        self.ssl_context.check_hostname = False

        # RSA keys for key exchange
        self.rsa_private_key = load_rsa_private_key(rsa_private_key_path)
        self.rsa_public_key = load_rsa_public_key(rsa_public_key_path)

        # Client session management (address -> AES key mapping)
        self.client_fernet_keys: Dict[str, bytes] = {}
        self.client_connections: Dict[str, ssl.SSLSocket] = {}
        self.client_names: Dict[str, str] = {}

        # RabbitMQ configuration
        self.mq_config = mq_config
        self.mq_channel: Optional[pika.channel.Channel] = None

        logger.info(f"Gateway initialized on {host}:{port}")

    def connect_to_mq(self) -> None:
        """
        Establish connection to RabbitMQ and set up exchange/queue.

        Raises:
            Exception: If connection fails
        """
        credentials = pika.PlainCredentials(
            self.mq_config.user, self.mq_config.passwd
        )
        parameters = pika.ConnectionParameters(
            host=self.mq_config.host,
            port=self.mq_config.port,
            virtual_host=self.mq_config.vhost,
            credentials=credentials,
            heartbeat=self.mq_config.heartbeat,
        )

        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()

        # Declare exchange
        channel.exchange_declare(
            exchange=self.mq_config.exchange_name, exchange_type="direct"
        )

        # Declare queue
        channel.queue_declare(queue=self.mq_config.queue_name, durable=True)

        # Bind queue to exchange
        channel.queue_bind(
            exchange=self.mq_config.exchange_name,
            queue=self.mq_config.queue_name,
            routing_key=self.mq_config.routing_key,
        )

        self.mq_channel = channel
        logger.info("Connected to RabbitMQ")

    def start_server(self) -> None:
        """
        Start the gateway server and listen for connections.
        """
        # Connect to RabbitMQ
        try:
            self.connect_to_mq()
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise

        # Create and bind socket
        self.bindsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.bindsocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.bindsocket.bind((self.host, self.port))
            self.bindsocket.listen(5)
            logger.info(f"Gateway listening on {self.host}:{self.port}")
        except socket.error as e:
            logger.error(f"Socket bind failed: {e}")
            raise

        # Accept connections
        while True:
            try:
                client_socket, client_addr = self.bindsocket.accept()
                logger.info(f"Accepted connection from {client_addr}")

                # Wrap with SSL
                conn = self.ssl_context.wrap_socket(
                    client_socket, server_side=True
                )

                # Handle in separate thread
                thread = threading.Thread(
                    target=self._handle_client, args=(conn, client_addr)
                )
                thread.daemon = True
                thread.start()

            except ssl.SSLError as e:
                logger.error(f"SSL error: {e}")
            except Exception as e:
                logger.error(f"Accept error: {e}\n{traceback.format_exc()}")

    def _handle_client(
        self, conn: ssl.SSLSocket, addr: tuple
    ) -> None:
        """
        Handle communication with a connected client.

        Args:
            conn: SSL connection
            addr: Client address tuple
        """
        addr_str = f"{addr[0]}:{addr[1]}"
        logger.info(f"Handling client {addr_str}")

        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    break

                data_str = data.decode("utf-8")
                logger.info(f"Received from {addr_str}: {data_str[:100]}...")

                # Check if this client has completed key exchange
                if addr_str in self.client_fernet_keys:
                    # Normal encrypted communication
                    self._handle_encrypted_message(conn, addr_str, data)
                else:
                    # Key exchange phase
                    self._handle_key_exchange(conn, addr_str, data_str)

        except ssl.SSLError as e:
            logger.error(f"SSL error for {addr_str}: {e}")
        except Exception as e:
            logger.error(f"Handler error for {addr_str}: {e}\n{traceback.format_exc()}")
        finally:
            conn.shutdown(socket.SHUT_RDWR)
            conn.close()
            # Clean up client state
            self._cleanup_client(addr_str)

    def _handle_key_exchange(
        self, conn: ssl.SSLSocket, addr_str: str, data: str
    ) -> None:
        """
        Handle RSA key exchange from client.

        Args:
            conn: SSL connection
            addr_str: Client address string
            data: Encrypted key exchange message
        """
        try:
            # Decrypt with RSA private key
            decrypted = rsa_decrypt(self.rsa_private_key, data)
            logger.info(f"Decrypted key exchange: {decrypted}")

            # Parse the message
            parsed = parse_data(decrypted, verify_hash=False)
            if not parsed:
                logger.error("Failed to parse key exchange message")
                return

            # Extract AES key
            aes_key = parsed["message"].encode("utf-8")
            self.client_fernet_keys[addr_str] = aes_key

            client_name = parsed["client"]
            self.client_names[addr_str] = client_name

            # Send confirmation
            self._send_confirmation(conn, aes_key)

            # Store connection
            self.client_connections[addr_str] = conn

            logger.info(f"Key exchange completed for {client_name}")

        except Exception as e:
            logger.error(f"Key exchange failed: {e}")
            logger.debug(traceback.format_exc())

    def _handle_encrypted_message(
        self, conn: ssl.SSLSocket, addr_str: str, data: bytes
    ) -> None:
        """
        Handle encrypted message from established session.

        Args:
            conn: SSL connection
            addr_str: Client address string
            data: Encrypted message
        """
        aes_key = self.client_fernet_keys.get(addr_str)
        if not aes_key:
            logger.error(f"No AES key for {addr_str}")
            return

        try:
            decrypted = decrypt_aes(aes_key, data)
            if not decrypted:
                logger.error("AES decryption failed")
                return

            message = decrypted.decode("utf-8")
            logger.info(f"Decrypted message: {message}")

            # Send to RabbitMQ
            self._send_to_mq(message)

        except Exception as e:
            logger.error(f"Message handling error: {e}")

    def _send_confirmation(self, conn: ssl.SSLSocket, aes_key: bytes) -> None:
        """
        Send connection confirmation to client.

        Args:
            conn: SSL connection
            aes_key: AES key for encryption
        """
        response_msg = "Secure communication established."
        wrapped, _ = create_signed_message(self.node_name, "ConnectionEstablished", response_msg)
        encrypted = encrypt_aes(aes_key, wrapped)
        conn.send(encrypted)

    def _send_to_mq(self, message: str) -> None:
        """
        Send message to RabbitMQ.

        Args:
            message: Message to send
        """
        if self.mq_channel:
            self.mq_channel.basic_publish(
                exchange=self.mq_config.exchange_name,
                routing_key=self.mq_config.routing_key,
                body=message,
            )
            logger.info(f"Message sent to RabbitMQ: {message[:50]}...")

    def _cleanup_client(self, addr_str: str) -> None:
        """
        Clean up client session state.

        Args:
            addr_str: Client address string
        """
        self.client_fernet_keys.pop(addr_str, None)
        self.client_connections.pop(addr_str, None)
        logger.info(f"Cleaned up client {addr_str}")

    def remote_control(
        self, node_name: str, action: str, message: str
    ) -> bool:
        """
        Send remote control command to a vehicle.

        Args:
            node_name: Target vehicle name
            action: Action to perform
            message: Message content

        Returns:
            True if sent successfully
        """
        # Find client by name
        addr_str = None
        for addr, name in self.client_names.items():
            if name == node_name:
                addr_str = addr
                break

        if not addr_str:
            logger.error(f"Unknown node: {node_name}")
            return False

        aes_key = self.client_fernet_keys.get(addr_str)
        if not aes_key:
            logger.error(f"No AES key for {node_name}")
            return False

        conn = self.client_connections.get(addr_str)
        if not conn:
            logger.error(f"No connection for {node_name}")
            return False

        try:
            # Create and encrypt message
            wrapped, _ = create_signed_message(self.node_name, action, message)
            encrypted = encrypt_aes(aes_key, wrapped)
            conn.send(encrypted)
            logger.info(f"Sent {action} to {node_name}")
            return True

        except Exception as e:
            logger.error(f"Remote control failed: {e}")
            return False


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Start the gateway node.")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host address")
    parser.add_argument("--port", type=int, default=10001, help="Port number")
    parser.add_argument("--config", type=str, help="Path to config file")
    return parser.parse_args()


def main() -> None:
    """Main entry point for gateway."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    args = parse_arguments()

    # Load configuration
    config = get_config(args.config)

    # Determine paths
    base_dir = Path(__file__).parent.parent
    cert_dir = base_dir / "certs"

    # Create and start gateway
    gateway = GatewayNode(
        host=args.host,
        port=args.port,
        certfile=str(cert_dir / "admin_cert.pem"),
        keyfile=str(cert_dir / "admin_key.pem"),
        client_certfile=str(cert_dir / "vehicle_a_cert.pem"),
        rsa_private_key_path=str(cert_dir / "rsa_private_key.pem"),
        rsa_public_key_path=str(cert_dir / "rsa_public_key.pem"),
        mq_config=config.server.rabbitmq,
    )

    # Start gateway server
    gateway.start_server()


if __name__ == "__main__":
    main()