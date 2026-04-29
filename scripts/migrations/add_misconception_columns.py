"""
マイグレーション: learning_log テーブルに誤概念フィンガープリント列を追加
対象: misconception_tag, misconception_detail
"""
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "ai_school.db"

print(f"DB path: {DB_PATH}")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("PRAGMA table_info(learning_log)")
existing = {row[1] for row in cur.fetchall()}
print(f"既存カラム: {existing}")

migrations = [
    ("misconception_tag",    "ALTER TABLE learning_log ADD COLUMN misconception_tag VARCHAR(120)"),
    ("misconception_detail", "ALTER TABLE learning_log ADD COLUMN misconception_detail TEXT"),
]

for col, sql in migrations:
    if col not in existing:
        cur.execute(sql)
        print(f"✅ 追加: {col}")
    else:
        print(f"⏭ スキップ（既存）: {col}")

conn.commit()
conn.close()
print("完了!")
