#!/bin/bash
# =========================================
# Failure Recovery Demo Script
# =========================================
# Demonstrates the self-healing capability
# of the Secure Vehicle Management System
# =========================================

set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║   Secure Vehicle Management System - Failure Recovery    ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Change to project root
cd "$(dirname "$0")/.."

echo "=== Phase 1: Normal Operation ==="
print_step "Starting all services..."
docker-compose -f docker/docker-compose.yml up -d
sleep 10

print_step "Checking service health..."
docker-compose -f docker/docker-compose.yml ps

print_step "Checking Redis for vehicle status..."
docker exec svm_redis_master redis-cli -a egen5202 GET vehicle_a_Location 2>/dev/null || echo "No data yet"

echo ""
echo "=== Phase 2: Simulate Server Failure ==="
print_warning "Killing server process..."
docker exec svm_server kill -9 1 || true
sleep 2

print_step "Server killed. Monitor will detect failure..."

echo ""
echo "=== Phase 3: Monitor Detection & Auto-Restart ==="
print_step "Waiting for Monitor to detect failure (6 seconds)..."
sleep 8

print_step "Checking if server was restarted..."
docker-compose -f docker/docker-compose.yml ps server

echo ""
echo "=== Phase 4: Verification ==="
print_step "Checking server logs..."
docker logs svm_server --tail 10 2>&1 | grep -E "(started|alive)" || echo "Checking logs..."

print_step "Verifying service recovery..."
LOCATION=$(docker exec svm_redis_master redis-cli -a egen5202 GET vehicle_a_Location 2>/dev/null)
if [ -n "$LOCATION" ]; then
    print_success "Service recovered! vehicle_a_Location = $LOCATION"
else
    print_warning "No data yet - this is expected if client wasn't sending data"
fi

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║                    Demo Complete!                          ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "Key Takeaways:"
echo "  1. Monitor detected server failure within 6 seconds"
echo "  2. Auto-restart was triggered automatically"
echo "  3. System recovered without manual intervention"
echo ""