#!/bin/bash
# =========================================
# Certificate Generation Script
# =========================================
# Generates self-signed SSL/TLS certificates
# for development and testing purposes
# =========================================

set -e

CERTS_DIR="$(dirname "$0")/../certs"
mkdir -p "$CERTS_DIR"

echo "╔════════════════════════════════════════════════════════════╗"
echo "║          Certificate Generation Script                 ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
NC='\033[0m'

print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

cd "$CERTS_DIR"

echo "[1/4] Generating RSA-2048 key pair..."
openssl genrsa -out rsa_private_key.pem 2048 2>/dev/null
openssl rsa -in rsa_private_key.pem -pubout -out rsa_public_key.pem 2>/dev/null
print_success "RSA key pair generated"

echo "[2/4] Generating Admin (Gateway) certificate..."
openssl req -new -x509 -key admin_key.pem -out admin_cert.pem -days 365 \
    -subj "/C=CA/ST=ON/L=Ottawa/O=SecureVehicle/CN=gateway" 2>/dev/null
print_success "Admin certificate generated"

echo "[3/4] Generating Vehicle A certificate..."
openssl req -new -x509 -key vehicle_a_key.pem -out vehicle_a_cert.pem -days 365 \
    -subj "/C=CA/ST=ON/L=Ottawa/O=SecureVehicle/CN=vehicle_a" 2>/dev/null
print_success "Vehicle A certificate generated"

echo "[4/4] Setting permissions..."
chmod 600 *.pem
chmod 600 *_key.pem
print_success "Permissions set"

echo ""
echo "Generated certificates:"
ls -la *.pem

echo ""
print_success "Certificate generation complete!"
echo ""
echo "Note: For production, use certificates from a trusted CA."