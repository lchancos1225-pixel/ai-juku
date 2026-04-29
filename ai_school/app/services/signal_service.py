from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..models import LearningLog, Problem


def classify_time_signal(elapsed_sec: int) -> str:
    if elapsed_sec >= 45:
        return "long"
    if elapsed_sec >= 20:
        return "normal"
    return "short"


def extract_recent_signals(db: Session, student_id: int, limit: int = 8) -> list[dict]:
    stmt = (
        select(LearningLog, Problem)
        .join(Problem, LearningLog.problem_id == Problem.problem_id)
        .where(LearningLog.student_id == student_id, Problem.problem_type == "practice")
        .order_by(desc(LearningLog.created_at))
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    signals: list[dict] = []
    correct_streak = 0
    wrong_streak = 0

    for log, problem in rows:
        if log.is_correct:
            correct_streak += 1
            wrong_streak = 0
        else:
            wrong_streak += 1
            correct_streak = 0
        signals.append(
            {
                "problem_id": log.problem_id,
                "unit_id": problem.unit,
                "difficulty": problem.difficulty,
                "correctness_signal": "correct" if log.is_correct else "wrong",
                "hint_signal": log.hint_used,
                "error_pattern": log.error_pattern,
                "time_signal": classify_time_signal(log.elapsed_sec),
                "elapsed_sec": log.elapsed_sec,
                "streak_signal": {
                    "correct_streak": correct_streak,
                    "wrong_streak": wrong_streak,
                },
                "route_signal": log.route_decision or "reinforce_current_unit",
                "created_at": log.created_at.isoformat(),
            }
        )
    return signals


def summarize_recent_signals(signals: list[dict]) -> dict:
    if not signals:
        return {
            "recent_correct_rate": 0.0,
            "recent_hint_avg": 0.0,
            "recent_elapsed_avg": 0.0,
        }

    count = len(signals)
    correct_rate = sum(1 for item in signals if item["correctness_signal"] == "correct") / count
    hint_avg = sum(item["hint_signal"] for item in signals) / count
    elapsed_avg = sum(item["elapsed_sec"] for item in signals) / count
    return {
        "recent_correct_rate": round(correct_rate, 2),
        "recent_hint_avg": round(hint_avg, 2),
        "recent_elapsed_avg": round(elapsed_avg, 2),
    }
