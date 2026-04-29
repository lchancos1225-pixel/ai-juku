"""
マイグレーション: unit_dependency テーブルに lecture_steps_json 列を追加
"""
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "ai_school.db"

print(f"DB path: {DB_PATH}")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("PRAGMA table_info(unit_dependency)")
existing = {row[1] for row in cur.fetchall()}
print(f"既存カラム: {existing}")

if "lecture_steps_json" not in existing:
    cur.execute("ALTER TABLE unit_dependency ADD COLUMN lecture_steps_json TEXT")
    print("✅ 追加: lecture_steps_json")
else:
    print("⏭ スキップ（既存）: lecture_steps_json")

conn.commit()
conn.close()
print("完了!")
