"""Listening adaptive routing, mastery, and problem selection."""

import random
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Classroom, ListeningLog, ListeningMastery, ListeningProblem, Student, StudentState
from .listening_error_service import classify_listening_error, refine_question_misread
from .state_service import effective_unit_unlock

LISTENING_TYPES_ALLOWED = frozenset({
    "word_discrimination",
    "short_sentence",
    "dialog_response",
    "info_capture",
    "dialog_comprehension",
})

LISTENING_UNIT_ROWS = [
    ('lis_g7_alphabet', 'アルファベット・音', 7),
    ('lis_g7_greetings', 'あいさつ表現', 7),
    ('lis_g7_numbers', '数字・曜日・月', 7),
    ('lis_g7_be_verb', 'be 動詞文', 7),
    ('lis_g7_general_verb', '一般動詞文', 7),
    ('lis_g7_question', '疑問文と応答', 7),
    ('lis_g8_past_tense', '過去形', 8),
    ('lis_g8_auxiliary', '助動詞', 8),
    ('lis_g8_comparison', '比較表現', 8),
    ('lis_g8_directions', '道案内', 8),
    ('lis_g8_daily_life', '日常会話', 8),
    ('lis_g9_present_perfect', '現在完了', 9),
    ('lis_g9_passive', '受け身', 9),
    ('lis_g9_infinitive', '不定詞・動名詞', 9),
    ('lis_g9_relative', '関係代名詞入り短文', 9),
    ('lis_g9_speech', '短いスピーチ・説明文', 9),
]

UNIT_DISPLAY = {u[0]: u[1] for u in LISTENING_UNIT_ROWS}



def units_for_grade(grade_band: int):
    return [u for u in LISTENING_UNIT_ROWS if u[2] == grade_band]


def unit_index(full_unit_id: str):
    for i, u in enumerate(LISTENING_UNIT_ROWS):
        if u[0] == full_unit_id:
            return i
    return None


def prev_full_unit(full_unit_id: str):
    idx = unit_index(full_unit_id)
    if idx is None or idx <= 0:
        return None
    g = LISTENING_UNIT_ROWS[idx][2]
    for j in range(idx - 1, -1, -1):
        if LISTENING_UNIT_ROWS[j][2] == g:
            return LISTENING_UNIT_ROWS[j][0]
    return None


def next_full_unit(full_unit_id: str):
    idx = unit_index(full_unit_id)
    if idx is None or idx >= len(LISTENING_UNIT_ROWS) - 1:
        return None
    g = LISTENING_UNIT_ROWS[idx][2]
    for j in range(idx + 1, len(LISTENING_UNIT_ROWS)):
        if LISTENING_UNIT_ROWS[j][2] == g:
            return LISTENING_UNIT_ROWS[j][0]
    return None


def is_listening_unit_unlocked(db: Session, student: Student, classroom, full_unit_id: str) -> bool:
    if classroom is None:
        return True
    st = db.get(StudentState, student.student_id)
    mode, up_to_val = effective_unit_unlock(classroom, st)
    if mode == "full":
        return True
    idx = unit_index(full_unit_id)
    if idx is None:
        return False
    grade = LISTENING_UNIT_ROWS[idx][2]
    chain = [u[0] for u in LISTENING_UNIT_ROWS if u[2] == grade]
    if full_unit_id not in chain:
        return False
    pos = chain.index(full_unit_id)
    if pos == 0:
        return True
    prev_id = chain[pos - 1]
    if mode == "up_to" and up_to_val:
        up_to = up_to_val
        try:
            cap = chain.index(up_to)
        except ValueError:
            cap = len(chain) - 1
        if pos > cap:
            return False
    m = _get_mastery_row(db, student.student_id, prev_id)
    return m is not None and m.mastery_score >= 0.40


def count_problems_in_unit(db: Session, full_unit_id: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(ListeningProblem)
            .where(
                ListeningProblem.full_unit_id == full_unit_id,
                ListeningProblem.problem_type == "practice",
                ListeningProblem.status.in_(["approved", "pending"]),
            )
        )
        or 0
    )


def _get_mastery_row(db: Session, student_id: int, full_unit_id: str):
    return db.scalar(
        select(ListeningMastery).where(
            ListeningMastery.student_id == student_id,
            ListeningMastery.full_unit_id == full_unit_id,
        )
    )


def get_or_create_mastery(db: Session, student: Student, full_unit_id: str) -> ListeningMastery:
    row = _get_mastery_row(db, student.student_id, full_unit_id)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cid = student.classroom_id or 0
    if row is None:
        row = ListeningMastery(
            student_id=student.student_id,
            classroom_id=cid,
            full_unit_id=full_unit_id,
            mastery_score=0.0,
            correct_count=0,
            wrong_count=0,
            hint_count=0,
            avg_play_count=1.0,
            avg_elapsed_sec=None,
            updated_at=now,
        )
        db.add(row)
        db.flush()
    return row


def last_logs_for_unit(db: Session, student_id: int, full_unit_id: str, n: int = 10):
    return (
        db.scalars(
            select(ListeningLog)
            .join(ListeningProblem, ListeningLog.problem_id == ListeningProblem.id)
            .where(ListeningLog.student_id == student_id, ListeningProblem.full_unit_id == full_unit_id)
            .order_by(ListeningLog.id.desc())
            .limit(n)
        ).all()
    )


def streaks_from_logs(logs):
    c_ok, c_bad = 0, 0
    for log in logs:
        if log.is_correct:
            if c_bad:
                break
            c_ok += 1
        else:
            if c_ok:
                break
            c_bad += 1
    return c_ok, c_bad


def last_logs_global(db: Session, student_id: int, n: int = 15):
    return db.scalars(select(ListeningLog).where(ListeningLog.student_id == student_id).order_by(ListeningLog.id.desc()).limit(n)).all()


def count_fallback_routes_recent(db: Session, student_id: int, n: int = 12) -> int:
    logs = last_logs_global(db, student_id, n)
    return sum(1 for x in logs if (x.route or "") == "fallback_prerequisite_unit")


def same_error_pattern_streak(logs, pattern: str) -> int:
    if not pattern:
        return 0
    n = 0
    for log in logs:
        if (log.error_pattern or "") != pattern:
            break
        if log.is_correct:
            break
        n += 1
    return n


def select_intervention(
    error_pattern: str,
    problem: ListeningProblem,
    hint_used: int,
    play_count: int,
    play_limit: int,
    vocab_gap_streak: int,
    grammar_gap_streak: int,
    fallback_count_recent: int,
    same_err_streak: int,
) -> str:
    if fallback_count_recent >= 2 or same_err_streak >= 3:
        return "teacher_intervention_needed"
    if error_pattern == "sound_discrimination_error" and (problem.audio_speed or "") == "normal":
        return "retry_with_slower_audio"
    if error_pattern == "vocabulary_listening_gap" and hint_used == 0:
        return "retry_with_keyword_hint"
    if error_pattern == "vocabulary_listening_gap" and vocab_gap_streak >= 2:
        return "fallback_vocab_review"
    if error_pattern == "grammar_listening_gap" and grammar_gap_streak >= 2:
        return "fallback_basic_sentence"
    if error_pattern == "meaning_capture_error":
        return "explain_differently"
    if error_pattern == "attention_loss":
        return "slow_down_and_replay"
    if play_limit > 0 and play_count >= play_limit and not error_pattern:
        return "slow_down_and_replay"
    return "monitor_only"


def decide_route(mastery: ListeningMastery, logs_unit, streak_wrong: int, streak_correct: int) -> str:
    last3_ok = len(logs_unit) >= 3 and all(x.is_correct for x in logs_unit[:3])
    if mastery.mastery_score >= 0.55 and mastery.correct_count >= 3 and last3_ok:
        return "advance_next_unit"
    if mastery.mastery_score < 0.40 and streak_wrong >= 3:
        return "fallback_prerequisite_unit"
    return "reinforce_current_unit"


def target_difficulty_and_speed(last_problem, streak_wrong: int, streak_correct: int):
    base = last_problem.difficulty if last_problem else 1
    if streak_wrong >= 3:
        return 1, "slow"
    if streak_wrong >= 2:
        return max(1, base - 1), None
    if streak_correct >= 2:
        return min(3, base + 1), None
    return base, None


def pick_problem(db: Session, full_unit_id: str, listening_type: str, target_difficulty: int, prefer_speed, exclude_ids=None):
    exclude_ids = exclude_ids or set()
    stmt = (
        select(ListeningProblem)
        .where(
            ListeningProblem.full_unit_id == full_unit_id,
            ListeningProblem.listening_type == listening_type,
            ListeningProblem.problem_type == "practice",
            ListeningProblem.status.in_(["approved", "pending"]),
        )
        .order_by(func.abs(ListeningProblem.difficulty - target_difficulty), ListeningProblem.id.asc())
    )
    candidates = [p for p in db.scalars(stmt).all() if p.id not in exclude_ids]
    if not candidates:
        stmt2 = (
            select(ListeningProblem)
            .where(
                ListeningProblem.full_unit_id == full_unit_id,
                ListeningProblem.problem_type == "practice",
                ListeningProblem.status.in_(["approved", "pending"]),
            )
            .order_by(func.abs(ListeningProblem.difficulty - target_difficulty), ListeningProblem.id.asc())
        )
        candidates = [p for p in db.scalars(stmt2).all() if p.id not in exclude_ids]
    if prefer_speed == "slow":
        slow = [p for p in candidates if (p.audio_speed or "") == "slow"]
        if slow:
            candidates = slow
    if candidates:
        return random.choice(candidates)
    return None


def pick_first_for_unit(db: Session, full_unit_id: str, listening_type=None):
    stmt = select(ListeningProblem).where(
        ListeningProblem.full_unit_id == full_unit_id,
        ListeningProblem.problem_type == "practice",
        ListeningProblem.status.in_(["approved", "pending"]),
    )
    if listening_type:
        stmt = stmt.where(ListeningProblem.listening_type == listening_type)
    stmt = stmt.order_by(ListeningProblem.difficulty.asc(), ListeningProblem.id.asc())
    return db.scalar(stmt.limit(1))


def get_next_problem_for_context(db: Session, student: Student, classroom, full_unit_id: str, current_problem, route: str):
    logs_unit = last_logs_for_unit(db, student.student_id, full_unit_id, 20)
    streak_ok, streak_bad = streaks_from_logs(logs_unit)
    tgt_d, pref_speed = target_difficulty_and_speed(current_problem, streak_bad, streak_ok)
    lt = current_problem.listening_type if current_problem else "word_discrimination"
    ex = {current_problem.id} if current_problem else set()

    if route == "advance_next_unit":
        nxt = next_full_unit(full_unit_id)
        if not nxt:
            return None
        if not is_listening_unit_unlocked(db, student, classroom, nxt):
            return pick_problem(db, full_unit_id, lt, tgt_d, pref_speed, ex)
        p = pick_first_for_unit(db, nxt)
        if p:
            return p
        return None

    if route == "fallback_prerequisite_unit":
        prev = prev_full_unit(full_unit_id)
        target_unit = prev or full_unit_id
        p = pick_problem(db, target_unit, "word_discrimination", 1, "slow", set())
        if p:
            return p
        return pick_first_for_unit(db, target_unit)

    return pick_problem(db, full_unit_id, lt, tgt_d, pref_speed, ex)


def update_mastery_after_answer(db: Session, mastery: ListeningMastery, is_correct: bool, hint_used: int, play_count: int, elapsed_sec):
    if is_correct:
        mastery.correct_count += 1
    else:
        mastery.wrong_count += 1
    if hint_used:
        mastery.hint_count += 1
    total = mastery.correct_count + mastery.wrong_count
    mastery.mastery_score = mastery.correct_count / total if total else 0.0
    n = total
    mastery.avg_play_count = ((mastery.avg_play_count * (n - 1)) + play_count) / n if n else float(play_count)
    if elapsed_sec is not None:
        if mastery.avg_elapsed_sec is None:
            mastery.avg_elapsed_sec = float(elapsed_sec)
        else:
            mastery.avg_elapsed_sec = (mastery.avg_elapsed_sec * (n - 1) + elapsed_sec) / n
    mastery.updated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db.add(mastery)



def build_listening_mastery_rows(db: Session, student_id: int, grade: int):
    rows = []
    for uid, label, g in LISTENING_UNIT_ROWS:
        if g != grade:
            continue
        m = _get_mastery_row(db, student_id, uid)
        rows.append({
            "full_unit_id": uid,
            "display_name": label,
            "mastery_score": m.mastery_score if m else 0.0,
            "correct_count": m.correct_count if m else 0,
            "wrong_count": m.wrong_count if m else 0,
            "problem_total": count_problems_in_unit(db, uid),
        })
    return rows


def listening_home_units(db: Session, student: Student, classroom, grade_tab: int):
    out = []
    for uid, label, g in LISTENING_UNIT_ROWS:
        if g != grade_tab:
            continue
        unlocked = is_listening_unit_unlocked(db, student, classroom, uid)
        m = _get_mastery_row(db, student.student_id, uid)
        total = count_problems_in_unit(db, uid)
        out.append({
            "full_unit_id": uid,
            "display_name": label,
            "grade_band": g,
            "unlocked": unlocked,
            "mastery_score": round((m.mastery_score if m else 0.0) * 100),
            "mastery_float": m.mastery_score if m else 0.0,
            "correct_count": m.correct_count if m else 0,
            "problem_total": total,
        })
    return out


def submit_listening_answer(
    db: Session,
    student: Student,
    problem_id: str,
    selected_answer: str,
    play_count: int,
    elapsed_sec,
    hint_used: int,
):
    problem = db.get(ListeningProblem, problem_id)
    if problem is None:
        return None
    classroom_id = student.classroom_id or 0
    is_correct = selected_answer.strip() == problem.correct_answer.strip()
    err = classify_listening_error(
        db, student.student_id, problem, selected_answer, is_correct, hint_used, play_count, problem.play_limit
    )
    if err:
        err = refine_question_misread(db, student.student_id, err)

    gl = last_logs_global(db, student.student_id, 8)
    vocab_streak = same_error_pattern_streak(gl, "vocabulary_listening_gap")
    grammar_streak = same_error_pattern_streak(gl, "grammar_listening_gap")
    fb_count = count_fallback_routes_recent(db, student.student_id, 12)
    same_err = same_error_pattern_streak(gl, err) if err else 0

    intervention = select_intervention(
        err,
        problem,
        hint_used,
        play_count,
        problem.play_limit,
        vocab_streak,
        grammar_streak,
        fb_count,
        same_err,
    )

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    log_row = ListeningLog(
        student_id=student.student_id,
        classroom_id=classroom_id,
        problem_id=problem_id,
        is_correct=1 if is_correct else 0,
        selected_answer=selected_answer,
        play_count=play_count,
        elapsed_sec=elapsed_sec,
        hint_used=hint_used,
        error_pattern=err or None,
        intervention_type=intervention,
        route=None,
        created_at=now,
    )
    db.add(log_row)
    db.flush()

    mastery = get_or_create_mastery(db, student, problem.full_unit_id)
    update_mastery_after_answer(db, mastery, is_correct, hint_used, play_count, elapsed_sec)
    db.flush()

    logs_unit = last_logs_for_unit(db, student.student_id, problem.full_unit_id, 10)
    streak_ok, streak_bad = streaks_from_logs(logs_unit)
    route = decide_route(mastery, logs_unit, streak_bad, streak_ok)
    log_row.route = route
    db.add(log_row)
    db.flush()

    classroom = db.get(Classroom, student.classroom_id) if student.classroom_id else None
    next_p = get_next_problem_for_context(db, student, classroom, problem.full_unit_id, problem, route)
    db.commit()
    db.refresh(log_row)
    db.refresh(mastery)

    return {
        "is_correct": is_correct,
        "correct_answer": problem.correct_answer,
        "explanation": problem.explanation_base,
        "error_pattern": err or None,
        "intervention_type": intervention,
        "route": route,
        "next_problem_id": next_p.id if next_p else None,
        "mastery_score": mastery.mastery_score,
        "log_id": log_row.id,
    }


def build_listening_stats(db: Session, classroom_id: int) -> dict:
    now = datetime.now()
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    ws = week_start.strftime("%Y-%m-%d")

    logs = (
        db.query(ListeningLog, ListeningProblem)
        .join(ListeningProblem, ListeningLog.problem_id == ListeningProblem.id)
        .filter(ListeningLog.classroom_id == classroom_id)
        .filter(ListeningLog.created_at >= ws)
        .all()
    )
    if not logs:
        return {
            "attempts_week": 0,
            "accuracy_week": None,
            "weak_units_top3": [],
            "replay_limit_rate": None,
            "teacher_flag_students": [],
        }

    attempts = len(logs)
    acc = sum(1 for L, _ in logs if L.is_correct) / attempts
    unit_stats = {}
    for L, P in logs:
        uid = P.full_unit_id
        if uid not in unit_stats:
            unit_stats[uid] = {"n": 0, "ok": 0}
        unit_stats[uid]["n"] += 1
        if L.is_correct:
            unit_stats[uid]["ok"] += 1
    weak = sorted(
        ((u, v["ok"] / v["n"] if v["n"] else 0, v["n"]) for u, v in unit_stats.items()),
        key=lambda x: x[1],
    )[:3]
    weak_units = [{"full_unit_id": u, "display_name": UNIT_DISPLAY.get(u, u), "accuracy": r, "n": n} for u, r, n in weak]

    lim_hits = 0
    lim_total = 0
    for L, P in logs:
        pl = P.play_limit or 0
        if pl > 0:
            lim_total += 1
            if L.play_count >= pl:
                lim_hits += 1
    rlr = (lim_hits / lim_total) if lim_total else None

    t_rows = (
        db.query(ListeningLog.student_id)
        .filter(ListeningLog.classroom_id == classroom_id)
        .filter(ListeningLog.intervention_type == "teacher_intervention_needed")
        .distinct()
        .all()
    )
    students_flagged = [r[0] for r in t_rows]

    return {
        "attempts_week": attempts,
        "accuracy_week": acc,
        "weak_units_top3": weak_units,
        "replay_limit_rate": rlr,
        "teacher_flag_students": students_flagged,
    }

UNIT_PRIMARY_LISTENING_TYPE = {
    "lis_g7_alphabet": "word_discrimination",
    "lis_g7_greetings": "dialog_response",
    "lis_g7_numbers": "info_capture",
    "lis_g7_be_verb": "short_sentence",
    "lis_g7_general_verb": "short_sentence",
    "lis_g7_question": "dialog_response",
    "lis_g8_past_tense": "short_sentence",
    "lis_g8_auxiliary": "dialog_response",
    "lis_g8_comparison": "short_sentence",
    "lis_g8_directions": "info_capture",
    "lis_g8_daily_life": "dialog_comprehension",
    "lis_g9_present_perfect": "dialog_comprehension",
    "lis_g9_passive": "short_sentence",
    "lis_g9_infinitive": "short_sentence",
    "lis_g9_relative": "short_sentence",
    "lis_g9_speech": "dialog_comprehension",
}


def resolve_practice_problem(db: Session, student: Student, classroom, full_unit_id: str, explicit_problem_id: str | None = None):
    if not is_listening_unit_unlocked(db, student, classroom, full_unit_id):
        return None
    if explicit_problem_id:
        p = db.get(ListeningProblem, explicit_problem_id)
        if p is None or p.full_unit_id != full_unit_id:
            return None
        if p.status not in ("approved", "pending"):
            return None
        return p
    lt = UNIT_PRIMARY_LISTENING_TYPE.get(full_unit_id, "word_discrimination")
    logs_unit = last_logs_for_unit(db, student.student_id, full_unit_id, 10)
    last = None
    if logs_unit:
        last = db.get(ListeningProblem, logs_unit[0].problem_id)
    streak_ok, streak_bad = streaks_from_logs(logs_unit)
    tgt_d, pref_speed = target_difficulty_and_speed(last, streak_bad, streak_ok)
    ex = set()
    return pick_problem(db, full_unit_id, lt, tgt_d, pref_speed, ex)
