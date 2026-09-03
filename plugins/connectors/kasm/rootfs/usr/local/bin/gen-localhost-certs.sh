#!/bin/sh
# gen-localhost-certs: bake a stable development CA + localhost server cert.
#
# KasmVNC serves the desktop over HTTPS using the certificate it finds at the
# Debian snakeoil paths. The distro-generated snakeoil cert is anonymous, so
# browsers reject it on both trust AND hostname (it has no Subject Alternative
# Name for localhost). This script bakes a long-lived CA + server certificate
# into the image at build time:
#   - the server cert is valid for localhost / 127.0.0.1 (no hostname error),
#   - the CA can be imported once into a browser / OS trust store to also
#     silence the self-signed trust warning (see docs/architecture.md).
# The certs are baked (NOT regenerated per container) so a single CA import
# stays valid across container re-creations.
set -e

CA_DIR="/etc/ssl/local"
CA_KEY="$CA_DIR/gravity-ca.key"
CA_CERT="$CA_DIR/gravity-ca.pem"
SERVER_KEY="/etc/ssl/private/ssl-cert-snakeoil.key"
SERVER_PEM="/etc/ssl/certs/ssl-cert-snakeoil.pem"

mkdir -p "$CA_DIR"

# Development CA. Reuse an existing one so repeated builds keep the same
# CA identity (an already-imported CA stays valid across image rebuilds).
if [ ! -f "$CA_CERT" ]; then
    openssl genrsa -out "$CA_KEY" 2048
    chmod 600 "$CA_KEY"
    openssl req -x509 -new -key "$CA_KEY" -sha256 -days 3650 \
        -subj "/CN=Sanity Gravity Development CA" \
        -addext "basicConstraints=critical,CA:TRUE" \
        -addext "keyUsage=critical,keyCertSign,cRLSign" \
        -out "$CA_CERT"
fi

# Server key + certificate signed by the CA, valid for localhost access.
EXT_FILE="$(mktemp)"
trap 'rm -f "$EXT_FILE"' EXIT
cat > "$EXT_FILE" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:localhost,IP:127.0.0.1
EOF

openssl genrsa -out "$SERVER_KEY" 2048
chmod 600 "$SERVER_KEY"
openssl req -new -key "$SERVER_KEY" -subj "/CN=localhost" -out "$CA_DIR/server.csr"
openssl x509 -req -in "$CA_DIR/server.csr" \
    -CA "$CA_CERT" -CAkey "$CA_KEY" -CAcreateserial \
    -days 3650 -sha256 -extfile "$EXT_FILE" \
    -out "$SERVER_PEM"

# Present the chain (leaf + CA) so clients that trust the CA validate the leaf.
cat "$CA_CERT" >> "$SERVER_PEM"

# vncserver runs as the developer user, a member of the ssl-cert group.
chmod 640 "$SERVER_KEY"
chown root:ssl-cert "$SERVER_KEY" 2>/dev/null || true
chmod 644 "$SERVER_PEM"
rm -f "$CA_DIR/server.csr"
