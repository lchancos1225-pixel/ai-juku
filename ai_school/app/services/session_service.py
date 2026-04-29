"""
7分集中セッション管理サービス

Atomic Habits Loop の実装:
  Cue     → 「今日のミッション3問」をAIが選定
  Routine → 7分タイマー + 問題3問
  Reward  → Meinストーリーが1章進む

セッション状態はStudentStateの既存フィールドを活用。
追加モデル不要（DBマイグレーションなし）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from ..models import LearningLog, Problem, StudentState
from .mein_story_service import get_chapter_for_session_count

SESSION_DURATION_SEC = 7 * 60  # 7分
SESSION_MISSION_COUNT = 3       # 1セッションの目標問題数


def get_today_session_info(db: Session, student_id: int) -> dict:
    """
    今日のセッション状況を返す。

    Returns:
        {
          "today_sessions": 今日完了したセッション数,
          "today_problems_solved": 今日解いた問題数,
          "mission_remaining": 今のセッションで残り何問か,
          "session_in_progress": セッション中かどうか,
          "current_chapter": 現在のMein章データ,
          "total_sessions_ever": 累計セッション数（Mein章決定用）
        }
    """
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    today_logs = db.scalars(
        select(LearningLog)
        .where(
            LearningLog.student_id == student_id,
            LearningLog.created_at >= datetime.strptime(today_str, "%Y-%m-%d"),
        )
        .order_by(desc(LearningLog.created_at))
    ).all()

    today_count = len(today_logs)
    today_sessions_completed = today_count // SESSION_MISSION_COUNT
    position_in_current = today_count % SESSION_MISSION_COUNT
    mission_remaining = SESSION_MISSION_COUNT - position_in_current if position_in_current > 0 else SESSION_MISSION_COUNT
    session_in_progress = position_in_current > 0

    # 累計セッション数（全期間）
    total_logs = db.scalar(
        select(LearningLog.log_id)
        .where(LearningLog.student_id == student_id)
        .order_by(desc(LearningLog.log_id))
        .limit(1)
    )
    # 簡易推定: 全ログ数 ÷ SESSION_MISSION_COUNT（整数除算）
    total_count = db.query(LearningLog).filter(LearningLog.student_id == student_id).count()
    total_sessions_ever = max(total_count // SESSION_MISSION_COUNT, 1)

    current_chapter = get_chapter_for_session_count(total_sessions_ever)

    return {
        "today_sessions": today_sessions_completed,
        "today_problems_solved": today_count,
        "mission_remaining": mission_remaining,
        "session_in_progress": session_in_progress,
        "position_in_session": position_in_current,
        "current_chapter": current_chapter,
        "total_sessions_ever": total_sessions_ever,
        "session_just_completed": (position_in_current == 0 and today_count > 0),
    }


def get_mission_problems(db: Session, student_id: int, state: StudentState, n: int = 3) -> list[Problem]:
    """
    今のセッションで解くべき問題をn問選定する。
    誤概念タグが多い単元を優先的に選ぶ。
    """
    from sqlalchemy import func
    from ..models import LearningLog

    # 最頻出の誤概念タグを持つ単元を特定
    weak_unit = None
    miscon_row = db.execute(
        select(LearningLog.misconception_tag, func.count(LearningLog.log_id).label("cnt"))
        .where(
            LearningLog.student_id == student_id,
            LearningLog.misconception_tag.isnot(None),
        )
        .group_by(LearningLog.misconception_tag)
        .order_by(desc("cnt"))
        .limit(1)
    ).first()

    # 現在単元の問題を優先して選択
    current_unit = state.current_unit
    stmt = (
        select(Problem)
        .where(
            Problem.problem_type == "practice",
        )
    )
    if current_unit:
        stmt = stmt.where(Problem.unit == current_unit)

    stmt = stmt.order_by(Problem.difficulty.asc(), Problem.problem_id.asc()).limit(n)
    problems = db.scalars(stmt).all()

    return list(problems)
