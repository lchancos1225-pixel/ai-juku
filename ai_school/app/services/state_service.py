from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..models import Classroom, LearningLog, Problem, Student, StudentState, UnitDependency, UnitMastery
from ..schemas import StudentStateSummary
from .conversation_service import get_recent_turns
from .diagnostic_service import build_diagnostic_snapshot, get_active_teacher_annotation
from .error_pattern_service import normalize_error_pattern
from .intervention_service import build_intervention_snapshot
from .routing_service import (
    ADVANCE_ROUTE,
    FALLBACK_ROUTE,
    REINFORCE_ROUTE,
    get_next_problem_candidate_ids,
    get_recommended_route,
    recent_unit_history,
)
from .unit_map_service import build_current_position_summary, resolve_unit_map_entry


def effective_unit_unlock(classroom: Classroom | None, state: StudentState | None) -> tuple[str, str | None]:
    if state is not None and getattr(state, "unit_unlock_mode", None):
        mode = state.unit_unlock_mode
        up_to = (getattr(state, "unit_unlock_up_to", None) or None) if mode == "up_to" else None
        return mode, up_to
    if classroom is not None:
        return (getattr(classroom, "unit_unlock_mode", "progressive") or "progressive"), getattr(
            classroom, "unit_unlock_up_to", None
        )
    return "progressive", None


def ensure_student_state(db: Session, student: Student, initial_problem_id: int | None = None) -> StudentState:
    state = db.get(StudentState, student.student_id)
    if state is None:
        first_unit = db.scalar(select(UnitDependency).order_by(UnitDependency.display_order.asc()))
        state = StudentState(
            student_id=student.student_id,
            current_unit=first_unit.unit_id if first_unit else None,
            current_level=1,
            mastery_score=0.0,
            weak_unit=None,
            last_problem_id=initial_problem_id,
        )
        db.add(state)
        db.commit()
        db.refresh(state)
    ensure_unit_mastery_rows(db, student.student_id)
    return state


def ensure_unit_mastery_rows(db: Session, student_id: int) -> None:
    unit_ids = db.scalars(select(UnitDependency.unit_id).order_by(UnitDependency.display_order.asc())).all()
    changed = False
    for unit_id in unit_ids:
        mastery = db.get(UnitMastery, (student_id, unit_id))
        if mastery is None:
            db.add(
                UnitMastery(
                    student_id=student_id,
                    unit_id=unit_id,
                    mastery_score=0.0,
                    correct_count=0,
                    wrong_count=0,
                    hint_count=0,
                    avg_elapsed_sec=0.0,
                )
            )
            changed = True
    if changed:
        db.commit()


def _recent_results(db: Session, student_id: int, limit: int = 8, *, practice_only: bool = False) -> list[dict]:
    stmt = (
        select(LearningLog, Problem)
        .join(Problem, LearningLog.problem_id == Problem.problem_id)
        .where(LearningLog.student_id == student_id)
    )
    if practice_only:
        stmt = stmt.where(Problem.problem_type == "practice")
    stmt = stmt.order_by(desc(LearningLog.created_at)).limit(limit)
    rows = db.execute(stmt).all()
    return [
        {
            "problem_id": log.problem_id,
            "unit_id": problem.full_unit_id or problem.unit,
            "is_correct": bool(log.is_correct),
            "hint_used": log.hint_used,
            "hint_1_seen": log.hint_used >= 1,
            "hint_2_seen": log.hint_used >= 2,
            "elapsed_sec": log.elapsed_sec,
            "route_decision": log.route_decision or REINFORCE_ROUTE,
            "error_pattern": normalize_error_pattern(log.error_pattern),
            "intervention_type": log.intervention_type,
            "answer_payload": log.answer_payload,
            "created_at": log.created_at.isoformat(),
        }
        for log, problem in rows
    ]


def _recent_error_patterns(recent_results: list[dict], limit: int = 5) -> list[str]:
    patterns = [
        item["error_pattern"]
        for item in recent_results
        if not item.get("is_correct") and item.get("error_pattern")
    ]
    return patterns[:limit]


def _dominant_error_pattern(recent_results: list[dict]) -> str | None:
    counts: dict[str, int] = {}
    for pattern in _recent_error_patterns(recent_results, limit=8):
        counts[pattern] = counts.get(pattern, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def _unit_error_summary(db: Session, student_id: int) -> dict[str, dict[str, int]]:
    stmt = (
        select(LearningLog, Problem)
        .join(Problem, LearningLog.problem_id == Problem.problem_id)
        .where(
            LearningLog.student_id == student_id,
            LearningLog.is_correct.is_(False),
            Problem.problem_type == "practice",
        )
        .order_by(desc(LearningLog.created_at))
        .limit(30)
    )
    rows = db.execute(stmt).all()
    summary: dict[str, dict[str, int]] = {}
    for log, problem in rows:
        pattern = normalize_error_pattern(log.error_pattern)
        if pattern is None:
            continue
        ukey = problem.full_unit_id or problem.unit
        if ukey not in summary:
            summary[ukey] = {}
        summary[ukey][pattern] = summary[ukey].get(pattern, 0) + 1
    return summary


def infer_weak_points(db: Session, student_id: int, limit: int = 12) -> list[dict]:
    stmt = (
        select(LearningLog, Problem)
        .join(Problem, LearningLog.problem_id == Problem.problem_id)
        .where(LearningLog.student_id == student_id)
        .order_by(desc(LearningLog.created_at))
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    buckets: dict[tuple[str, int], dict] = {}
    for log, problem in rows:
        key = (problem.full_unit_id or problem.unit, problem.difficulty)
        if key not in buckets:
            buckets[key] = {
                "unit_id": problem.full_unit_id or problem.unit,
                "difficulty": problem.difficulty,
                "wrong_count": 0,
                "hinted_correct_count": 0,
            }
        if not log.is_correct:
            buckets[key]["wrong_count"] += 1
        if log.is_correct and log.hint_used > 0:
            buckets[key]["hinted_correct_count"] += 1

    weak_points = [value for value in buckets.values() if value["wrong_count"] > 0 or value["hinted_correct_count"] > 0]
    weak_points.sort(key=lambda item: (item["wrong_count"], item["hinted_correct_count"]), reverse=True)
    return weak_points[:5]


def _update_unit_mastery(
    db: Session,
    student_id: int,
    unit_id: str,
    was_correct: bool,
    hint_used: int,
    elapsed_sec: int,
) -> UnitMastery:
    mastery = db.get(UnitMastery, (student_id, unit_id))
    if mastery is None:
        mastery = UnitMastery(
            student_id=student_id,
            unit_id=unit_id,
            mastery_score=0.0,
            correct_count=0,
            wrong_count=0,
            hint_count=0,
            avg_elapsed_sec=0.0,
        )
        db.add(mastery)
        db.flush()

    if was_correct:
        mastery.correct_count += 1
        delta = 0.02 if hint_used >= 2 else 0.04 if hint_used == 1 else 0.1
    else:
        mastery.wrong_count += 1
        delta = -0.12
    mastery.hint_count += hint_used

    total_attempts = mastery.correct_count + mastery.wrong_count
    mastery.avg_elapsed_sec = round(
        ((mastery.avg_elapsed_sec * (total_attempts - 1)) + elapsed_sec) / total_attempts,
        2,
    ) if total_attempts > 0 else 0.0
    mastery.mastery_score = max(0.0, min(1.0, round(mastery.mastery_score + delta, 2)))
    return mastery


def apply_practice_attempt_to_unit_mastery(
    db: Session,
    student_id: int,
    unit_key: str,
    was_correct: bool,
    hint_used: int,
    elapsed_sec: int,
) -> UnitMastery:
    """Apply one practice attempt to UnitMastery before route decision."""
    return _update_unit_mastery(db, student_id, unit_key, was_correct, hint_used, elapsed_sec)


def build_practice_submit_intervention_context(db: Session, student_id: int, limit: int = 8) -> dict:
    """Post-submit intervention: practice logs only; aligns with diagnostic snapshot."""
    recent = _recent_results(db, student_id, limit=limit, practice_only=True)
    diagnostic = build_diagnostic_snapshot(db, student_id)
    return {
        "recent_results": recent,
        "diagnostic_label": diagnostic["diagnostic_label"],
        "dominant_error_pattern": _dominant_error_pattern(recent),
        "hint_dependency_level": _hint_dependency_level(recent),
        "speed_profile": diagnostic["speed_profile"],
        "fallback_risk_level": diagnostic["fallback_risk_level"],
    }


def update_student_state(
    db: Session,
    state: StudentState,
    current_problem: Problem,
    next_problem: Problem | None,
    was_correct: bool,
    hint_used: int,
    elapsed_sec: int,
    *,
    apply_unit_mastery: bool = True,
) -> StudentState:
    if apply_unit_mastery:
        unit_mastery = _update_unit_mastery(
            db,
            student_id=state.student_id,
            unit_id=current_problem.full_unit_id or current_problem.unit,
            was_correct=was_correct,
            hint_used=hint_used,
            elapsed_sec=elapsed_sec,
        )
    else:
        unit_mastery = db.get(
            UnitMastery, (state.student_id, current_problem.full_unit_id or current_problem.unit)
        )

    state.mastery_score = (
        unit_mastery.mastery_score if unit_mastery is not None else state.mastery_score
    )
    state.last_problem_id = current_problem.problem_id
    weak_points = infer_weak_points(db, state.student_id)
    state.weak_unit = weak_points[0]["unit_id"] if weak_points else None

    if next_problem is not None:
        next_mastery = db.get(UnitMastery, (state.student_id, next_problem.full_unit_id or next_problem.unit))
        state.current_unit = next_problem.full_unit_id or next_problem.unit
        state.current_level = next_problem.difficulty
        state.mastery_score = next_mastery.mastery_score if next_mastery is not None else state.mastery_score
    else:
        state.current_unit = current_problem.full_unit_id or current_problem.unit
        state.current_level = current_problem.difficulty
    db.commit()
    db.refresh(state)
    return state


def _hint_dependency_level(recent_results: list[dict]) -> str:
    if not recent_results:
        return "none"
    count = min(len(recent_results), 5)
    average = sum(item.get("hint_used", 0) for item in recent_results[:count]) / count
    if average >= 1.5:
        return "high"
    if average >= 0.5:
        return "medium"
    return "low"


def _unit_hint_summary(db: Session, student_id: int) -> list[dict]:
    dependencies = db.scalars(select(UnitDependency).order_by(UnitDependency.display_order.asc())).all()
    summary = []
    for dependency in dependencies:
        stmt = (
            select(LearningLog)
            .join(Problem, LearningLog.problem_id == Problem.problem_id)
            .where(LearningLog.student_id == student_id, Problem.full_unit_id == dependency.unit_id)
            .order_by(desc(LearningLog.created_at))
            .limit(20)
        )
        logs = db.scalars(stmt).all()
        total = len(logs)
        hint_1_count = sum(1 for log in logs if log.hint_used >= 1)
        hint_2_count = sum(1 for log in logs if log.hint_used >= 2)
        summary.append(
            {
                "unit_id": dependency.unit_id,
                "display_name": dependency.display_name,
                "hint_1_rate": round(hint_1_count / total, 2) if total else 0.0,
                "hint_2_rate": round(hint_2_count / total, 2) if total else 0.0,
            }
        )
    return summary


def _unit_mastery_summary(db: Session, student_id: int) -> list[dict]:
    dependencies = db.scalars(select(UnitDependency).order_by(UnitDependency.display_order.asc())).all()
    summary = []
    for dependency in dependencies:
        mastery = db.get(UnitMastery, (student_id, dependency.unit_id))
        mastery_score = mastery.mastery_score if mastery else 0.0
        attempts = (mastery.correct_count + mastery.wrong_count) if mastery else 0
        if attempts == 0:
            status = "not_started"
        elif mastery_score >= 0.75:
            status = "mastered"
        elif mastery_score < 0.40:
            status = "needs_support"
        else:
            status = "in_progress"
        summary.append(
            {
                "unit_id": dependency.unit_id,
                "display_name": dependency.display_name,
                "subject": dependency.subject or "math",
                "mastery_score": mastery_score,
                "status": status,
                "correct_count": mastery.correct_count if mastery else 0,
                "wrong_count": mastery.wrong_count if mastery else 0,
                "hint_count": mastery.hint_count if mastery else 0,
            }
        )
    return summary


def build_student_summary(db: Session, student_id: int, current_user_role: str | None = None) -> StudentStateSummary | None:
    student = db.get(Student, student_id)
    if student is None:
        return None

    state = ensure_student_state(db, student)
    current_problem = db.get(Problem, state.last_problem_id) if state.last_problem_id else None
    if current_problem is None and state.current_unit:
        _subject = 'english' if state.current_unit.startswith('eng_') else 'math'
        current_problem = db.scalar(
            select(Problem)
            .where(Problem.unit == state.current_unit, Problem.subject == _subject)
            .order_by(Problem.difficulty.asc(), Problem.problem_id.asc())
        )
    current_unit_entry = resolve_unit_map_entry(
        state.current_unit,
        current_problem.sub_unit if current_problem is not None else None,
        current_problem.full_unit_id if current_problem is not None else None,
    )

    recommended_route = get_recommended_route(db, state, current_problem)
    next_problem_candidate_ids = (
        get_next_problem_candidate_ids(db, state, current_problem) if current_problem is not None else []
    )
    recent_results = _recent_results(db, student_id, practice_only=True)
    diagnostic_snapshot = build_diagnostic_snapshot(db, student_id)
    recent_error_patterns = _recent_error_patterns(recent_results)
    teacher_annotation = get_active_teacher_annotation(db, student_id)
    intervention_snapshot = build_intervention_snapshot(
        db,
        student_id=student_id,
        diagnostic_label=diagnostic_snapshot["diagnostic_label"],
        dominant_error_pattern=_dominant_error_pattern(recent_results),
        hint_dependency_level=_hint_dependency_level(recent_results),
        speed_profile=diagnostic_snapshot["speed_profile"],
        fallback_risk_level=diagnostic_snapshot["fallback_risk_level"],
        recommended_route=recommended_route,
        recent_results=recent_results,
    )

    return StudentStateSummary(
        student_id=student.student_id,
        display_name=student.display_name,
        current_user_role=current_user_role,
        current_unit=state.current_unit,
        current_full_unit_id=current_unit_entry["full_unit_id"] if current_unit_entry else None,
        current_unit_display_name=current_unit_entry["display_name"] if current_unit_entry else None,
        prerequisite_full_unit_id=current_unit_entry["prerequisite_full_unit_id"] if current_unit_entry else None,
        next_full_unit_id=current_unit_entry["next_full_unit_id"] if current_unit_entry else None,
        current_position_summary=build_current_position_summary(current_unit_entry),
        current_level=state.current_level,
        mastery_score=state.mastery_score,
        unit_mastery_summary=_unit_mastery_summary(db, student_id),
        recent_results=recent_results,
        recent_hint_usage=[item["hint_used"] for item in recent_results[:5]],
        hint_dependency_level=_hint_dependency_level(recent_results),
        unit_hint_summary=_unit_hint_summary(db, student_id),
        diagnostic_label=diagnostic_snapshot["diagnostic_label"],
        recent_signal_summary=diagnostic_snapshot["recent_signal_summary"],
        unit_diagnostic_summary=diagnostic_snapshot["unit_diagnostic_summary"],
        speed_profile=diagnostic_snapshot["speed_profile"],
        fallback_risk_level=diagnostic_snapshot["fallback_risk_level"],
        recent_error_patterns=recent_error_patterns,
        dominant_error_pattern=_dominant_error_pattern(recent_results),
        unit_error_summary=_unit_error_summary(db, student_id),
        recent_conversation_turns=get_recent_turns(db, student_id, n=4),
        current_intervention=intervention_snapshot["current_intervention"],
        recommended_intervention=intervention_snapshot["recommended_intervention"],
        recent_interventions=intervention_snapshot["recent_interventions"],
        intervention_reason=intervention_snapshot["intervention_reason"],
        teacher_intervention_needed=intervention_snapshot["teacher_intervention_needed"],
        teacher_override_pending=state.teacher_override_problem_id is not None,
        teacher_annotation={
            "active": teacher_annotation is not None,
            "diagnostic_correction": teacher_annotation.diagnostic_correction if teacher_annotation else None,
            "reason_code": teacher_annotation.reason_code if teacher_annotation else None,
            "note": teacher_annotation.note if teacher_annotation else diagnostic_snapshot.get("annotation_note"),
            "expires_at": teacher_annotation.expires_at if teacher_annotation else None,
        },
        weak_points=infer_weak_points(db, student_id),
        next_problem_candidate_ids=next_problem_candidate_ids,
        recommended_route=recommended_route,
    )


def _unit_accuracy(mastery: UnitMastery | None) -> float:
    if mastery is None:
        return 0.0
    total = mastery.correct_count + mastery.wrong_count
    return round(mastery.correct_count / total, 2) if total else 0.0


def _recent_transition_history(db: Session, student_id: int, limit: int = 5) -> list[str]:
    label_map = {
        unit.unit_id: unit.display_name
        for unit in db.scalars(select(UnitDependency).order_by(UnitDependency.display_order.asc())).all()
    }
    stmt = (
        select(LearningLog, Problem)
        .join(Problem, LearningLog.problem_id == Problem.problem_id)
        .where(LearningLog.student_id == student_id)
        .order_by(desc(LearningLog.created_at))
        .limit(20)
    )
    rows = list(reversed(db.execute(stmt).all()))
    transitions: list[str] = []
    last_unit: str | None = None
    for _, problem in rows:
        if last_unit is not None and last_unit != problem.unit:
            transitions.append(
                f"{label_map.get(last_unit, last_unit)} -> {label_map.get(problem.unit, problem.unit)}"
            )
        last_unit = problem.unit
    return transitions[-limit:]


def build_teacher_student_metrics(db: Session, student_id: int) -> dict:
    recent_results = _recent_results(db, student_id, limit=3, practice_only=True)
    student_state = db.get(StudentState, student_id)
    current_unit = student_state.current_unit if student_state else None
    current_problem = db.get(Problem, student_state.last_problem_id) if student_state and student_state.last_problem_id else None
    current_unit_entry = resolve_unit_map_entry(
        current_unit,
        current_problem.sub_unit if current_problem is not None else None,
        current_problem.full_unit_id if current_problem is not None else None,
    )
    route = get_recommended_route(db, student_state, current_problem) if student_state else REINFORCE_ROUTE
    diagnostic_snapshot = build_diagnostic_snapshot(db, student_id)
    error_summary = _unit_error_summary(db, student_id)
    teacher_annotation = get_active_teacher_annotation(db, student_id)
    all_recent_results = _recent_results(db, student_id, limit=8, practice_only=True)
    intervention_snapshot = build_intervention_snapshot(
        db,
        student_id=student_id,
        diagnostic_label=diagnostic_snapshot["diagnostic_label"],
        dominant_error_pattern=_dominant_error_pattern(all_recent_results),
        hint_dependency_level=_hint_dependency_level(all_recent_results),
        speed_profile=diagnostic_snapshot["speed_profile"],
        fallback_risk_level=diagnostic_snapshot["fallback_risk_level"],
        recommended_route=route,
        recent_results=all_recent_results,
    )

    unit_progress = []
    for dependency in db.scalars(select(UnitDependency).order_by(UnitDependency.display_order.asc())).all():
        mastery = db.get(UnitMastery, (student_id, dependency.unit_id))
        unit_progress.append(
            {
                "unit_id": dependency.unit_id,
                "display_name": dependency.display_name,
                "mastery_score": mastery.mastery_score if mastery else 0.0,
                "accuracy": _unit_accuracy(mastery),
            }
        )

    wrong_history = [
        {
            "problem_id": log.problem_id,
            "unit_id": problem.unit,
            "difficulty": problem.difficulty,
        }
        for log, problem in recent_unit_history(db, student_id, current_unit, limit=6)
    ] if current_unit else []

    return {
        "recent_three_results": recent_results,
        "wrong_tendency": infer_weak_points(db, student_id),
        "recent_wrong_history": [item for item in wrong_history if True][:3],
        "recommended_route": route,
        "unit_progress": unit_progress,
        "transition_history": _recent_transition_history(db, student_id),
        "hint_dependency_level": _hint_dependency_level(recent_results),
        "unit_hint_summary": _unit_hint_summary(db, student_id),
        "diagnostic_label": diagnostic_snapshot["diagnostic_label"],
        "recent_signal_summary": diagnostic_snapshot["recent_signal_summary"],
        "unit_diagnostic_summary": diagnostic_snapshot["unit_diagnostic_summary"],
        "speed_profile": diagnostic_snapshot["speed_profile"],
        "fallback_risk_level": diagnostic_snapshot["fallback_risk_level"],
        "recent_error_patterns": _recent_error_patterns(recent_results),
        "dominant_error_pattern": _dominant_error_pattern(all_recent_results),
        "unit_error_summary": error_summary,
        "current_intervention": intervention_snapshot["current_intervention"],
        "recommended_intervention": intervention_snapshot["recommended_intervention"],
        "recent_interventions": intervention_snapshot["recent_interventions"],
        "intervention_reason": intervention_snapshot["intervention_reason"],
        "teacher_intervention_needed": intervention_snapshot["teacher_intervention_needed"],
        "teacher_override_pending": student_state.teacher_override_problem_id is not None if student_state else False,
        "teacher_annotation": {
            "active": teacher_annotation is not None,
            "diagnostic_correction": teacher_annotation.diagnostic_correction if teacher_annotation else None,
            "reason_code": teacher_annotation.reason_code if teacher_annotation else None,
            "note": teacher_annotation.note if teacher_annotation else diagnostic_snapshot.get("annotation_note"),
            "expires_at": teacher_annotation.expires_at if teacher_annotation else None,
        },
        "current_full_unit_id": current_unit_entry["full_unit_id"] if current_unit_entry else None,
        "current_unit_display_name": current_unit_entry["display_name"] if current_unit_entry else None,
        "prerequisite_full_unit_id": current_unit_entry["prerequisite_full_unit_id"] if current_unit_entry else None,
        "next_full_unit_id": current_unit_entry["next_full_unit_id"] if current_unit_entry else None,
        "current_position_summary": build_current_position_summary(current_unit_entry),
        "display_order": current_unit_entry["display_order"] if current_unit_entry else None,
    }


_EXCLUDE_TEACHER_AI_SLIM = frozenset({
    "display_name",
    "student_id",
    "current_user_role",
    "recent_conversation_turns",
    "next_problem_candidate_ids",
    "teacher_annotation",
    "unit_diagnostic_summary",
    "unit_error_summary",
    "unit_hint_summary",
})


def slim_teacher_summary_context(full: dict) -> dict:
    """Minimal dict for teacher AI summary (no PII / large blobs). Pass before generate_teacher_summary."""
    slim: dict = {k: v for k, v in full.items() if k not in _EXCLUDE_TEACHER_AI_SLIM}
    um = slim.get("unit_mastery_summary")
    if isinstance(um, list) and len(um) > 6:
        slim["unit_mastery_summary"] = um[:6]
    rr = slim.get("recent_results")
    if isinstance(rr, list):
        slim["recent_results"] = rr[:5]
    wp = slim.get("weak_points")
    if isinstance(wp, list):
        slim["weak_points"] = wp[:1]
    sig = slim.get("recent_signal_summary")
    if isinstance(sig, dict):
        slim["recent_signal_summary"] = {
            k: sig[k] for k in ("recent_correct_rate", "recent_hint_avg", "recent_elapsed_avg") if k in sig
        }
    return slim
