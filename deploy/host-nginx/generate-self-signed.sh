#!/usr/bin/env bash
# Generate a self-signed certificate for queryforge.local demo TLS.
set -euo pipefail

DOMAIN="${1:-queryforge.local}"
IP="${2:-106.12.4.23}"
OUT_DIR="${3:-/etc/nginx/ssl}"

mkdir -p "${OUT_DIR}"

openssl req -x509 -nodes -newkey rsa:2048 \
  -days 825 \
  -keyout "${OUT_DIR}/${DOMAIN}.key" \
  -out "${OUT_DIR}/${DOMAIN}.crt" \
  -subj "/CN=${DOMAIN}/O=QueryForge Demo/C=CN" \
  -addext "subjectAltName=DNS:${DOMAIN},IP:${IP}"

chmod 600 "${OUT_DIR}/${DOMAIN}.key"
chmod 644 "${OUT_DIR}/${DOMAIN}.crt"

echo "Created:"
echo "  ${OUT_DIR}/${DOMAIN}.crt"
echo "  ${OUT_DIR}/${DOMAIN}.key"
