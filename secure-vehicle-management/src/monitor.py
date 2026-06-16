# -*- coding: utf-8 -*-
"""
System Monitor
==============

Monitors system health by watching health log files and automatically
restarts failed services. Implements self-healing capability.

Self-Healing Flow:
    health.log monitoring -> inactivity detection -> service restart
"""

import argparse
import logging
import os
import subprocess
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import Config, get_config, MonitorConfig

logger = logging.getLogger(__name__)


class HealthMonitor:
    """
    Health monitoring system with auto-restart capability.

    Monitors health.log files to detect:
    - Service startup events
    - Service alive heartbeats
    - Service crashes/failures

    When a service fails to send heartbeat within the check interval,
    it automatically restarts the service.
    """

    def __init__(
        self,
        log_file: str,
        check_interval: int = 6,
        restart_command: str = "python -m src.server",
    ):
        """
        Initialize health monitor.

        Args:
            log_file: Path to health log file
            check_interval: Seconds between health checks
            restart_command: Command to restart service
        """
        self.log_file = log_file
        self.check_interval = check_interval
        self.restart_command = restart_command

        # Track last alive time for each server
        # Format: {server_address: last_alive_timestamp}
        self.servers: Dict[str, Optional[float]] = defaultdict(lambda: None)

        self.last_check_time = time.time()

        # Ensure log directory exists
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        logger.info(f"Health monitor initialized (interval: {check_interval}s)")

    def _parse_log_line(self, line: str) -> tuple:
        """
        Parse a health log line.

        Expected format:
            2024-01-01 12:00:00 - 127.0.0.1:10021 - alive
            2024-01-01 12:00:00 - 127.0.0.1:10021 - started

        Args:
            line: Log line to parse

        Returns:
            Tuple of (server_address, status) or (None, None)
        """
        parts = line.strip().split(" - ")
        if len(parts) < 3:
            return None, None

        timestamp = parts[0]
        server = parts[1].strip()
        status = parts[2].strip()

        return server, status

    def _check_for_inactivity(self) -> None:
        """
        Check all monitored servers for inactivity.

        Servers that haven't sent an 'alive' within check_interval
        are considered failed and will be restarted.
        """
        current_time = time.time()

        for server, last_alive in list(self.servers.items()):
            if last_alive is None:
                continue

            time_since_alive = current_time - last_alive

            if time_since_alive > self.check_interval:
                logger.warning(
                    f"Server {server} inactive for {time_since_alive:.1f}s "
                    f"(last alive: {last_alive})"
                )
                self._restart_service(server)

    def _restart_service(self, server: str) -> bool:
        """
        Restart a failed service.

        Args:
            server: Server identifier (host:port)

        Returns:
            True if restart command succeeded
        """
        try:
            # Parse server address
            parts = server.split(":")
            if len(parts) != 2:
                logger.error(f"Invalid server format: {server}")
                return False

            host = parts[0]
            port = parts[1]

            # Build restart command
            command = f"{self.restart_command} --host {host} --port {port}"

            logger.info(f"Restarting {server} with command: {command}")

            # Execute restart
            subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            logger.info(f"Restart command issued for {server}")

            # Update last alive time to prevent immediate re-restart
            self.servers[server] = time.time()

            return True

        except subprocess.SubprocessError as e:
            logger.error(f"Failed to restart {server}: {e}")
            return False
        except Exception as e:
            logger.error(f"Restart error: {e}\n{traceback.format_exc()}")
            return False

    def monitor(self) -> None:
        """
        Main monitoring loop.

        Continuously:
        1. Watch health.log for new entries
        2. Parse entries to update server status
        3. Check for inactive servers
        4. Restart failed services
        """
        logger.info(f"Starting monitoring of {self.log_file}")

        # Ensure file exists
        if not os.path.exists(self.log_file):
            # Create empty file
            with open(self.log_file, "w") as f:
                pass
            logger.info(f"Created health log file: {self.log_file}")

        try:
            with open(self.log_file, "r") as f:
                # Seek to end of file to only read new entries
                f.seek(0, os.SEEK_END)

                while True:
                    line = f.readline()

                    if line:
                        server, status = self._parse_log_line(line)

                        if server:
                            current_time = time.time()

                            if status == "started":
                                logger.info(f"Server {server} started")
                                self.servers[server] = current_time

                            elif status == "alive":
                                self.servers[server] = current_time
                                logger.debug(f"Server {server} alive")

                            elif status == "crashed":
                                logger.warning(f"Server {server} crashed")
                                self.servers[server] = None

                    else:
                        # No new lines, wait before checking again
                        time.sleep(1)

                    # Periodic inactivity check
                    if time.time() - self.last_check_time > self.check_interval:
                        self._check_for_inactivity()
                        self.last_check_time = time.time()

        except KeyboardInterrupt:
            logger.info("Monitor stopped by user")
        except FileNotFoundError:
            logger.error(f"Health log file not found: {self.log_file}")
        except Exception as e:
            logger.error(f"Monitor error: {e}\n{traceback.format_exc()}")

    def get_server_status(self) -> Dict[str, dict]:
        """
        Get status of all monitored servers.

        Returns:
            Dictionary mapping server addresses to status info
        """
        current_time = time.time()
        status = {}

        for server, last_alive in self.servers.items():
            if last_alive is None:
                status[server] = {"state": "unknown"}
            else:
                time_since = current_time - last_alive
                is_alive = time_since <= self.check_interval

                status[server] = {
                    "state": "alive" if is_alive else "unresponsive",
                    "last_alive": last_alive,
                    "seconds_since_alive": time_since,
                }

        return status


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Monitor system health and auto-restart failed services."
    )
    parser.add_argument(
        "--log_file",
        type=str,
        default="logs/health.log",
        help="Path to health log file",
    )
    parser.add_argument(
        "--check_interval",
        type=int,
        default=6,
        help="Health check interval in seconds",
    )
    parser.add_argument(
        "--restart_command",
        type=str,
        default="python -m src.server",
        help="Command to restart failed service",
    )
    parser.add_argument(
        "--config", type=str, help="Path to config file"
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point for monitor."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    args = parse_arguments()

    # Load configuration
    config = get_config(args.config)

    # Override with command line arguments
    log_file = args.log_file or config.monitor.log_file
    check_interval = args.check_interval or config.monitor.check_interval
    restart_command = args.restart_command or config.monitor.restart_command

    # Create and start monitor
    monitor = HealthMonitor(
        log_file=log_file,
        check_interval=check_interval,
        restart_command=restart_command,
    )

    try:
        monitor.monitor()
    except KeyboardInterrupt:
        logger.info("Monitor shutting down...")


if __name__ == "__main__":
    main()