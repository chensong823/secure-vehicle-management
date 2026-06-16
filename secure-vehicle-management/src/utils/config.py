# -*- coding: utf-8 -*-
"""
Configuration Management
=========================

Centralized configuration management for the Secure Vehicle Management System.
Loads configuration from YAML files and environment variables.
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass, field

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass
class RabbitMQConfig:
    """RabbitMQ configuration."""
    host: str = "127.0.0.1"
    port: int = 5672
    vhost: str = "/egen5202_host"
    user: str = "egen5202"
    passwd: str = "egen5202"
    exchange_name: str = "exchange_name"
    routing_key: str = "routing_key"
    queue_name: str = "egen5202"
    heartbeat: int = 30


@dataclass
class RedisConfig:
    """Redis configuration."""
    host: str = "127.0.0.1"
    port: int = 6379
    backup_port: int = 6380
    db: int = 0
    password: str = "egen5202"
    socket_timeout: int = 5
    socket_connect_timeout: int = 5


@dataclass
class SSLConfig:
    """SSL/TLS configuration."""
    certfile: str = "certs/admin_cert.pem"
    keyfile: str = "certs/admin_key.pem"
    client_certfile: str = "certs/vehicle_a_cert.pem"
    client_keyfile: str = "certs/vehicle_a_key.pem"
    rsa_public_key: str = "certs/rsa_public_key.pem"
    rsa_private_key: str = "certs/rsa_private_key.pem"


@dataclass
class GatewayConfig:
    """Gateway configuration."""
    host: str = "0.0.0.0"
    port: int = 10001
    ssl: SSLConfig = field(default_factory=SSLConfig)


@dataclass
class ServerConfig:
    """Server configuration."""
    host: str = "0.0.0.0"
    port: int = 10021
    health_log_file: str = "logs/health.log"
    health_interval: int = 5
    rabbitmq: RabbitMQConfig = field(default_factory=RabbitMQConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)


@dataclass
class ClientConfig:
    """Client configuration."""
    host: str = "127.0.0.1"
    port: int = 10011
    gateway_host: str = "127.0.0.1"
    gateway_port: int = 10001
    node_id: str = "1"
    node_name: str = "vehicle_a"
    location: str = "1125 Colonel By Dr, Ottawa"
    ssl: SSLConfig = field(default_factory=SSLConfig)


@dataclass
class MonitorConfig:
    """Monitor configuration."""
    log_file: str = "logs/health.log"
    check_interval: int = 6
    restart_command: str = "python -m src.server"


@dataclass
class AppConfig:
    """Application configuration."""
    env: str = "development"
    debug: bool = False


class Config:
    """
    Centralized configuration manager.

    Loads configuration from:
    1. Default values
    2. YAML config file
    3. Environment variables (.env file)
    """

    _instance: Optional["Config"] = None

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration.

        Args:
            config_path: Path to YAML config file. If None, uses default.
        """
        self.app = AppConfig()
        self.gateway = GatewayConfig()
        self.server = ServerConfig()
        self.client = ClientConfig()
        self.monitor = MonitorConfig()

        # Load environment variables
        load_dotenv()

        # Load YAML config if provided
        if config_path is None:
            config_path = str(
                Path(__file__).parent.parent.parent / "configs" / "config.yaml"
            )

        if os.path.exists(config_path):
            self._load_yaml(config_path)

        # Override with environment variables
        self._load_env()

    def _load_yaml(self, config_path: str) -> None:
        """Load configuration from YAML file."""
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data:
                return

            # Parse app config
            if "app" in data:
                self.app = AppConfig(**data["app"])

            # Parse gateway config
            if "gateway" in data:
                gateway_data = data["gateway"].copy()
                ssl_data = gateway_data.pop("ssl", {})
                self.gateway = GatewayConfig(
                    host=gateway_data.get("host", "0.0.0.0"),
                    port=gateway_data.get("port", 10001),
                    ssl=SSLConfig(**ssl_data) if ssl_data else SSLConfig(),
                )

            # Parse server config
            if "server" in data:
                server_data = data["server"].copy()
                self.server = ServerConfig(
                    host=server_data.get("host", "0.0.0.0"),
                    port=server_data.get("port", 10021),
                    health_log_file=server_data.get("health_log_file", "logs/health.log"),
                    health_interval=server_data.get("health_interval", 5),
                )

            # Parse client config
            if "client" in data:
                client_data = data["client"].copy()
                ssl_data = client_data.pop("ssl", {})
                self.client = ClientConfig(
                    host=client_data.get("host", "127.0.0.1"),
                    port=client_data.get("port", 10011),
                    gateway_host=client_data.get("gateway_host", "127.0.0.1"),
                    gateway_port=client_data.get("gateway_port", 10001),
                    node_id=client_data.get("node_id", "1"),
                    node_name=client_data.get("node_name", "vehicle_a"),
                    location=client_data.get("location", ""),
                    ssl=SSLConfig(**ssl_data) if ssl_data else SSLConfig(),
                )

            # Parse monitor config
            if "monitor" in data:
                self.monitor = MonitorConfig(**data["monitor"])

            logger.info(f"Loaded configuration from {config_path}")

        except Exception as e:
            logger.warning(f"Failed to load config from {config_path}: {e}")

    def _load_env(self) -> None:
        """Override configuration with environment variables."""
        # RabbitMQ
        if os.getenv("RABBITMQ_HOST"):
            self.server.rabbitmq.host = os.getenv("RABBITMQ_HOST")
        if os.getenv("RABBITMQ_USER"):
            self.server.rabbitmq.user = os.getenv("RABBITMQ_USER")
        if os.getenv("RABBITMQ_PASS"):
            self.server.rabbitmq.passwd = os.getenv("RABBITMQ_PASS")

        # Redis
        if os.getenv("REDIS_HOST"):
            self.server.redis.host = os.getenv("REDIS_HOST")
        if os.getenv("REDIS_PASSWORD"):
            self.server.redis.password = os.getenv("REDIS_PASSWORD")

        # Application
        if os.getenv("APP_ENV"):
            self.app.env = os.getenv("APP_ENV")
        if os.getenv("DEBUG"):
            self.app.debug = os.getenv("DEBUG").lower() == "true"

    def get_rabbitmq_url(self) -> str:
        """Get RabbitMQ connection URL."""
        return (
            f"amqp://{self.server.rabbitmq.user}:{self.server.rabbitmq.passwd}"
            f"@{self.server.rabbitmq.host}:{self.server.rabbitmq.port}"
            f"/{self.server.rabbitmq.vhost}"
        )

    def get_redis_url(self, use_backup: bool = False) -> str:
        """Get Redis connection URL."""
        port = self.server.redis.backup_port if use_backup else self.server.redis.port
        return f"redis://:{self.server.redis.password}@{self.server.redis.host}:{port}/{self.server.redis.db}"


def get_config(config_path: Optional[str] = None) -> Config:
    """
    Get singleton configuration instance.

    Args:
        config_path: Optional path to config file

    Returns:
        Config singleton instance
    """
    if Config._instance is None:
        Config._instance = Config(config_path)
    return Config._instance


def reset_config() -> None:
    """Reset configuration singleton (useful for testing)."""
    Config._instance = None