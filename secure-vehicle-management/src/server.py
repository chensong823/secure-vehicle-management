# -*- coding: utf-8 -*-
"""
Backend Server Node
===================

Business logic server that consumes messages from RabbitMQ and stores
vehicle data in Redis. Implements high availability with Redis
master-slave replication.

Architecture:
    RabbitMQ -> Server -> Redis Master -> Redis Slave
"""

import argparse
import logging
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

import pika
import redis

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import Config, get_config, RabbitMQConfig, RedisConfig
from src.utils.parsing import parse_data

logger = logging.getLogger(__name__)


class ServerNode:
    """
    Backend server for vehicle data management.

    Consumes messages from RabbitMQ and stores:
    - Vehicle locations
    - Lock status

    Features:
    - Redis master-slave replication
    - Automatic failover to backup Redis
    - Health status logging for monitoring
    """

    def __init__(
        self,
        host: str,
        port: int,
        health_log_file: str,
        health_interval: int,
        mq_config: RabbitMQConfig,
        redis_config: RedisConfig,
    ):
        """
        Initialize server node.

        Args:
            host: Server bind address
            port: Server port
            health_log_file: Path to health log file
            health_interval: Interval for health logging (seconds)
            mq_config: RabbitMQ configuration
            redis_config: Redis configuration
        """
        self.host = host
        self.port = port
        self.health_log_file = health_log_file
        self.health_interval = health_interval

        # RabbitMQ configuration
        self.mq_config = mq_config
        self.mq_channel: Optional[pika.channel.Channel] = None
        self.mq_connection: Optional[pika.BlockingConnection] = None

        # Redis configuration
        self.redis_config = redis_config
        self.r: Optional[redis.Redis] = None
        self.backup_r: Optional[redis.Redis] = None

        # Initialize connections
        self._connect_rabbitmq()
        self._connect_redis()

        # Ensure log directory exists
        log_dir = os.path.dirname(health_log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        logger.info(f"Server initialized on {host}:{port}")

    def _connect_rabbitmq(self) -> None:
        """Connect to RabbitMQ."""
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

        self.mq_connection = pika.BlockingConnection(parameters)
        self.mq_channel = self.mq_connection.channel()

        logger.info("Connected to RabbitMQ")

    def _connect_redis(self) -> None:
        """Connect to Redis master and slave."""
        try:
            self.r = redis.Redis(
                host=self.redis_config.host,
                port=self.redis_config.port,
                db=self.redis_config.db,
                password=self.redis_config.password,
                socket_timeout=self.redis_config.socket_timeout,
                socket_connect_timeout=self.redis_config.socket_connect_timeout,
                decode_responses=True,
            )
            # Test connection
            self.r.ping()
            logger.info(f"Connected to Redis master at {self.redis_config.host}:{self.redis_config.port}")
        except redis.ConnectionError as e:
            logger.error(f"Failed to connect to Redis master: {e}")
            self.r = None

        # Connect to backup (slave)
        try:
            self.backup_r = redis.Redis(
                host=self.redis_config.host,
                port=self.redis_config.backup_port,
                db=self.redis_config.db,
                password=self.redis_config.password,
                socket_timeout=self.redis_config.socket_timeout,
                socket_connect_timeout=self.redis_config.socket_connect_timeout,
                decode_responses=True,
            )
            self.backup_r.ping()
            logger.info(f"Connected to Redis slave at {self.redis_config.host}:{self.redis_config.backup_port}")
        except redis.ConnectionError as e:
            logger.warning(f"Failed to connect to Redis slave: {e}")
            self.backup_r = None

    def _get_redis(self) -> Optional[redis.Redis]:
        """
        Get active Redis connection with failover.

        Returns:
            Redis client or None if unavailable
        """
        if self.r:
            try:
                self.r.ping()
                return self.r
            except redis.ConnectionError:
                logger.warning("Redis master unavailable, trying backup")
                self.r = None

        if self.backup_r:
            try:
                self.backup_r.ping()
                return self.backup_r
            except redis.ConnectionError:
                logger.error("Redis slave also unavailable")
                self.backup_r = None

        # Try to reconnect
        self._connect_redis()
        return self.r

    def _on_message(
        self,
        ch: pika.channel.Channel,
        method: pika.spec.Basic.Deliver,
        properties: pika.spec.BasicProperties,
        body: bytes,
    ) -> None:
        """
        Callback for processing RabbitMQ messages.

        Args:
            ch: Channel
            method: Delivery method
            properties: Message properties
            body: Message body
        """
        try:
            message = body.decode("utf-8")
            logger.info(f"Received message: {message[:100]}...")

            # Parse message
            parsed = parse_data(message, verify_hash=True)
            if not parsed:
                logger.warning("Failed to parse message or hash mismatch")
                return

            client = parsed["client"]
            action = parsed["action"]
            data = parsed["message"]

            # Store in Redis
            r = self._get_redis()
            if not r:
                logger.error("No Redis connection available")
                return

            if action == "LockStatus":
                key = f"{client}_LockStatus"
                r.set(key, data)
                logger.info(f"Stored {key} = {data}")

            elif action == "Location":
                key = f"{client}_Location"
                r.set(key, data)
                logger.info(f"Stored {key} = {data}")

            elif action == "KeyExchange":
                # Key exchange messages - log but don't store
                logger.debug(f"Key exchange from {client}")

            else:
                logger.warning(f"Unknown action: {action}")

        except Exception as e:
            logger.error(f"Message processing error: {e}\n{traceback.format_exc()}")

    def start_consuming(self) -> None:
        """
        Start consuming messages from RabbitMQ queue.
        """
        if not self.mq_channel:
            logger.error("No RabbitMQ channel available")
            return

        self.mq_channel.basic_consume(
            queue=self.mq_config.queue_name,
            on_message_callback=self._on_message,
            auto_ack=True,
        )

        logger.info(f"Waiting for messages on queue: {self.mq_config.queue_name}")
        logger.info("Press CTRL+C to exit")

        try:
            self.mq_channel.start_consuming()
        except KeyboardInterrupt:
            logger.info("Stopping consumer...")
            self.mq_channel.stop_consuming()

    def log_health_status(self) -> None:
        """
        Log health status periodically.

        Writes to health log file for monitoring by Monitor module.
        """
        logger.info("Health logging started")

        while True:
            try:
                log_message = f"{self.host}:{self.port} - alive"
                # Use WARNING level for health log to separate from debug logs
                logging.warning(log_message)
                time.sleep(self.health_interval)
            except Exception as e:
                logger.error(f"Health logging error: {e}")
                break

    def get_vehicle_data(self, vehicle_name: str) -> dict:
        """
        Get all data for a specific vehicle.

        Args:
            vehicle_name: Name of the vehicle

        Returns:
            Dictionary with location and lock status
        """
        r = self._get_redis()
        if not r:
            return {"error": "Redis unavailable"}

        location = r.get(f"{vehicle_name}_Location")
        lock_status = r.get(f"{vehicle_name}_LockStatus")

        return {
            "vehicle": vehicle_name,
            "location": location,
            "lock_status": lock_status,
        }

    def close(self) -> None:
        """Close all connections."""
        if self.mq_connection:
            try:
                self.mq_connection.close()
            except Exception as e:
                logger.warning(f"Error closing RabbitMQ connection: {e}")

        if self.r:
            try:
                self.r.close()
            except Exception as e:
                logger.warning(f"Error closing Redis master: {e}")

        if self.backup_r:
            try:
                self.backup_r.close()
            except Exception as e:
                logger.warning(f"Error closing Redis slave: {e}")

        logger.info("Server connections closed")


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Start the backend server node.")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host address")
    parser.add_argument("--port", type=int, default=10021, help="Port number")
    parser.add_argument(
        "--config", type=str, help="Path to config file"
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point for server."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    args = parse_arguments()

    # Load configuration
    config = get_config(args.config)

    # Create server
    server = ServerNode(
        host=args.host,
        port=args.port,
        health_log_file=config.server.health_log_file,
        health_interval=config.server.health_interval,
        mq_config=config.server.rabbitmq,
        redis_config=config.server.redis,
    )

    # Log startup
    logging.warning(f"{server.host}:{server.port} - started")

    # Start health logging thread
    health_thread = threading.Thread(target=server.log_health_status)
    health_thread.daemon = True
    health_thread.start()

    # Start consuming messages
    try:
        server.start_consuming()
    except KeyboardInterrupt:
        logging.warning(f"{server.host}:{server.port} - stopped")
    finally:
        server.close()


if __name__ == "__main__":
    main()