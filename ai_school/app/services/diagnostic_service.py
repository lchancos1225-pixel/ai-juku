from datetime import date, datetime

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from ..models import LearningLog, Problem, TeacherAnnotation, UnitDependency
from .signal_service import classify_time_signal, extract_recent_signals, summarize_recent_signals


VALID_DIAGNOSTIC_LABELS = {
    "stable_mastery",
    "hint_dependent",
    "slow_but_correct",
    "unstable_understanding",
    "fallback_risk",
    "prerequisite_gap",
    "in_progress",
    "not_enough_data",
}


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None


def get_active_teacher_annotation(db: Session, student_id: int) -> TeacherAnnotation | None:
    stmt = (
        select(TeacherAnnotation)
        .where(TeacherAnnotation.student_id == student_id)
        .order_by(desc(TeacherAnnotation.created_at))
    )
    today = date.today()
    for annotation in db.scalars(stmt).all():
        expires = _parse_iso_date(annotation.expires_at)
        if expires is None or expires >= today:
            return annotation
    return None


def _detect_unstable(signals: list[dict]) -> bool:
    if len(signals) < 4:
        return False
    recent = [item["correctness_signal"] for item in signals[:4]]
    return recent in (["correct", "wrong", "correct", "wrong"], ["wrong", "correct", "wrong", "correct"])


def determine_diagnostic_label(signals: list[dict]) -> str:
    if not signals:
        return "not_enough_data"

    top = signals[0]
    wrong_streak = top["streak_signal"]["wrong_streak"]
    correct_streak = top["streak_signal"]["correct_streak"]
    recent_correct = [item for item in signals[:5] if item["correctness_signal"] == "correct"]
    avg_hint = sum(item["hint_signal"] for item in signals[:5]) / min(len(signals), 5)

    if any(item["route_signal"] == "fallback_prerequisite_unit" for item in signals[:3]):
        return "prerequisite_gap"
    if wrong_streak >= 2:
        return "fallback_risk"
    if avg_hint >= 1:
        return "hint_dependent"
    if recent_correct and all(item["time_signal"] == "long" for item in recent_correct[: min(3, len(recent_correct))]):
        return "slow_but_correct"
    if _detect_unstable(signals):
        return "unstable_understanding"
    if correct_streak >= 2 and all(item["hint_signal"] == 0 for item in signals[: min(3, len(signals))]) and all(
        item["time_signal"] != "long" for item in signals[: min(3, len(signals))]
    ):
        return "stable_mastery"
    return "in_progress"


def build_unit_diagnostic_summary(db: Session, student_id: int) -> list[dict]:
    dependencies = db.scalars(select(UnitDependency).order_by(UnitDependency.display_order.asc())).all()
    summary: list[dict] = []

    for dependency in dependencies:
        stmt = (
            select(LearningLog, Problem)
            .join(Problem, LearningLog.problem_id == Problem.problem_id)
            .where(
                LearningLog.student_id == student_id,
                Problem.problem_type == "practice",
                or_(Problem.unit == dependency.unit_id, Problem.full_unit_id == dependency.unit_id),
            )
            .order_by(desc(LearningLog.created_at))
            .limit(6)
        )
        rows = db.execute(stmt).all()
        if not rows:
            summary.append(
                {
                    "unit_id": dependency.unit_id,
                    "display_name": dependency.display_name,
                    "diagnostic_label": "not_started",
                    "hint_dependency_level": "none",
                }
            )
            continue

        signals = []
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
                    "correctness_signal": "correct" if log.is_correct else "wrong",
                    "hint_signal": log.hint_used,
                    "time_signal": classify_time_signal(log.elapsed_sec),
                    "elapsed_sec": log.elapsed_sec,
                    "streak_signal": {
                        "correct_streak": correct_streak,
                        "wrong_streak": wrong_streak,
                    },
                    "route_signal": log.route_decision or "reinforce_current_unit",
                }
            )

        hint_avg = sum(item["hint_signal"] for item in signals) / len(signals)
        hint_level = "high" if hint_avg >= 1.5 else "medium" if hint_avg >= 0.5 else "low"
        summary.append(
            {
                "unit_id": dependency.unit_id,
                "display_name": dependency.display_name,
                "diagnostic_label": determine_diagnostic_label(signals),
                "hint_dependency_level": hint_level,
            }
        )
    return summary


def build_speed_profile(signals: list[dict]) -> str:
    if not signals:
        return "unknown"
    avg_elapsed = summarize_recent_signals(signals)["recent_elapsed_avg"]
    if avg_elapsed >= 45:
        return "slow"
    if avg_elapsed >= 20:
        return "normal"
    return "fast"


def build_fallback_risk_level(signals: list[dict]) -> str:
    if not signals:
        return "low"
    recent_wrong = sum(1 for item in signals[:5] if item["correctness_signal"] == "wrong")
    if any(item["route_signal"] == "fallback_prerequisite_unit" for item in signals[:3]):
        return "high"
    if recent_wrong >= 3:
        return "high"
    if recent_wrong >= 2:
        return "medium"
    return "low"


def build_recent_signal_summary(db: Session, student_id: int) -> dict:
    return summarize_recent_signals(extract_recent_signals(db, student_id))


def build_diagnostic_snapshot(db: Session, student_id: int) -> dict:
    signals = extract_recent_signals(db, student_id)
    teacher_annotation = get_active_teacher_annotation(db, student_id)
    diagnostic_label = determine_diagnostic_label(signals)
    teacher_annotated = False
    annotation_note = None
    if teacher_annotation is not None and teacher_annotation.diagnostic_correction in VALID_DIAGNOSTIC_LABELS:
        diagnostic_label = teacher_annotation.diagnostic_correction
        teacher_annotated = True
        annotation_note = teacher_annotation.note
    return {
        "diagnostic_label": diagnostic_label,
        "recent_signal_summary": summarize_recent_signals(signals),
        "unit_diagnostic_summary": build_unit_diagnostic_summary(db, student_id),
        "speed_profile": build_speed_profile(signals),
        "fallback_risk_level": build_fallback_risk_level(signals),
        "teacher_annotated": teacher_annotated,
        "annotation_note": annotation_note,
    }
