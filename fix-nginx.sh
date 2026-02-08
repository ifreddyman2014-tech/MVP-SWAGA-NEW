#!/bin/bash
# Fix NGINX configuration for SWAGA VPN
# Resolves ERR_CONNECTION_CLOSED for sub.swaga-vpn.ru
#
# Usage: bash fix-nginx.sh

set -e

echo "=== Fixing NGINX for SWAGA VPN ==="

# 1. Remove any conflicting configs for sub.swaga-vpn.ru
echo "[1/6] Removing conflicting NGINX configs..."
rm -f /etc/nginx/sites-enabled/sub.swaga-vpn.ru
rm -f /etc/nginx/sites-available/sub.swaga-vpn.ru
echo "  Removed old sub.swaga-vpn.ru configs (if any)"

# 2. Check for any OTHER configs referencing sub.swaga-vpn.ru
echo "[2/6] Checking for remaining conflicts..."
CONFLICTS=$(grep -rl "sub.swaga-vpn.ru" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | grep -v swaga-vpn.conf || true)
if [ -n "$CONFLICTS" ]; then
    echo "  WARNING: Found additional configs with sub.swaga-vpn.ru:"
    echo "  $CONFLICTS"
    echo "  These may need manual removal."
else
    echo "  No conflicts found"
fi

# 3. Copy updated config
echo "[3/6] Deploying updated NGINX config..."
cp /root/MVP-SWAGA-NEW/SWAGA-NEW/nginx-swaga-vpn.conf /etc/nginx/sites-available/swaga-vpn.conf 2>/dev/null \
  || cp /root/MVP-SWAGA-NEW/nginx-swaga-vpn.conf /etc/nginx/sites-available/swaga-vpn.conf 2>/dev/null \
  || echo "  WARNING: Could not copy config. Copy nginx-swaga-vpn.conf to /etc/nginx/sites-available/swaga-vpn.conf manually."

# 4. Ensure symlink exists
echo "[4/6] Ensuring sites-enabled symlink..."
ln -sf /etc/nginx/sites-available/swaga-vpn.conf /etc/nginx/sites-enabled/swaga-vpn.conf
echo "  Symlink OK"

# 5. Verify SSL certs exist
echo "[5/6] Checking SSL certificates..."
if [ -f /etc/letsencrypt/live/sub.swaga-vpn.ru/fullchain.pem ]; then
    echo "  sub.swaga-vpn.ru cert: OK"
else
    echo "  WARNING: cert not found at /etc/letsencrypt/live/sub.swaga-vpn.ru/"
    echo "  Run: certbot certonly --nginx -d sub.swaga-vpn.ru"
fi
if [ -f /etc/letsencrypt/live/swaga-vpn.ru/fullchain.pem ]; then
    echo "  swaga-vpn.ru cert: OK"
else
    echo "  WARNING: cert not found at /etc/letsencrypt/live/swaga-vpn.ru/"
fi

# 6. Test and reload NGINX
echo "[6/6] Testing and reloading NGINX..."
nginx -t
systemctl reload nginx
echo ""
echo "=== Done! Test: curl -sk https://sub.swaga-vpn.ru/connect/test ==="
