# SWAGA VPN Deployment Guide

Complete step-by-step deployment instructions for production.

---

## 🚀 БЫСТРОЕ ОБНОВЛЕНИЕ (для существующего сервера)

Если у вас уже запущен бот и нужно только обновить код с новыми зависимостями:

### На production сервере выполните:

```bash
cd /root/MVP-SWAGA-NEW

# 1. Остановить бота (если запущен)
pkill -f "python.*main.py" || pkill -f "python.*bot.py"
# или для Docker:
# docker-compose stop vpn-bot

# 2. Получить обновления
git fetch origin
git checkout claude/check-status-bH5rv
git pull origin claude/check-status-bH5rv

# 3. Установить новые зависимости
pip3 install -r requirements.txt

# 4. Синхронизировать серверы
python3 sync_servers.py --dry-run  # предпросмотр
python3 sync_servers.py            # применить
python3 sync_servers.py --list     # проверить

# 5. Запустить бота
# Для прямого запуска:
nohup python3 main.py > bot.log 2>&1 &

# Для Docker:
# docker-compose up -d

# 6. Проверить логи
tail -f bot.log
# или: docker-compose logs -f vpn-bot
```

### Что изменилось:
- ✅ Добавлены: SQLAlchemy, asyncpg, pydantic
- ✅ Исправлена валидация config для placeholder значений
- ✅ Теперь работает `sync_servers.py`

---

## Pre-Deployment Checklist

### 1. Server Requirements
- [ ] VPS with Docker & Docker Compose installed
- [ ] Minimum 2GB RAM, 2 CPU cores
- [ ] 20GB disk space
- [ ] Public IP address
- [ ] Domain name (for webhook)

### 2. External Services
- [ ] 3X-UI panel (MHSanaei fork) installed and accessible
- [ ] YooKassa account created and verified
- [ ] Telegram bot created via @BotFather
- [ ] SSL certificate for webhook domain (Let's Encrypt recommended)

## Step 1: Clone Repository

```bash
cd /opt
git clone <your-repo-url> swaga-vpn
cd swaga-vpn
```

## Step 2: Configure Environment

```bash
cp .env.example .env
nano .env
```

### Required Configuration

```env
# Database
DATABASE_URL=postgresql+asyncpg://swaga_user:CHANGE_THIS_PASSWORD@postgres:5432/swaga
POSTGRES_USER=swaga_user
POSTGRES_PASSWORD=CHANGE_THIS_PASSWORD
POSTGRES_DB=swaga

# Telegram Bot
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
ADMIN_CHAT_ID=123456789
SUPPORT_BOT_USERNAME=YourSupportBot

# 3X-UI Panel
XUI_BASE=https://panel.yourdomain.com
XUI_USERNAME=admin
XUI_PASSWORD=your_secure_password
XUI_INBOUND_ID=1

# VPN Configuration
VPN_FLOW=xtls-rprx-vision

# YooKassa
YOOKASSA_SHOP_ID=123456
YOOKASSA_SECRET=live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
YOOKASSA_WEBHOOK_SECRET=random_32_char_string_for_validation

# Webhook Server
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8000
WEBHOOK_BASE_URL=https://webhook.yourdomain.com

# Pricing (in RUB)
PRICE_M1=130
PRICE_M3=350
PRICE_M12=800

# Trial
TRIAL_DAYS=7

# Logging
LOG_LEVEL=INFO
```

### Generate Secure Passwords

```bash
# PostgreSQL password
openssl rand -base64 32

# Webhook secret
openssl rand -hex 32
```

## Step 3: Setup Nginx (for webhook)

Create `/etc/nginx/sites-available/swaga-webhook`:

```nginx
server {
    listen 80;
    server_name webhook.yourdomain.com;

    location / {
        return 301 https://$server_name$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name webhook.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/webhook.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/webhook.yourdomain.com/privkey.pem;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable site:
```bash
ln -s /etc/nginx/sites-available/swaga-webhook /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx
```

## Step 4: Setup SSL Certificate

```bash
# Install certbot
apt-get update
apt-get install -y certbot python3-certbot-nginx

# Get certificate
certbot --nginx -d webhook.yourdomain.com

# Auto-renewal
certbot renew --dry-run
```

## Step 5: Prepare Server Database

### Option A: Fresh Installation

```bash
# Start only PostgreSQL first
docker-compose up -d postgres

# Wait for PostgreSQL to be ready
docker-compose logs -f postgres
# Press Ctrl+C when you see "database system is ready to accept connections"

# Add server configuration
docker-compose exec postgres psql -U swaga_user -d swaga
```

```sql
-- Insert your VPN server details
INSERT INTO servers (
    name, is_active, api_url, username, password, inbound_id,
    host, port, public_key, short_ids, domain,
    security, network_type, flow, fingerprint, spider_x,
    xhttp_host, xhttp_path, xhttp_mode,
    created_at, updated_at
) VALUES (
    'Main Server',          -- name
    true,                   -- is_active
    'https://panel.yourdomain.com',  -- api_url
    'admin',                -- username
    'your_panel_password',  -- password
    1,                      -- inbound_id
    'vpn.yourdomain.com',   -- host
    443,                    -- port
    'YOUR_REALITY_PUBLIC_KEY',  -- public_key (from 3X-UI)
    'SHORT_ID_1,SHORT_ID_2',    -- short_ids (from 3X-UI)
    'www.example.com',      -- domain (SNI)
    'reality',              -- security
    'xhttp',                -- network_type
    'xtls-rprx-vision',     -- flow
    'chrome',               -- fingerprint
    '/',                    -- spider_x
    'yandex.ru',            -- xhttp_host
    '/adv',                 -- xhttp_path
    'packet-up',            -- xhttp_mode
    NOW(),
    NOW()
);

-- Verify
SELECT id, name, host, port FROM servers;
```

Press `Ctrl+D` to exit psql.

### Option B: Migrate from Legacy

```bash
# Copy old bot.db to migration directory
cp /path/to/old/bot.db ./

# Run migration
docker-compose run --rm bot python migrate_legacy.py \
    --sqlite-path /app/bot.db \
    --server-name "Main Server"

# Then manually update server configuration in PostgreSQL
```

## Step 6: Start Services

```bash
# Create logs directory
mkdir -p logs

# Start all services
docker-compose up -d

# Check logs
docker-compose logs -f bot
```

Expected output:
```
swaga_bot | [2024-01-25 10:00:00] INFO: Starting SWAGA VPN Bot...
swaga_bot | [2024-01-25 10:00:01] INFO: Initializing database...
swaga_bot | [2024-01-25 10:00:02] INFO: Database initialized successfully
swaga_bot | [2024-01-25 10:00:03] INFO: Bot commands set successfully
swaga_bot | [2024-01-25 10:00:04] INFO: Starting bot polling...
swaga_bot | [2024-01-25 10:00:05] INFO: SWAGA VPN Bot started successfully
```

## Step 7: Configure YooKassa Webhook

1. Login to YooKassa dashboard
2. Go to Settings → Notifications
3. Set webhook URL: `https://webhook.yourdomain.com/webhook/yookassa`
4. Select events:
   - ✅ payment.succeeded
   - ✅ payment.canceled
   - ✅ refund.succeeded
5. Save settings

### Test Webhook

```bash
# Send test webhook
curl -X POST https://webhook.yourdomain.com/webhook/yookassa \
  -H "Content-Type: application/json" \
  -d '{
    "event": "payment.succeeded",
    "object": {
      "id": "test-payment-id",
      "status": "succeeded"
    }
  }'
```

Check logs:
```bash
docker-compose logs bot | grep -i webhook
```

## Step 8: Test Bot

1. Open Telegram and find your bot
2. Send `/start` command
3. Try activating 7-day trial
4. Verify key generation
5. Test payment flow (use YooKassa test mode)

## Step 9: Monitoring

### Check Service Status
```bash
docker-compose ps
```

### View Logs
```bash
# All logs
docker-compose logs -f

# Bot only
docker-compose logs -f bot

# PostgreSQL only
docker-compose logs -f postgres

# Last 100 lines
docker-compose logs --tail=100 bot
```

### Database Queries
```bash
# Connect to database
docker-compose exec postgres psql -U swaga_user -d swaga

# Check users
SELECT telegram_id, username, trial_used, created_at FROM users ORDER BY id DESC LIMIT 10;

# Check active subscriptions
SELECT s.id, u.telegram_id, s.plan_type, s.expiry_date, s.is_active
FROM subscriptions s
JOIN users u ON s.user_id = u.id
WHERE s.is_active = true
ORDER BY s.expiry_date DESC;

# Check payments
SELECT payment_id, telegram_id, plan_type, amount, status, created_at
FROM payments
ORDER BY created_at DESC
LIMIT 20;
```

## Step 10: Backup Strategy

### Database Backup
```bash
# Create backup script
cat > /opt/swaga-vpn/backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/opt/swaga-vpn/backups"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

docker-compose exec -T postgres pg_dump -U swaga_user swaga | gzip > "$BACKUP_DIR/swaga_$DATE.sql.gz"

# Keep only last 30 days
find $BACKUP_DIR -name "swaga_*.sql.gz" -mtime +30 -delete

echo "Backup completed: swaga_$DATE.sql.gz"
EOF

chmod +x /opt/swaga-vpn/backup.sh

# Add to crontab (daily at 3 AM)
(crontab -l 2>/dev/null; echo "0 3 * * * /opt/swaga-vpn/backup.sh") | crontab -
```

### Restore from Backup
```bash
# Stop bot
docker-compose stop bot

# Restore
gunzip < backups/swaga_20240125_030000.sql.gz | docker-compose exec -T postgres psql -U swaga_user swaga

# Start bot
docker-compose start bot
```

## Troubleshooting

### Bot not starting
```bash
# Check environment
docker-compose config

# Check logs
docker-compose logs bot

# Restart
docker-compose restart bot
```

### Database connection errors
```bash
# Check PostgreSQL status
docker-compose ps postgres

# Check credentials
docker-compose exec postgres psql -U swaga_user -d swaga -c "SELECT 1;"

# Recreate database (⚠️ DANGER: loses all data)
docker-compose down -v
docker-compose up -d
```

### 3X-UI connection issues
```bash
# Test connection
docker-compose exec bot python << EOF
import asyncio
from src.services.xui import ThreeXUIClient
from src.config import settings

async def test():
    client = ThreeXUIClient(
        base_url=settings.xui_base,
        username=settings.xui_username,
        password=settings.xui_password,
    )
    async with client.session():
        clients = await client.list_clients()
        print(f"✅ Connected! Found {len(clients)} clients")

asyncio.run(test())
EOF
```

### Webhook not receiving events
1. Check firewall: `ufw status`
2. Test webhook endpoint: `curl https://webhook.yourdomain.com/health`
3. Check Nginx logs: `tail -f /var/log/nginx/error.log`
4. Verify YooKassa settings

## Maintenance

### Update Application
```bash
cd /opt/swaga-vpn
git pull
docker-compose build
docker-compose up -d
```

### View Resource Usage
```bash
docker stats swaga_bot swaga_postgres
```

### Clean Old Logs
```bash
# Add to crontab (weekly cleanup)
0 0 * * 0 find /opt/swaga-vpn/logs -name "*.log" -mtime +7 -delete
```

## Security Hardening

1. **Firewall**:
   ```bash
   ufw allow 22/tcp    # SSH
   ufw allow 80/tcp    # HTTP
   ufw allow 443/tcp   # HTTPS
   ufw enable
   ```

2. **Fail2ban**:
   ```bash
   apt-get install fail2ban
   systemctl enable fail2ban
   systemctl start fail2ban
   ```

3. **Regular Updates**:
   ```bash
   apt-get update && apt-get upgrade -y
   ```

4. **Change Default Passwords**:
   - PostgreSQL password
   - 3X-UI admin password
   - Server SSH keys

## Production Checklist

Before going live:

- [ ] All environment variables configured
- [ ] Database backups automated
- [ ] SSL certificate installed and auto-renewal configured
- [ ] YooKassa webhook tested
- [ ] Trial activation tested
- [ ] Payment flow tested
- [ ] Server configuration added to database
- [ ] Monitoring setup (logs, alerts)
- [ ] Bot commands tested
- [ ] Deep links working
- [ ] Firewall configured
- [ ] Documentation reviewed

---

**Deployment completed!** Your SWAGA VPN bot is now production-ready. 🚀
