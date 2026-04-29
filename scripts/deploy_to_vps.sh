#!/bin/bash
# Safe VPS Deployment Script for AI-Juku
# 安全なVPSデプロイ: DB・環境変数・キャッシュを除外して転送

set -e

VPS_HOST="Administrator@210.149.87.43"
VPS_PATH="C:/Users/Administrator/ai-juku"
LOCAL_PATH="/Users/ryuzi_hirata/Desktop/ai-juku"

echo "========================================"
echo "AI-Juku Safe Deploy to VPS"
echo "========================================"
echo ""

# 1. 事前チェック - 誤ってdataディレクトリを送ろうとしていないか確認
echo "[1/4] Checking for data directory safety..."
if [ -d "$LOCAL_PATH/data" ]; then
    echo "   ✓ data/ directory exists locally (WILL NOT be transferred)"
fi

# 2. rsyncで安全に転送（__pycache__, .pyc, .env, data を除外）
echo ""
echo "[2/4] Deploying application files to VPS..."
echo "   Excluding: __pycache__, *.pyc, .env, data/, .venv/, .git/"

rsync -avz --delete \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='data/' \
    --exclude='.venv/' \
    --exclude='.git/' \
    --exclude='*.log' \
    --exclude='.DS_Store' \
    --exclude='scripts/' \
    "$LOCAL_PATH/" \
    "$VPS_HOST:$VPS_PATH/"

echo ""
echo "[3/4] Deployment complete!"

# 3. VPS上のファイル一覧を確認
echo ""
echo "[4/4] Verifying deployment on VPS..."
ssh "$VPS_HOST" "dir '$VPS_PATH\ai_school\app\main.py'" 2>/dev/null || echo "   (SSH verification skipped - please check manually)"

echo ""
echo "========================================"
echo "Next steps:"
echo "  1. SSH into VPS: ssh $VPS_HOST"
echo "  2. Navigate to: cd $VPS_PATH"
echo "  3. Run: restart_server.bat"
echo "========================================"
