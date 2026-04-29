"""REST API for the React student frontend (Phase 3)."""

import logging
from datetime import datetime
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Classroom, LearningLog, Student, StudentBoardCell, StudentState
from ..services.auth_service import (
    login_student_session,
    read_session,
)
from ..services.grading_service import grade_answer_detailed
from ..services.problem_service import (
    get_problem_by_id,
    get_unit_label_map,
    consume_teacher_override_problem,
    get_first_problem,
    get_first_problem_for_unit,
)
from ..services.routing_service import choose_next_problem
from ..services.state_service import ensure_student_state
from ..services.review_service import update_review_schedule

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/students", tags=["api-students"])
auth_router = APIRouter(prefix="/api/v1/auth", tags=["api-auth"])


# ─── auth endpoints ───────────────────────────────────────────────────────────

class ClassroomLoginPayload(BaseModel):
    classroom_code: str
    student_id: int | None = None


@auth_router.post("/classroom-students")
def api_get_classroom_students(
    payload: ClassroomLoginPayload,
    response: Response,
    db: Session = Depends(get_db),
):
    """Get students in classroom by code (first step of login)."""
    from ..services.classroom_ops_service import normalize_classroom_code
    code = normalize_classroom_code(payload.classroom_code)
    classroom = db.scalar(select(Classroom).where(func.upper(Classroom.code) == code))
    if classroom is None:
        raise HTTPException(status_code=401, detail="教室コードが正しくありません")
    students = db.scalars(
        select(Student).where(
            Student.classroom_id == classroom.classroom_id,
            Student.is_active == True,
        )
    ).all()
    return {
        "classroom_id": classroom.classroom_id,
        "classroom_name": classroom.classroom_name,
        "students": [{"student_id": s.student_id, "display_name": s.display_name, "grade": s.grade} for s in students],
    }


class StudentLoginPayload(BaseModel):
    student_id: int
    pin: str


@auth_router.post("/student-login")
def api_student_login(
    payload: StudentLoginPayload,
    response: Response,
    db: Session = Depends(get_db),
):
    """Authenticate a student with PIN."""
    import hashlib, hmac
    from ..services.auth_service import SESSION_COOKIE_NAME
    student = db.get(Student, payload.student_id)
    if student is None:
        raise HTTPException(status_code=401, detail="生徒が見つかりません")
    if student.login_pin_hash and payload.pin:
        pin_hash = hashlib.sha256(payload.pin.encode()).hexdigest()
        if not hmac.compare_digest(student.login_pin_hash, pin_hash):
            raise HTTPException(status_code=401, detail="PINが正しくありません")
    login_student_session(response, student)
    return {
        "student_id": student.student_id,
        "display_name": student.display_name,
        "grade": student.grade,
    }


@auth_router.get("/me")
def api_me(request: Request, db: Session = Depends(get_db)):
    """Return current session info."""
    session = read_session(request)
    role = session.get("role")
    if not role:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"role": role, "student_id": session.get("student_id"), "classroom_id": session.get("classroom_id")}


# ─── helpers ──────────────────────────────────────────────────────────────────

def _require_student(request: Request, student_id: int, db: Session) -> Student:
    session = read_session(request)
    if session.get("role") not in ("student", "classroom", "teacher", "owner"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    if session.get("role") == "student" and session.get("student_id") != student_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


def _problem_to_dict(problem) -> dict:
    import json
    return {
        "problem_id": problem.problem_id,
        "question_text": problem.question_text,
        "answer_type": problem.answer_type,
        "difficulty": problem.difficulty,
        "subject": problem.subject,
        "unit": problem.full_unit_id or problem.unit,
        "choices": json.loads(problem.choices) if getattr(problem, "choices", None) else None,
        "correct_answer": problem.correct_answer,
    }


def _state_to_dict(state: StudentState) -> dict:
    return {
        "current_unit": state.current_unit,
        "current_level": state.current_level,
        "mastery_score": round(state.mastery_score, 2),
        "gold": state.gold or 0,
        "login_streak": getattr(state, "login_streak", 0) or 0,
        "total_xp": getattr(state, "total_xp", 0) or 0,
        "last_activity_date": getattr(state, "last_activity_date", None),
    }


# ─── endpoints ────────────────────────────────────────────────────────────────

@router.get("/{student_id}/home")
def api_student_home(request: Request, student_id: int, db: Session = Depends(get_db)):
    """Return current question + student state for the React UI."""
    student = _require_student(request, student_id, db)
    state = db.get(StudentState, student_id)
    if state is None:
        raise HTTPException(status_code=404, detail="State not found")

    # 教師overrideチェック
    override = consume_teacher_override_problem(db, state)
    if override is not None:
        state.current_unit = override.full_unit_id or override.unit
        db.commit()
        db.refresh(state)
        problem = override
    elif state.last_problem_id:
        last = get_problem_by_id(db, state.last_problem_id)
        recent_log = db.scalar(
            select(LearningLog)
            .where(LearningLog.student_id == student_id, LearningLog.problem_id == state.last_problem_id)
            .order_by(desc(LearningLog.created_at)).limit(1)
        )
        if last and recent_log:
            problem = choose_next_problem(db, state, last) or get_first_problem_for_unit(db, state.current_unit) or get_first_problem(db)
        else:
            problem = last or get_first_problem_for_unit(db, state.current_unit) or get_first_problem(db)
    else:
        problem = get_first_problem_for_unit(db, state.current_unit) if state.current_unit else None
        if problem is None and state.current_unit:
            from ..models import Problem as ProblemModel
            problem = db.scalar(
                select(ProblemModel)
                .where(ProblemModel.unit == state.current_unit, ProblemModel.status == "approved", ProblemModel.difficulty < 5)
                .order_by(ProblemModel.difficulty.asc(), ProblemModel.problem_id.asc())
            )
        if problem is None:
            problem = get_first_problem(db)
    if problem is None:
        raise HTTPException(status_code=404, detail="No problem available")

    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    today_logs = db.scalars(
        select(LearningLog).where(
            LearningLog.student_id == student_id,
            LearningLog.created_at >= datetime.strptime(today_str, "%Y-%m-%d"),
        )
    ).all()

    unit_labels = get_unit_label_map(db)
    classroom = db.get(Classroom, student.classroom_id)

    return {
        "student": {
            "student_id": student.student_id,
            "display_name": student.display_name,
            "grade": student.grade,
            "classroom_name": classroom.classroom_name if classroom else None,
        },
        "state": _state_to_dict(state),
        "problem": _problem_to_dict(problem),
        "unit_label": unit_labels.get(problem.full_unit_id or problem.unit, problem.full_unit_id or problem.unit),
        "today_answer_count": len(today_logs),
        "quest_goal": 10,
    }


class SubmitPayload(BaseModel):
    problem_id: int
    answer: str
    hint_used: int = 0
    elapsed_sec: int = 0


@router.post("/{student_id}/submit")
def api_student_submit(
    request: Request,
    student_id: int,
    payload: SubmitPayload,
    db: Session = Depends(get_db),
):
    """Process an answer and return the result."""
    student = _require_student(request, student_id, db)
    state = db.get(StudentState, student_id)
    if state is None:
        raise HTTPException(status_code=404, detail="State not found")

    problem = get_problem_by_id(db, payload.problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    hint_used = max(0, min(2, payload.hint_used))
    grading_result = grade_answer_detailed(problem, payload.answer)
    is_correct = grading_result["judgment"] == "correct"

    # ── Log ──
    log = LearningLog(
        student_id=student_id,
        problem_id=problem.problem_id,
        answer_payload=payload.answer,
        is_correct=is_correct,
        elapsed_sec=payload.elapsed_sec,
        attempt_count=1,
        hint_used=hint_used,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    # ── Gold ──
    g_earned = (8 if hint_used == 0 else 5) if is_correct else 0
    recent_logs = db.scalars(
        select(LearningLog)
        .where(LearningLog.student_id == student_id)
        .order_by(desc(LearningLog.created_at))
        .limit(5)
    ).all()
    consecutive = sum(1 for _ in (l for l in recent_logs if l.is_correct))
    ai_event_text = None
    if consecutive >= 3 and is_correct:
        ai_event_text = f"🔥 {consecutive}問連続正解！ボーナス +10G"
        g_earned += 10
    state.gold = (state.gold or 0) + g_earned

    # ── Streak & XP ──
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    last_date = getattr(state, "last_activity_date", None)
    if last_date != today_str:
        if last_date is None or (datetime.strptime(today_str, "%Y-%m-%d") - datetime.strptime(last_date, "%Y-%m-%d")).days == 1:
            state.login_streak = (state.login_streak or 0) + 1
        else:
            state.login_streak = 1
        state.last_activity_date = today_str
    xp_earned = 10 if is_correct and hint_used == 0 else 5 if is_correct else 1
    state.total_xp = (state.total_xp or 0) + xp_earned

    # ── Board cell ──
    cell_count = db.execute(
        select(StudentBoardCell).where(
            StudentBoardCell.student_id == student_id,
            StudentBoardCell.unit_id == (problem.full_unit_id or problem.unit),
        )
    ).unique().all()
    cell_type = "bonus" if ai_event_text else ("correct" if is_correct else ("hint" if hint_used >= 1 else "wrong"))
    board_cell = StudentBoardCell(
        student_id=student_id,
        unit_id=problem.full_unit_id or problem.unit,
        cell_index=len(cell_count),
        problem_id=problem.problem_id,
        is_correct=is_correct,
        hint_used=hint_used,
        cell_type=cell_type,
        ai_event_text=ai_event_text,
        g_earned=g_earned,
        created_at=datetime.utcnow().isoformat(),
    )
    db.add(board_cell)

    # ── Next problem ──
    next_problem = choose_next_problem(db, state, problem)
    update_review_schedule(db, student_id, problem, is_correct, hint_used, payload.elapsed_sec)
    db.add(state)
    db.commit()

    return {
        "is_correct": is_correct,
        "correct_answer": problem.correct_answer,
        "explanation": problem.explanation_base or "",
        "g_earned": g_earned,
        "xp_earned": xp_earned,
        "ai_event_text": ai_event_text,
        "new_streak": getattr(state, "login_streak", 0),
        "new_total_xp": getattr(state, "total_xp", 0),
        "new_gold": state.gold,
        "next_problem_id": next_problem.problem_id if next_problem else None,
    }


@router.get("/{student_id}/hint/{problem_id}")
def api_student_hint(
    request: Request,
    student_id: int,
    problem_id: int,
    step: int = 1,
    db: Session = Depends(get_db),
):
    """Return hint for a problem. step=1 → hint_1, step=2 → hint_2."""
    _require_student(request, student_id, db)
    problem = get_problem_by_id(db, problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    hint = None
    if step <= 1:
        hint = getattr(problem, "hint_1", None) or getattr(problem, "hint_text", None)
    else:
        hint = getattr(problem, "hint_2", None) or getattr(problem, "hint_1", None) or getattr(problem, "hint_text", None)

    if not hint:
        from ..services.ai_service import generate_text, ai_conversation_enabled
        if ai_conversation_enabled():
            hint = generate_text(
                system_prompt="あなたは中学生向けの数学・英語の先生です。答えは言わずヒントだけを1文で返してください。",
                user_prompt=f"問題: {problem.question_text}\n正解: {problem.correct_answer}\nヒント(step {step})を1文で:",
                max_output_tokens=80,
            )
            if hint and step <= 1 and not getattr(problem, "hint_1", None):
                from ..models import Problem as ProblemModel
                db.execute(
                    ProblemModel.__table__.update()
                    .where(ProblemModel.problem_id == problem_id)
                    .values(hint_1=hint)
                )
                db.commit()

    return {
        "problem_id": problem_id,
        "step": step,
        "hint": hint or "ヒントはありません。もう一度問題文をよく読んでみましょう。",
        "has_next": step < 2 and bool(getattr(problem, "hint_2", None)),
    }


@router.get("/{student_id}/ranking")
def api_student_ranking(request: Request, student_id: int, db: Session = Depends(get_db)):
    """Return class ranking."""
    student = _require_student(request, student_id, db)
    week_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = week_start.replace(day=week_start.day - week_start.weekday())

    classroom_id = student.classroom_id
    classmates = db.scalars(
        select(Student).where(Student.classroom_id == classroom_id, Student.is_active == True)
    ).all() if classroom_id else [student]

    rows = []
    for s in classmates:
        logs = db.scalars(
            select(LearningLog).where(LearningLog.student_id == s.student_id, LearningLog.created_at >= week_start)
        ).all()
        st = db.get(StudentState, s.student_id)
        rows.append({
            "student_id": s.student_id,
            "display_name": s.display_name,
            "week_xp": sum(10 if l.is_correct else 1 for l in logs),
            "week_correct": sum(1 for l in logs if l.is_correct),
            "streak": getattr(st, "login_streak", 0) if st else 0,
            "total_xp": getattr(st, "total_xp", 0) if st else 0,
            "is_me": s.student_id == student_id,
        })

    rows.sort(key=lambda r: r["week_xp"], reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1

    return {"ranking": rows, "week_start": week_start.strftime("%m/%d")}
