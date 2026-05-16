"""DeepSeek API を使ったオンデマンド激ムズ問題生成サービス。"""
import json
import logging
import os
import time
from datetime import datetime, date

import httpx

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..models import Problem

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

CHALLENGE_CATEGORIES = {
    "speed": "計算スピード",
    "proof": "証明・論述",
    "applied": "応用・実生活",
    "puzzle": "数学パズル",
    "olympiad": "数学オリンピック風",
}

DAILY_GENERATE_LIMIT = int(os.getenv("DEEPSEEK_DAILY_LIMIT", "10"))

_daily_count: dict[str, int] = {}


def _today_key() -> str:
    return date.today().isoformat()


def _over_daily_limit() -> bool:
    today = _today_key()
    return _daily_count.get(today, 0) >= DAILY_GENERATE_LIMIT


def _increment_daily():
    today = _today_key()
    _daily_count[today] = _daily_count.get(today, 0) + 1


def _build_prompt(category: str, unit_label: str) -> str:
    cat_label = CHALLENGE_CATEGORIES.get(category, category)
    return (
        f"あなたは中学数学の天才問題作成者です。\n"
        f"カテゴリ「{cat_label}」で、単元「{unit_label}」に関連する激ムズ問題を1問作成してください。\n"
        f"問題は中学生が本気で考えても10分以上かかるレベルにしてください。\n"
        f"以下のJSON形式のみで返してください（他のテキストは不要）:\n"
        f'{{"question": "問題文", "answer": "正解（数値または式）", "explanation": "解説"}}'
    )


def generate_challenge_problem(
    db: Session,
    category: str,
    unit_id: str | None = None,
    unit_label: str = "数学",
) -> Problem | None:
    """DeepSeek API で激ムズ問題を1問生成して DB に保存し返す。失敗時は None。"""
    if not DEEPSEEK_API_KEY:
        logger.warning("DEEPSEEK_API_KEY が設定されていません")
        return None

    if _over_daily_limit():
        logger.warning("DeepSeek API の日次上限に達しています")
        return None

    prompt = _build_prompt(category, unit_label)

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                DEEPSEEK_API_URL,
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.9,
                    "max_tokens": 512,
                },
            )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        data = json.loads(content)
    except Exception as e:
        logger.error("DeepSeek API エラー: %s", e)
        return None

    question = str(data.get("question", "")).strip()
    answer = str(data.get("answer", "")).strip()
    explanation = str(data.get("explanation", "")).strip()

    if not question or not answer:
        logger.error("DeepSeek API からの応答が不正: %s", data)
        return None

    _increment_daily()

    now = datetime.utcnow().isoformat()
    p = Problem(
        question_text=question,
        correct_answer=answer,
        explanation=explanation or "解説なし",
        difficulty=5,
        subject="math",
        unit=unit_id or "challenge",
        full_unit_id=unit_id or "challenge",
        problem_type="practice",
        status="approved",
        answer_type="text",
        created_at=now,
    )
    setattr(p, "challenge_category", category)
    db.add(p)
    db.commit()
    db.refresh(p)
    logger.info("DeepSeek 激ムズ問題生成完了: problem_id=%s", p.problem_id)
    return p


def get_or_generate_challenge_problem(
    db: Session,
    category: str | None = None,
    unit_id: str | None = None,
    unit_label: str = "数学",
) -> Problem | None:
    """DBに問題があれば返す。なければ DeepSeek で生成して返す。"""
    stmt = (
        select(Problem)
        .where(
            Problem.difficulty == 5,
            Problem.problem_type == "practice",
            Problem.status == "approved",
        )
    )
    if category:
        from sqlalchemy import text as _t
        ids_row = db.execute(
            _t(
                "SELECT problem_id FROM problems "
                "WHERE difficulty=5 AND problem_type='practice' AND status='approved' "
                "AND challenge_category=:cat ORDER BY RANDOM() LIMIT 1"
            ),
            {"cat": category},
        ).first()
        if ids_row:
            return db.get(Problem, ids_row[0])
    else:
        stmt = stmt.order_by(func.random()).limit(1)
        p = db.scalar(stmt)
        if p:
            return p

    return generate_challenge_problem(db, category or "puzzle", unit_id, unit_label)
