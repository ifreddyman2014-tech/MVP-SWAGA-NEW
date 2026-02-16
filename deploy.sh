#!/bin/bash
set -e

echo "=================================================="
echo "SWAGA VPN - Quick Deployment Script"
echo "=================================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Error: Please run as root${NC}"
    exit 1
fi

echo -e "${YELLOW}Step 1: Stopping existing bot...${NC}"
pkill -f "python.*main.py" || true
pkill -f "python.*bot.py" || true
docker-compose stop vpn-bot 2>/dev/null || true
echo -e "${GREEN}✓ Bot stopped${NC}"
echo ""

echo -e "${YELLOW}Step 2: Updating code...${NC}"
git fetch origin
git checkout claude/check-status-bH5rv
git pull origin claude/check-status-bH5rv
echo -e "${GREEN}✓ Code updated${NC}"
echo ""

echo -e "${YELLOW}Step 3: Installing dependencies...${NC}"
pip3 install -r requirements.txt --quiet
echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

echo -e "${YELLOW}Step 4: Syncing servers...${NC}"
python3 sync_servers.py --dry-run
echo ""
read -p "Apply server sync? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    python3 sync_servers.py
    python3 sync_servers.py --list
    echo -e "${GREEN}✓ Servers synced${NC}"
else
    echo -e "${YELLOW}Skipped server sync${NC}"
fi
echo ""

echo -e "${YELLOW}Step 5: Starting bot...${NC}"
read -p "Start bot with Docker (d) or direct (p)? " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Dd]$ ]]; then
    docker-compose up -d
    echo -e "${GREEN}✓ Bot started in Docker${NC}"
    echo ""
    echo "View logs with: docker-compose logs -f vpn-bot"
else
    nohup python3 main.py > bot.log 2>&1 &
    echo -e "${GREEN}✓ Bot started${NC}"
    echo ""
    echo "View logs with: tail -f bot.log"
fi

echo ""
echo "=================================================="
echo -e "${GREEN}Deployment completed!${NC}"
echo "=================================================="
echo ""
echo "Quick checks:"
echo "  - Logs: tail -f bot.log"
echo "  - Processes: ps aux | grep python"
echo "  - Servers: python3 sync_servers.py --list"
echo ""
