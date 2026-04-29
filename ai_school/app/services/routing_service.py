from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from ..models import LearningLog, Problem, StudentState, UnitDependency, UnitMastery
from .intervention_service import (
    ADVANCE_WITH_CONFIDENCE,
    FALLBACK_PREREQUISITE,
    REINFORCE_SAME_PATTERN,
    RETRY_WITH_HINT,
    choose_problem_for_intervention,
)


ADVANCE_ROUTE = "advance_next_unit"
REINFORCE_ROUTE = "reinforce_current_unit"
FALLBACK_ROUTE = "fallback_prerequisite_unit"


def recent_unit_history(
    db: Session, student_id: int, unit: str, limit: int = 6, *, practice_only: bool = True
) -> list[tuple[LearningLog, Problem]]:
    if not unit:
        return []
    stmt = (
        select(LearningLog, Problem)
        .join(Problem, LearningLog.problem_id == Problem.problem_id)
        .where(
            LearningLog.student_id == student_id,
            or_(Problem.full_unit_id == unit, Problem.unit == unit),
        )
    )
    if practice_only:
        stmt = stmt.where(Problem.problem_type == "practice")
    stmt = stmt.order_by(desc(LearningLog.created_at)).limit(limit)
    return db.execute(stmt).all()


def recent_problem_ids(db: Session, student_id: int, limit: int = 5, *, practice_only: bool = True) -> list[int]:
    stmt = select(LearningLog.problem_id).join(Problem, LearningLog.problem_id == Problem.problem_id).where(
        LearningLog.student_id == student_id
    )
    if practice_only:
        stmt = stmt.where(Problem.problem_type == "practice")
    stmt = stmt.order_by(desc(LearningLog.created_at)).limit(limit)
    return list(db.scalars(stmt).all())


def recent_streaks(db: Session, student_id: int, unit: str) -> dict:
    history = recent_unit_history(db, student_id, unit, limit=6)
    correct_streak = 0
    wrong_streak = 0

    for log, _ in history:
        if log.is_correct and log.hint_used == 0 and wrong_streak == 0:
            correct_streak += 1
        else:
            break

    for log, _ in history:
        if not log.is_correct and correct_streak == 0:
            wrong_streak += 1
        else:
            break

    recent_correct = sum(1 for log, _ in history[:5] if log.is_correct and log.hint_used == 0)
    recent_wrong = sum(1 for log, _ in history[:5] if not log.is_correct)
    return {
        "correct_streak": correct_streak,
        "wrong_streak": wrong_streak,
        "recent_correct": recent_correct,
        "recent_wrong": recent_wrong,
        "history": history,
    }


def get_unit_dependency(db: Session, unit_id: str | None) -> UnitDependency | None:
    if unit_id is None:
        return None
    return db.get(UnitDependency, unit_id)


def get_unit_mastery(db: Session, student_id: int, unit_id: str | None) -> UnitMastery | None:
    if unit_id is None:
        return None
    return db.get(UnitMastery, (student_id, unit_id))


def get_recommended_route(db: Session, state: StudentState, current_problem: Problem | None) -> str:
    if current_problem is not None:
        unit_id = current_problem.full_unit_id or current_problem.unit
    else:
        unit_id = state.current_unit
    if unit_id is None:
        return REINFORCE_ROUTE

    dependency = get_unit_dependency(db, unit_id)
    mastery = get_unit_mastery(db, state.student_id, unit_id)
    streaks = recent_streaks(db, state.student_id, unit_id)

    if (
        dependency is not None
        and dependency.next_unit_id
        and mastery is not None
        and mastery.mastery_score >= 0.55
        and mastery.correct_count >= 3
        and streaks["recent_correct"] >= 3
    ):
        return ADVANCE_ROUTE

    if (
        dependency is not None
        and dependency.prerequisite_unit_id
        and mastery is not None
        and mastery.mastery_score < 0.40
        and streaks["recent_wrong"] >= 3
    ):
        return FALLBACK_ROUTE

    return REINFORCE_ROUTE


def determine_target_difficulty(db: Session, state: StudentState, current_problem: Problem) -> tuple[int, bool]:
    unit_key = current_problem.full_unit_id or current_problem.unit or ""
    streaks = recent_streaks(db, state.student_id, unit_key)
    correct_streak = streaks["correct_streak"]
    wrong_streak = streaks["wrong_streak"]

    if wrong_streak >= 3:
        return 1, True
    if wrong_streak >= 2:
        return max(1, current_problem.difficulty - 1), False
    if correct_streak >= 2:
        return min(3, current_problem.difficulty + 1), False
    return current_problem.difficulty, False


def _subject_for_unit(db: Session, unit: str) -> str:
    if not unit:
        return "math"
    dep = get_unit_dependency(db, unit)
    if dep is not None and getattr(dep, "subject", None):
        subj = (dep.subject or "math").strip().lower()
        if subj in ("english", "math"):
            return subj
    return "english" if unit.startswith("eng_") else "math"


def _pick_by_unit_and_difficulty(
    db: Session,
    unit: str,
    difficulty: int,
    excluded_problem_ids: set[int] | None = None,
) -> Problem | None:
    subject = _subject_for_unit(db, unit)
    stmt = (
        select(Problem)
        .where(
            Problem.full_unit_id == unit,
            Problem.subject == subject,
            Problem.difficulty == difficulty,
            Problem.difficulty < 5,
            Problem.status == 'approved',
        )
        .order_by(func.random())
    )
    problems = db.scalars(stmt).all()
    non_excluded = [p for p in problems if excluded_problem_ids is None or p.problem_id not in excluded_problem_ids]
    if non_excluded:
        return non_excluded[0]
    # 除外リストを無視して返すと同じ問題が出るため None を返す
    return None


def _pick_nearest_in_unit(
    db: Session,
    unit: str,
    desired_difficulty: int,
    excluded_problem_ids: set[int] | None = None,
) -> Problem | None:
    subject = _subject_for_unit(db, unit)
    for offset in range(0, 3):
        for candidate in {max(1, desired_difficulty - offset), min(3, desired_difficulty + offset)}:
            problem = _pick_by_unit_and_difficulty(db, unit, candidate, excluded_problem_ids)
            if problem is not None:
                return problem
    stmt = select(Problem).where(
        Problem.full_unit_id == unit,
        Problem.subject == subject,
        Problem.status == 'approved',
        Problem.difficulty < 5,
    ).order_by(func.random())
    problems = db.scalars(stmt).all()
    non_excluded = [p for p in problems if excluded_problem_ids is None or p.problem_id not in excluded_problem_ids]
    return non_excluded[0] if non_excluded else None


def _target_unit_for_route(db: Session, state: StudentState, current_problem: Problem, route: str) -> str:
    unit_key = current_problem.full_unit_id or current_problem.unit
    dependency = get_unit_dependency(db, unit_key)
    if route == ADVANCE_ROUTE and dependency and dependency.next_unit_id:
        return dependency.next_unit_id
    if route == FALLBACK_ROUTE and dependency and dependency.prerequisite_unit_id:
        return dependency.prerequisite_unit_id
    return unit_key or ""


def _target_level_for_route(db: Session, state: StudentState, current_problem: Problem, route: str) -> int:
    if route in {ADVANCE_ROUTE, FALLBACK_ROUTE}:
        return 1
    target_difficulty, _ = determine_target_difficulty(db, state, current_problem)
    return target_difficulty


def get_next_problem_candidate_ids(db: Session, state: StudentState, current_problem: Problem, limit: int = 3) -> list[int]:
    route = get_recommended_route(db, state, current_problem)
    target_unit = _target_unit_for_route(db, state, current_problem, route)
    target_level = _target_level_for_route(db, state, current_problem, route)
    excluded_ids = set(recent_problem_ids(db, state.student_id, limit=5))
    excluded_ids.add(current_problem.problem_id)
    target_subject = _subject_for_unit(db, target_unit)

    stmt = (
        select(Problem.problem_id)
        .where(
            Problem.full_unit_id == target_unit,
            Problem.subject == target_subject,
            Problem.difficulty == target_level,
            Problem.status == 'approved',
        )
        .order_by(Problem.problem_id.asc())
    )
    problem_ids = [problem_id for problem_id in db.scalars(stmt).all() if problem_id not in excluded_ids]
    if not problem_ids:
        fallback_stmt = (
            select(Problem.problem_id)
            .where(
                Problem.full_unit_id == target_unit,
                Problem.subject == target_subject,
                Problem.status == 'approved',
            )
            .order_by(Problem.difficulty.asc(), Problem.problem_id.asc())
        )
        problem_ids = list(db.scalars(fallback_stmt).all())
    return problem_ids[:limit]


def get_dominant_error_pattern(db: Session, student_id: int, unit: str, consecutive: int = 3) -> str | None:
    """直近ログで consecutive 回連続して同じ error_pattern が出ていたらそれを返す。"""
    stmt = (
        select(LearningLog.error_pattern)
        .where(LearningLog.student_id == student_id, LearningLog.error_pattern.isnot(None))
        .join(Problem, LearningLog.problem_id == Problem.problem_id)
        .where(
            or_(Problem.full_unit_id == unit, Problem.unit == unit),
            Problem.problem_type == "practice",
        )
        .order_by(desc(LearningLog.created_at))
        .limit(consecutive)
    )
    patterns = [p for p in db.scalars(stmt).all() if p]
    if len(patterns) < consecutive:
        return None
    first = patterns[0]
    return first if all(p == first for p in patterns) else None


def get_student_error_map(db: Session, student_id: int, limit: int = 20) -> dict[str, int]:
    """直近 limit 件の誤答ログから {error_pattern: count} を返す。"""
    stmt = (
        select(LearningLog.error_pattern)
        .where(LearningLog.student_id == student_id, LearningLog.error_pattern.isnot(None))
        .order_by(desc(LearningLog.created_at))
        .limit(limit)
    )
    counts: dict[str, int] = {}
    for p in db.scalars(stmt).all():
        if p:
            counts[p] = counts.get(p, 0) + 1
    return counts


def find_problem_for_error_pattern(
    db: Session,
    unit: str,
    difficulty: int,
    error_pattern: str,
    excluded_ids: set[int] | None = None,
) -> Problem | None:
    """error_pattern_candidates に error_pattern を含む approved 問題を返す。"""
    subject = _subject_for_unit(db, unit)
    stmt = (
        select(Problem)
        .where(
            Problem.full_unit_id == unit,
            Problem.subject == subject,
            Problem.difficulty == difficulty,
            Problem.status == 'approved',
            Problem.error_pattern_candidates.contains(error_pattern),
        )
        .order_by(Problem.problem_id.asc())
    )
    for problem in db.scalars(stmt).all():
        if excluded_ids is None or problem.problem_id not in excluded_ids:
            return problem
    return None


def choose_next_problem(db: Session, state: StudentState, current_problem: Problem) -> Problem | None:
    route = get_recommended_route(db, state, current_problem)
    target_unit = _target_unit_for_route(db, state, current_problem, route)
    target_level = _target_level_for_route(db, state, current_problem, route)
    # 直近5問 + 現在の問題 を除外リストに含める（同問題の再出題を防止）
    excluded_ids = set(recent_problem_ids(db, state.student_id, limit=5))
    excluded_ids.add(current_problem.problem_id)

    latest_history = recent_unit_history(
        db, state.student_id, current_problem.full_unit_id or current_problem.unit, limit=1
    )
    if route == REINFORCE_ROUTE and latest_history:
        latest_log, _ = latest_history[0]
        if latest_log.intervention_type in {RETRY_WITH_HINT, REINFORCE_SAME_PATTERN}:
            intervention_problem = choose_problem_for_intervention(
                db,
                state=state,
                current_problem=current_problem,
                intervention_type=latest_log.intervention_type,
            )
            # RETRY_WITH_HINT は同問題を返すが、同単元に別問題があれば差し替える
            if intervention_problem is not None and intervention_problem.problem_id != current_problem.problem_id:
                return intervention_problem
            if intervention_problem is not None and intervention_problem.problem_id == current_problem.problem_id:
                # 同問題介入 → excluded_ids から一時的に外して別問題を探す
                alt = _pick_nearest_in_unit(db, target_unit, target_level, excluded_ids)
                if alt is not None:
                    return alt
        explicit_next_id = current_problem.next_if_correct if latest_log.is_correct else current_problem.next_if_wrong
        if explicit_next_id:
            explicit_problem = db.get(Problem, explicit_next_id)
            if explicit_problem is not None and (
                explicit_problem.full_unit_id == target_unit or explicit_problem.unit == target_unit
            ) and explicit_problem.difficulty == target_level:
                return explicit_problem

    # error_pattern 3回連続 → そのパターンを含む問題を優先
    dominant_unit = current_problem.full_unit_id or current_problem.unit
    dominant = get_dominant_error_pattern(db, state.student_id, dominant_unit, consecutive=3)
    if dominant:
        pattern_problem = find_problem_for_error_pattern(db, target_unit, target_level, dominant, excluded_ids)
        if pattern_problem is not None:
            return pattern_problem

    candidate = _pick_nearest_in_unit(db, target_unit, target_level, excluded_ids)
    # 万が一同問題が返ってきた場合の最終防衛: excluded_ids を広げて再試行
    if candidate is not None and candidate.problem_id == current_problem.problem_id:
        broader_excluded = excluded_ids | {current_problem.problem_id}
        candidate = _pick_nearest_in_unit(db, target_unit, target_level, broader_excluded)
    return candidate
