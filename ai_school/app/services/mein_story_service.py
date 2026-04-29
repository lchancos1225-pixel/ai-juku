"""
Meinストーリーサービス

生徒の学習進捗と連動する30章のキャラクター物語。
DeepSeekで事前生成し、JSONファイルにキャッシュ。
APIコスト = 生成時1回のみ。

物語設定:
  Mein（メイン）は魔法使いの卵。
  生徒が問題を解くたびに魔力が増し、新しい力を手に入れる。
  30日の旅で「賢者の証明書」を取得する冒険譚。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_STORY_CACHE_PATH = Path(__file__).resolve().parent.parent / "static" / "mein_story.json"

# 30章の物語アーク（生成時のガイド）
_STORY_ARCS = [
    (1,  5,  "旅立ち編",   "Meinが魔法学校に入学し、最初の試練に挑む"),
    (6,  10, "成長編",    "難しい呪文に挑戦し、失敗しながらも諦めない"),
    (11, 15, "仲間編",    "仲間と協力して強大な問題モンスターを倒す"),
    (16, 20, "試練編",    "過去最大の難関に立ち向かい、弱さを克服する"),
    (21, 25, "覚醒編",    "眠っていた真の力が目覚め、新たな魔法を習得する"),
    (26, 30, "証明編",    "最終試験に臨み、賢者の証明書を勝ち取る"),
]

# デフォルトストーリー（API失敗時のフォールバック）
_FALLBACK_STORIES: list[dict] = [
    {"chapter": i, "title": f"第{i}章", "body": f"Meinは今日も魔法の練習を続けた。{i}日目の努力が実を結ぼうとしていた。", "mein_power": min(i * 3, 90)}
    for i in range(1, 31)
]


def load_mein_story() -> list[dict]:
    """キャッシュファイルからストーリーを読み込む。なければフォールバックを返す。"""
    if _STORY_CACHE_PATH.exists():
        try:
            with open(_STORY_CACHE_PATH, encoding="utf-8") as f:
                stories = json.load(f)
            if isinstance(stories, list) and len(stories) >= 30:
                return stories
        except (json.JSONDecodeError, OSError):
            pass
    return _FALLBACK_STORIES


def get_chapter_for_session_count(session_count: int) -> dict:
    """
    生徒の総セッション数から対応する章を返す。
    session_count 30以降はループして最終章を繰り返す。
    """
    stories = load_mein_story()
    idx = min(max(session_count - 1, 0), 29)
    if idx < len(stories):
        return stories[idx]
    return stories[-1]


def generate_and_cache_mein_story() -> list[dict]:
    """
    DeepSeekでMeinストーリー30章を生成してキャッシュする。
    バッチ実行用。通常の学習フローでは呼ばない。
    """
    from ..services.ai_service import generate_text

    all_chapters: list[dict] = []

    for arc_start, arc_end, arc_name, arc_theme in _STORY_ARCS:
        chapter_count = arc_end - arc_start + 1
        system_prompt = """あなたは子ども向けファンタジー小説作家です。
魔法使いの卵「Mein（メイン）」の冒険ストーリーを書いてください。

必ずJSON配列で返答してください：
[
  {
    "chapter": 章番号（整数）,
    "title": "章のタイトル（10文字以内）",
    "body": "本文（80〜100文字。前向きで元気が出る内容）",
    "mein_power": Meinの魔力値（0〜100の整数）
  },
  ...
]

制約:
- 学習・勉強を頑張ることで成長する物語にする
- 毎章「今日の学び」が魔力に変わる演出を含める
- 子どもが読んでワクワクする文体
- 問題を解くことで呪文が強くなるメタファーを使う"""

        user_prompt = f"""「{arc_name}」（{arc_theme}）の章を{chapter_count}章分（第{arc_start}章〜第{arc_end}章）書いてください。
Meinの魔力は第{arc_start}章が{arc_start * 3}、第{arc_end}章が{arc_end * 3}程度で成長させてください。"""

        raw = generate_text(system_prompt, user_prompt, max_output_tokens=800)
        if not raw:
            for i in range(arc_start, arc_end + 1):
                all_chapters.append({
                    "chapter": i,
                    "title": f"第{i}章",
                    "body": _FALLBACK_STORIES[i - 1]["body"],
                    "mein_power": i * 3,
                })
            continue

        try:
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start == -1 or end == 0:
                raise ValueError("no JSON array found")
            chapters = json.loads(raw[start:end])
            for ch in chapters:
                all_chapters.append({
                    "chapter": int(ch.get("chapter", len(all_chapters) + 1)),
                    "title": str(ch.get("title", ""))[:20],
                    "body": str(ch.get("body", ""))[:200],
                    "mein_power": min(max(int(ch.get("mein_power", 50)), 0), 100),
                })
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning("Mein story generation failed for arc %s: %s", arc_name, e)
            for i in range(arc_start, arc_end + 1):
                all_chapters.append({
                    "chapter": i,
                    "title": f"第{i}章",
                    "body": _FALLBACK_STORIES[i - 1]["body"],
                    "mein_power": i * 3,
                })

    all_chapters.sort(key=lambda x: x["chapter"])

    try:
        _STORY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_STORY_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(all_chapters, f, ensure_ascii=False, indent=2)
        logger.info("Mein story cached to %s", _STORY_CACHE_PATH)
    except OSError as e:
        logger.error("Failed to cache Mein story: %s", e)

    return all_chapters
