#!/bin/bash
# SWAGA VPN — одноклик деплой
# Использование: bash deploy.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

WORKDIR="/root/MVP-SWAGA-NEW"
VENV="$WORKDIR/venv/bin/python3"
BRANCH="claude/check-status-bH5rv"
BOT_SERVICE="swaga-bot"
SUPPORT_SERVICE="swaga-support"

step() { echo -e "\n${BLUE}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
fail() { echo -e "${RED}✗ $1${NC}"; exit 1; }

echo "=================================================="
echo "   SWAGA VPN — Deploy"
echo "=================================================="

# ── 0. Проверки ────────────────────────────────────────
[ "$EUID" -eq 0 ] || fail "Запускай от root"
[ -d "$WORKDIR" ]  || fail "Директория не найдена: $WORKDIR"
[ -f "$VENV" ]     || fail "venv не найден: $VENV"
cd "$WORKDIR"

# ── 1. Git pull ────────────────────────────────────────
step "Обновление кода ($BRANCH)"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull origin "$BRANCH"
echo "Коммит: $(git log -1 --oneline)"
ok "Код обновлён"

# ── 2. Зависимости ────────────────────────────────────
step "Зависимости"
"$VENV" -m pip install -r requirements.txt -q
ok "Зависимости установлены"

# ── 3. Перезапуск ботов ───────────────────────────────
step "Перезапуск сервисов"

# Останавливаем старые nohup-процессы если есть
pkill -f "python.*bot.py" 2>/dev/null || true
pkill -f "python.*main.py" 2>/dev/null || true
sleep 1

if systemctl is-enabled "$BOT_SERVICE" &>/dev/null; then
    systemctl restart "$BOT_SERVICE"
    sleep 3
    if systemctl is-active "$BOT_SERVICE" &>/dev/null; then
        ok "$BOT_SERVICE запущен"
    else
        warn "$BOT_SERVICE не запустился — смотри: journalctl -u $BOT_SERVICE -n 30"
    fi
else
    warn "$BOT_SERVICE не зарегистрирован в systemd — запускаю напрямую"
    nohup "$VENV" "$WORKDIR/bot.py" >> "$WORKDIR/bot.log" 2>&1 &
    sleep 3
    pgrep -f "python.*bot.py" &>/dev/null && ok "bot.py запущен (PID: $(pgrep -f 'python.*bot.py'))" \
        || warn "Бот не запустился — смотри: tail -30 $WORKDIR/bot.log"
fi

if systemctl is-enabled "$SUPPORT_SERVICE" &>/dev/null; then
    systemctl restart "$SUPPORT_SERVICE"
    sleep 2
    systemctl is-active "$SUPPORT_SERVICE" &>/dev/null && ok "$SUPPORT_SERVICE запущен" \
        || warn "$SUPPORT_SERVICE не запустился"
fi

# ── 4. Синхронизация клиентов на все серверы ──────────
step "Синхронизация клиентов на серверы"
echo "Добавляем/обновляем всех активных пользователей на всех включённых серверах..."
"$VENV" "$WORKDIR/sync_clients_to_servers.py" && ok "Синхронизация завершена" \
    || warn "Синхронизация завершилась с ошибками — проверь вывод выше"

# ── 5. Итог ───────────────────────────────────────────
echo ""
echo "=================================================="
echo -e "${GREEN}   Деплой завершён!${NC}"
echo "=================================================="
echo ""
echo "Активные серверы:"
"$VENV" -c "
import json
d = json.load(open('servers.json'))
for s in d['servers']:
    state = '✅' if s['enabled'] else '⏸'
    print(f'  {state} {s[\"name\"]:25} {s[\"host\"]}:{s[\"vpn_port\"]}')
"
echo ""
echo "Полезные команды:"
echo "  Логи бота:     journalctl -u $BOT_SERVICE -f"
echo "  Логи nohup:    tail -f $WORKDIR/bot.log"
echo "  Статус:        systemctl status $BOT_SERVICE $SUPPORT_SERVICE"
echo ""
