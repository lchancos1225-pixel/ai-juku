"""
マイグレーション: student_stateテーブルに不足カラムを追加
対象: login_streak, last_activity_date, total_xp
"""
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "ai_school.db"

print(f"DB path: {DB_PATH}")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("PRAGMA table_info(student_state)")
existing = {row[1] for row in cur.fetchall()}
print(f"既存カラム: {existing}")

migrations = [
    ("login_streak",       "ALTER TABLE student_state ADD COLUMN login_streak INTEGER NOT NULL DEFAULT 0"),
    ("last_activity_date", "ALTER TABLE student_state ADD COLUMN last_activity_date VARCHAR(10)"),
    ("total_xp",           "ALTER TABLE student_state ADD COLUMN total_xp INTEGER NOT NULL DEFAULT 0"),
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
