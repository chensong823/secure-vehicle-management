#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Security Integrity Demo
========================

Demonstrates the SHA-256 message integrity verification.
Shows how the system detects and blocks tampered messages.
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.crypto import sha256_hash
from src.utils.parsing import wrap_data, create_signed_message, parse_data


def print_header(title: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60 + "\n")


def print_step(msg: str) -> None:
    """Print a step message."""
    print(f"[STEP] {msg}")


def print_success(msg: str) -> None:
    """Print a success message."""
    print(f"[SUCCESS] {msg}")


def print_blocked(msg: str) -> None:
    """Print a blocked message."""
    print(f"[BLOCKED] {msg}")


def demo_message_integrity() -> None:
    """
    Demonstrate how integrity verification detects tampering.
    """
    print_header("Message Integrity Verification Demo")

    # Simulate normal message
    print_step("Simulating normal message exchange...")
    node_name = "vehicle_a"
    action = "LockStatus"
    original_message = "unlocked"

    # Create signed message
    msg_bytes, hash_code = create_signed_message(node_name, action, original_message)

    print(f"  Node: {node_name}")
    print(f"  Action: {action}")
    print(f"  Message: '{original_message}'")
    print(f"  SHA-256 Hash: {hash_code[:32]}...")
    print_success("Original message signed successfully\n")

    # Verify original
    print_step("Verifying original message...")
    parsed = parse_data(msg_bytes.decode("utf-8"), verify_hash=True)
    if parsed:
        print_success("Original message verified!\n")
    else:
        print_blocked("Original message verification failed!\n")

    # Simulate man-in-the-middle attack
    print_header("Simulating Man-in-the-Middle Attack")

    print_step("Attacker intercepts and tampers with message...")
    tampered_message = "locked"  # Changed from "unlocked" to "locked"

    print(f"  Original: '{original_message}'")
    print(f"  Tampered: '{tampered_message}'")

    # Attacker uses original hash (doesn't know the new hash)
    tampered_msg_bytes = wrap_data(
        node_name, action, tampered_message, hash_code
    )

    print(f"  Attacker uses original hash: {hash_code[:32]}...")
    print_blocked("Attacker sends tampered message with original hash\n")

    # Receiver verification
    print_step("Receiver verifies tampered message...")
    parsed = parse_data(tampered_msg_bytes.decode("utf-8"), verify_hash=True)

    if not parsed:
        print_blocked("Verification FAILED - Message integrity compromised!")
        print("  The system detected that the message was tampered.")
        print("  This prevents the attacker from modifying commands remotely.")
    else:
        print_success("Unexpected: verification passed")

    print("\n" + "=" * 60)
    print("  KEY TAKEAWAY:")
    print("  SHA-256 hash verification prevents data tampering")
    print("  Any modification to message content is detected")
    print("=" * 60 + "\n")


def demo_hash_collision_resistance() -> None:
    """
    Demonstrate SHA-256 collision resistance.
    """
    print_header("Hash Collision Resistance Demo")

    msg1 = "lock"
    msg2 = "l0ck"  # Visually similar but different

    hash1 = sha256_hash(msg1)
    hash2 = sha256_hash(msg2)

    print(f"  Message 1: '{msg1}' -> {hash1[:32]}...")
    print(f"  Message 2: '{msg2}' -> {hash2[:32]}...")

    if hash1 == hash2:
        print_blocked("COLLISION DETECTED!")
    else:
        print_success("Different messages produce different hashes")

    # Show avalanche effect
    print("\n[STEP] Demonstrating Avalanche Effect...")
    msg3 = "lock"
    msg4 = "locka"  # One character difference

    hash3 = sha256_hash(msg3)
    hash4 = sha256_hash(msg4)

    changed_bits = sum(
        c1 != c2 for c1, c2 in zip(hash3.replace("-", ""), hash4.replace("-", ""))
    )

    print(f"  '{msg3}' vs '{msg4}'")
    print(f"  Hash 3: {hash3[:32]}...")
    print(f"  Hash 4: {hash4[:32]}...")
    print(f"  Bits changed: ~{changed_bits * 4}% of hash bits")
    print_success("Even a single bit change drastically changes the hash\n")


def main() -> None:
    """Main entry point."""
    print("\n" + "╔" + "═" * 58 + "╗")
    print("║" + " " * 10 + "SECURITY INTEGRITY DEMONSTRATION" + " " * 10 + "║")
    print("╚" + "═" * 58 + "╝\n")

    demo_message_integrity()
    demo_hash_collision_resistance()

    print_header("Demo Complete!")
    print("This demonstrates why SHA-256 integrity verification")
    print("is critical for secure vehicle control systems.")
    print("")


if __name__ == "__main__":
    main()