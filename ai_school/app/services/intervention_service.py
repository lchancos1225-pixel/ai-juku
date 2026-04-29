from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..models import LearningLog, Problem, StudentState


REINFORCE_SAME_PATTERN = "reinforce_same_pattern"
RETRY_WITH_HINT = "retry_with_hint"
FALLBACK_PREREQUISITE = "fallback_prerequisite"
SLOW_DOWN_AND_CONFIRM = "slow_down_and_confirm"
EXPLAIN_DIFFERENTLY = "explain_differently"
TEACHER_INTERVENTION_NEEDED = "teacher_intervention_needed"
ADVANCE_WITH_CONFIDENCE = "advance_with_confidence"
MONITOR_ONLY = "monitor_only"

KNOWN_INTERVENTION_CANDIDATES = {
    REINFORCE_SAME_PATTERN,
    RETRY_WITH_HINT,
    FALLBACK_PREREQUISITE,
    SLOW_DOWN_AND_CONFIRM,
    EXPLAIN_DIFFERENTLY,
    TEACHER_INTERVENTION_NEEDED,
    ADVANCE_WITH_CONFIDENCE,
    MONITOR_ONLY,
}


def recent_interventions(db: Session, student_id: int, limit: int = 5) -> list[str]:
    stmt = (
        select(LearningLog.intervention_type)
        .where(LearningLog.student_id == student_id, LearningLog.intervention_type.is_not(None))
        .order_by(desc(LearningLog.created_at))
        .limit(limit)
    )
    return [item for item in db.scalars(stmt).all() if item]


def _teacher_intervention_needed(
    diagnostic_label: str,
    dominant_error_pattern: str | None,
    hint_dependency_level: str,
    fallback_risk_level: str,
    recent_results: list[dict],
) -> bool:
    hint2_count = sum(1 for item in recent_results[:4] if item.get("hint_used", 0) >= 2)
    comprehension_count = sum(1 for item in recent_results[:4] if item.get("error_pattern") == "comprehension_gap")
    fallback_count = sum(1 for item in recent_results[:4] if item.get("route_decision") == "fallback_prerequisite_unit")
    unstable_count = sum(1 for item in recent_results[:6] if not item.get("is_correct"))

    return any(
        [
            fallback_count >= 2,
            hint2_count >= 2 and hint_dependency_level == "high",
            comprehension_count >= 2,
            diagnostic_label == "unstable_understanding" and unstable_count >= 4,
            dominant_error_pattern in {"comprehension_gap", "prerequisite_gap"} and fallback_risk_level == "high",
        ]
    )


def select_intervention(
    diagnostic_label: str,
    dominant_error_pattern: str | None,
    hint_dependency_level: str,
    speed_profile: str,
    fallback_risk_level: str,
    recommended_route: str,
    recent_results: list[dict],
) -> tuple[str, str, bool]:
    teacher_needed = _teacher_intervention_needed(
        diagnostic_label,
        dominant_error_pattern,
        hint_dependency_level,
        fallback_risk_level,
        recent_results,
    )
    if teacher_needed:
        return (
            TEACHER_INTERVENTION_NEEDED,
            "fallback/hint2/comprehension の強い信号が続いているため、短い教師介入が必要",
            True,
        )

    if diagnostic_label == "stable_mastery" and recommended_route == "advance_next_unit":
        return ADVANCE_WITH_CONFIDENCE, "安定正答が続き、次単元へ進める条件を満たしている", False
    if diagnostic_label == "prerequisite_gap" or fallback_risk_level == "high":
        return FALLBACK_PREREQUISITE, "前提理解の抜け、または戻りリスクが高いため前提単元補強を優先", False
    if diagnostic_label == "hint_dependent":
        return RETRY_WITH_HINT, "ヒント依存が続いているため、支援付きで再挑戦させる", False
    if diagnostic_label == "slow_but_correct" or speed_profile == "slow":
        return SLOW_DOWN_AND_CONFIRM, "正解には近いが速度負荷があるため、速度を落として確認する", False
    if dominant_error_pattern == "comprehension_gap":
        return EXPLAIN_DIFFERENTLY, "問題理解のずれが疑われるため、説明の言い換えを優先する", False
    if dominant_error_pattern in {"sign_error", "formula_setup_error", "arithmetic_error"}:
        return REINFORCE_SAME_PATTERN, "同じ誤答型が続いているため、同型問題で補強する", False
    return MONITOR_ONLY, "強い介入条件はまだ揃っていないため、観察を続ける", False


def build_intervention_snapshot(
    db: Session,
    student_id: int,
    diagnostic_label: str,
    dominant_error_pattern: str | None,
    hint_dependency_level: str,
    speed_profile: str,
    fallback_risk_level: str,
    recommended_route: str,
    recent_results: list[dict],
) -> dict:
    recommended_intervention, intervention_reason, teacher_needed = select_intervention(
        diagnostic_label=diagnostic_label,
        dominant_error_pattern=dominant_error_pattern,
        hint_dependency_level=hint_dependency_level,
        speed_profile=speed_profile,
        fallback_risk_level=fallback_risk_level,
        recommended_route=recommended_route,
        recent_results=recent_results,
    )
    past = recent_interventions(db, student_id)
    return {
        "current_intervention": past[0] if past else recommended_intervention,
        "recommended_intervention": recommended_intervention,
        "recent_interventions": past[:5],
        "intervention_reason": intervention_reason,
        "teacher_intervention_needed": teacher_needed,
    }


def choose_problem_for_intervention(
    db: Session,
    state: StudentState,
    current_problem: Problem,
    intervention_type: str,
) -> Problem | None:
    if intervention_type == RETRY_WITH_HINT:
        return current_problem

    if intervention_type == REINFORCE_SAME_PATTERN:
        stmt = (
            select(Problem)
            .where(
                Problem.full_unit_id == current_problem.full_unit_id,
                Problem.subject == current_problem.subject,
                Problem.difficulty == current_problem.difficulty,
                Problem.problem_id != current_problem.problem_id,
                Problem.status == 'approved',
            )
            .order_by(Problem.problem_id.asc())
        )
        return db.scalar(stmt)

    return None
