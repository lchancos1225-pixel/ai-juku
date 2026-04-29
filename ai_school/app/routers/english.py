"""English subject router - /students/{student_id}/english"""
from datetime import datetime
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Classroom, LearningLog, Student, UnitDependency, UnitMastery
from ..schemas import SynonymMapRequest, SynonymMapResponse
from ..services.auth_service import ensure_session_classroom_access, read_session, require_student_login
from ..services.review_service import count_due_reviews
from ..services.test_service import should_trigger_test, scope_label as test_scope_label
from .flashcard import count_due_flashcards
from ..services.diagram_display_name_service import get_diagram_display_info
from ..services.diagram_service import render_problem_diagram_for_route
from ..services.problem_service import (
    get_first_problem_for_unit,
    get_problem_by_id,
    get_unit_label_map,
)
from ..services.routing_service import choose_next_problem
from ..services.state_service import effective_unit_unlock, ensure_student_state
from ..services.grading_service import generate_synonym_comparison_map
from . import student as _student_router

router = APIRouter(prefix="/students", tags=["english"])


def _templates():
    """student.py の templates インスタンス（render_math_text / from_json フィルター登録済み）を共有"""
    return _student_router.templates


def _ensure_student_classroom_access(request: Request, student: Student) -> None:
    session = read_session(request)
    ensure_session_classroom_access(session, student.classroom_id)


@router.get("/{student_id}/english", response_class=HTMLResponse)
def english_home(request: Request, student_id: int, db: Session = Depends(get_db)):
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth

    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)

    classroom = db.get(Classroom, student.classroom_id) if student.classroom_id else None
    state = ensure_student_state(db, student)
    unlock_mode, _ = effective_unit_unlock(classroom, state)

    eng_units = db.scalars(
        select(UnitDependency)
        .where(UnitDependency.subject == "english")
        .order_by(UnitDependency.display_order.asc())
    ).all()

    grade_groups: dict[int, list] = {}
    for u in eng_units:
        mastery = db.get(UnitMastery, (student_id, u.unit_id))
        pre_mastery = db.get(UnitMastery, (student_id, u.prerequisite_unit_id)) if u.prerequisite_unit_id else None

        if unlock_mode == "full":
            unlocked = True
        else:
            unlocked = (
                u.prerequisite_unit_id is None
                or (pre_mastery is not None and pre_mastery.mastery_score >= 0.40)
            )

        mastery_score = round((mastery.mastery_score if mastery else 0.0) * 100)
        correct_count = mastery.correct_count if mastery else 0
        wrong_count = mastery.wrong_count if mastery else 0

        row = {
            "unit_id": u.unit_id,
            "display_name": u.display_name,
            "intro_html": u.intro_html,
            "unlocked": unlocked,
            "grade": u.grade if u.grade else 7,
            "mastery_score": mastery_score,
            "correct_count": correct_count,
            "wrong_count": wrong_count,
            "status": (
                "mastered" if mastery and mastery.mastery_score >= 0.55
                else "in_progress" if mastery and (correct_count + wrong_count) > 0
                else "not_started"
            ),
        }
        grade_groups.setdefault(row["grade"], []).append(row)

    current_eng_unit = state.current_unit if state.current_unit and state.current_unit.startswith("eng_") else None

    current_unit_row = None
    if current_eng_unit:
        cud = db.get(UnitDependency, current_eng_unit)
        if cud:
            cm = db.get(UnitMastery, (student_id, current_eng_unit))
            current_unit_row = {
                "unit_id": cud.unit_id,
                "display_name": cud.display_name,
                "grade": cud.grade or 7,
                "mastery_score": round((cm.mastery_score if cm else 0.0) * 100),
            }

    unit_labels = get_unit_label_map(db)
    return _templates().TemplateResponse(
        "student_english_home.html",
        {
            "request": request,
            "student": student,
            "state": state,
            "grade_groups": grade_groups,
            "current_unit_row": current_unit_row,
            "unit_labels": unit_labels,
            "classroom_name": classroom.classroom_name if classroom else None,
            "is_student_view": True,
        },
    )


@router.post("/{student_id}/english/switch_unit", response_class=HTMLResponse)
def english_switch_unit(
    request: Request,
    student_id: int,
    unit_id: str = Form(...),
    db: Session = Depends(get_db),
):
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth

    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)

    unit = db.get(UnitDependency, unit_id)
    if unit is None or unit.subject != "english":
        raise HTTPException(status_code=400, detail="Invalid English unit")

    state = ensure_student_state(db, student)
    state.current_unit = unit_id
    state.current_level = 1
    state.last_problem_id = None
    db.add(state)
    db.commit()

    return RedirectResponse(url=f"/students/{student_id}/english/problem", status_code=303)


@router.get("/{student_id}/english/problem", response_class=HTMLResponse)
def english_problem(request: Request, student_id: int, hint_level: int = 0, db: Session = Depends(get_db)):
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth

    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)

    state = ensure_student_state(db, student)
    current_unit = state.current_unit or ""

    if not current_unit.startswith("eng_"):
        return RedirectResponse(url=f"/students/{student_id}/english", status_code=303)

    problem = None
    if state.last_problem_id:
        last = get_problem_by_id(db, state.last_problem_id)
        if last is not None and (last.full_unit_id or last.unit) == current_unit:
            problem = choose_next_problem(db, state, last)

    if problem is None:
        problem = get_first_problem_for_unit(db, current_unit)

    if problem is None:
        return RedirectResponse(
            url=f"/students/{student_id}/english?no_problems=1",
            status_code=303,
        )

    hint_level = max(0, min(2, hint_level))
    unit_labels = get_unit_label_map(db)
    diagram_display = get_diagram_display_info(problem, route="student")
    classroom = db.get(Classroom, student.classroom_id) if student.classroom_id else None

    review_count = count_due_reviews(db, student_id)
    flashcard_review_count = count_due_flashcards(db, student_id)
    unit_id = state.current_unit or problem.full_unit_id or problem.unit
    test_suggestion = should_trigger_test(db, student_id, unit_id) if unit_id else None

    # 今日の回答数を計算
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    today_count_row = db.execute(
        select(LearningLog).where(
            LearningLog.student_id == student_id,
            LearningLog.created_at >= datetime.strptime(today_str, "%Y-%m-%d"),
        )
    ).unique().all()
    today_answer_count = len(today_count_row)
    quest_goal = 10

    return _templates().TemplateResponse(
        "student_home.html",
        {
            "request": request,
            "student": student,
            "state": state,
            "problem": problem,
            "diagram_svg": render_problem_diagram_for_route(problem, "student"),
            "diagram_display": diagram_display,
            "unit_labels": unit_labels,
            "hint_level": hint_level,
            "is_student_view": True,
            "active_test": None,
            "test_suggestion": test_suggestion,
            "test_scope_label": test_scope_label(test_suggestion) if test_suggestion else None,
            "classroom_name": classroom.classroom_name if classroom else None,
            "review_count": review_count,
            "flashcard_review_count": flashcard_review_count,
            "today_answer_count": today_answer_count,
            "quest_goal": quest_goal,
            "is_adapted": False,
        },
    )


@router.post("/{student_id}/english/synonym-map")
def generate_synonym_map_endpoint(
    request: Request,
    student_id: int,
    body: SynonymMapRequest,
    db: Session = Depends(get_db),
):
    """
    近い間違い（near_miss）時に、使い分けマップを生成するエンドポイント
    
    Args:
        student_id: 学生ID
        body: {
            "submitted_word": "look",  # ユーザーが回答した単語
            "correct_word": "see",     # 正解の単語
            "hint_key": "see_look_watch"  # グループのヒントキー（オプション）
        }
    
    Returns:
        {
            "status": "ok" | "error",
            "data": {
                "message": "惜しい！...",
                "comparison": [...]
            } | null
        }
    """
    auth = require_student_login(request, student_id)
    if auth is not None:
        return JSONResponse(
            status_code=401,
            content={"status": "error", "message": "Unauthorized"}
        )
    
    student = db.get(Student, student_id)
    if student is None:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "Student not found"}
        )
    
    try:
        _ensure_student_classroom_access(request, student)
    except HTTPException:
        return JSONResponse(
            status_code=403,
            content={"status": "error", "message": "Classroom access denied"}
        )
    
    # 使い分けマップ生成
    map_data = generate_synonym_comparison_map(
        submitted_word=body.submitted_word.strip().lower(),
        correct_word=body.correct_word.strip().lower(),
        hint_key=body.hint_key
    )
    
    if map_data is None:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Failed to generate map"}
        )
    
    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "data": map_data
        }
    )
