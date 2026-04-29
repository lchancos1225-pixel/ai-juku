# VPSデプロイ手順書

## 前提条件
- VPS IP: 210.149.87.43
- ユーザー: administrator
- パスワード: Leel1225!!!!
- プロジェクトパス: C:\Users\Administrator\ai-juku\ai-juku

## 1. 初期セットアップ（初回のみ）

### VPS側（PowerShell）
```powershell
cd C:\Users\Administrator\ai-juku\ai-juku
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install tzdata
```

## 2. コード同期（Mac→VPS）

### Mac側（ターミナル）
```bash
cd ~/Desktop/ai-juku

# 方法A: 全ファイル転送（SCP）
scp -r ~/Desktop/ai-juku/* administrator@210.149.87.43:C:/Users/Administrator/ai-juku/ai-juku/

# 方法B: 特定ファイルのみ
scp ~/Desktop/ai-juku/data/seed_problems.json administrator@210.149.87.43:C:/Users/Administrator/ai-juku/ai-juku/data/
```

## 3. VPS起動

### VPS側（PowerShell）
```powershell
cd C:\Users\Administrator\ai-juku\ai-juku
.venv\Scripts\Activate.ps1
python -m uvicorn ai_school.app.main:app --host 0.0.0.0 --port 8000
```

## 4. 一括コマンド（毎回使用）

### Mac側（ターミナル）
```bash
# コード転送 + VPS起動
cd ~/Desktop/ai-juku
scp -r ~/Desktop/ai-juku/* administrator@210.149.87.43:C:/Users/Administrator/ai-juku/ai-juku/
ssh administrator@210.149.87.43 "powershell -Command 'cd ai-juku/ai-juku; .venv\Scripts\Activate.ps1; python -m uvicorn ai_school.app.main:app --host 0.0.0.0 --port 8000'"
```

## 5. 自動化スクリプト（任意）

### Mac用 deploy.sh
```bash
#!/bin/bash
cd ~/Desktop/ai-juku
rsync -avz --exclude=".venv" --exclude="node_modules" --exclude="__pycache__" --exclude=".env" \
  ~/Desktop/ai-juku/ administrator@210.149.87.43:/cygdrive/c/Users/Administrator/ai-juku/ai-juku/
```

## 注意事項
- `.env` はVPS側の設定を維持（転送時に上書きしない）
- 二重フォルダ構造（ai-juku/ai-juku）に注意
- 仮想環境（.venv）の有効化が必須
- DeepSeek APIキーはVPS側の.envに既に設定済み

## よくあるエラーと対処

### ModuleNotFoundError: No module named 'ai_school'
→ 仮想環境が有効化されていない。`.venv\Scripts\Activate.ps1` を実行

### ZoneInfoNotFoundError: 'No time zone found with key Asia/Tokyo'
→ `pip install tzdata` を実行

### FileNotFoundError: seed_problems.json
→ MacからSCPでファイルを転送
