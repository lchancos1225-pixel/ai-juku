"""Listening routes for students and teachers."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Classroom, ListeningLog, ListeningProblem, Student, Teacher
from ..services.auth_service import ensure_session_classroom_access, read_session, require_student_login, require_teacher_login
from ..services.listening_service import (
    UNIT_DISPLAY,
    build_listening_mastery_rows,
    build_listening_stats,
    count_problems_in_unit,
    listening_home_units,
    resolve_practice_problem,
    submit_listening_answer,
    _get_mastery_row,
)
from . import student as _student_router

_templ = _student_router.templates
if "tojson" not in _templ.env.filters:
    _templ.env.filters["tojson"] = lambda v: json.dumps(v, ensure_ascii=False)

router = APIRouter(tags=["listening"])


def _templates():
    return _student_router.templates


def _ensure_student_classroom_access(request: Request, student: Student) -> None:
    session = read_session(request)
    ensure_session_classroom_access(session, student.classroom_id)


class ListeningSubmitBody(BaseModel):
    problem_id: str = Field(...)
    selected_answer: str = Field(...)
    play_count: int = Field(default=1, ge=0)
    elapsed_sec: int | None = Field(default=None, ge=0)
    hint_used: int = Field(default=0, ge=0, le=2)


@router.get("/students/{student_id}/listening", response_class=HTMLResponse)
def listening_home(request: Request, student_id: int, db: Session = Depends(get_db)):
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)
    classroom = db.get(Classroom, student.classroom_id) if student.classroom_id else None
    grade = student.grade or 7
    units_by_grade = {
        7: listening_home_units(db, student, classroom, 7),
        8: listening_home_units(db, student, classroom, 8),
        9: listening_home_units(db, student, classroom, 9),
    }
    return _templates().TemplateResponse(
        "student_listening_home.html",
        {
            "request": request,
            "student": student,
            "student_id": student_id,
            "units_by_grade": units_by_grade,
            "default_grade": grade,
            "is_student_view": True,
            "title": "\u30ea\u30b9\u30cb\u30f3\u30b0",
        },
    )


@router.get("/students/{student_id}/listening/progress", response_class=HTMLResponse)
def listening_progress_page(request: Request, student_id: int, db: Session = Depends(get_db)):
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)
    grade = student.grade or 7
    rows = build_listening_mastery_rows(db, student_id, grade)
    return _templates().TemplateResponse(
        "student_listening_progress.html",
        {
            "request": request,
            "student": student,
            "student_id": student_id,
            "listening_rows": rows,
            "is_student_view": True,
            "title": "\u30ea\u30b9\u30cb\u30f3\u30b0\u306e\u8a18\u9332",
        },
    )


@router.get("/students/{student_id}/listening/problem", response_class=HTMLResponse)
def listening_problem(
    request: Request,
    student_id: int,
    unit_id: str,
    problem_id: str | None = None,
    db: Session = Depends(get_db),
):
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)
    classroom = db.get(Classroom, student.classroom_id) if student.classroom_id else None
    prob = resolve_practice_problem(db, student, classroom, unit_id, problem_id)
    if prob is None:
        raise HTTPException(status_code=404, detail="No problem available for this unit")
    try:
        choices = json.loads(prob.choices) if prob.choices else []
    except json.JSONDecodeError:
        choices = []
    total_in_unit = count_problems_in_unit(db, unit_id)
    mastery = _get_mastery_row(db, student_id, unit_id)
    solved = mastery.correct_count if mastery else 0
    return _templates().TemplateResponse(
        "student_listening_problem.html",
        {
            "request": request,
            "student_id": student_id,
            "unit_id": unit_id,
            "unit_label": UNIT_DISPLAY.get(unit_id, unit_id),
            "grade_band": student.grade or 7,
            "problem": prob,
            "choices": choices,
            "progress_total": total_in_unit,
            "progress_solved": solved,
            "is_student_view": True,
            "title": "\u30ea\u30b9\u30cb\u30f3\u30b0\u554f\u984c",
        },
    )


@router.post("/students/{student_id}/listening/submit")
def listening_submit(
    request: Request,
    student_id: int,
    body: ListeningSubmitBody,
    db: Session = Depends(get_db),
):
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)
    out = submit_listening_answer(
        db,
        student,
        body.problem_id,
        body.selected_answer,
        body.play_count,
        body.elapsed_sec,
        body.hint_used,
    )
    if out is None:
        raise HTTPException(status_code=404, detail="Problem not found")
    return JSONResponse(out)


@router.get("/students/{student_id}/listening/result/{log_id}", response_class=HTMLResponse)
def listening_result(
    request: Request,
    student_id: int,
    log_id: int,
    next_problem_id: str | None = None,
    db: Session = Depends(get_db),
):
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)
    log_row = db.get(ListeningLog, log_id)
    if log_row is None or log_row.student_id != student_id:
        raise HTTPException(status_code=404, detail="Log not found")
    problem = db.get(ListeningProblem, log_row.problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem missing")
    try:
        choices = json.loads(problem.choices) if problem.choices else []
    except json.JSONDecodeError:
        choices = []
    messages = {
        "retry_with_slower_audio": "\u3086\u3063\u304f\u308a\u97f3\u58f0\u3067\u3082\u3046\u4e00\u5ea6\u30c1\u30e3\u30ec\u30f3\u30b8\u3057\u3066\u307f\u307e\u3057\u3087\u3046\u3002",
        "retry_with_keyword_hint": "\u30ad\u30fc\u30ef\u30fc\u30c9\u306e\u30d2\u30f3\u30c8\u3092\u4f7f\u3063\u3066\u3082\u3046\u4e00\u5ea6\u805e\u3044\u3066\u307f\u307e\u3057\u3087\u3046\u3002",
        "fallback_vocab_review": "\u8a9e\u5f59\u306e\u5fa9\u7fd2\u304b\u3089\u5165\u308b\u3068\u805e\u304d\u53d6\u308a\u3084\u3059\u304f\u306a\u308b\u3053\u3068\u304c\u3042\u308a\u307e\u3059\u3002",
        "fallback_basic_sentence": "\u57fa\u672c\u306e\u6587\u578b\u304b\u3089\u77ed\u3044\u6587\u3067\u5fa9\u7fd2\u3057\u3066\u307f\u307e\u3057\u3087\u3046\u3002",
        "explain_differently": "\u610f\u5473\u306e\u3064\u306a\u304c\u308a\u3092\u8a00\u3044\u63db\u3048\u3066\u6574\u7406\u3057\u3066\u307f\u307e\u3057\u3087\u3046\u3002",
        "slow_down_and_replay": "\u518d\u751f\u3092\u7e70\u308a\u8fd4\u3057\u3001\u6700\u5f8c\u307e\u3067\u96c6\u4e2d\u3057\u3066\u805e\u304d\u53d6\u308a\u307e\u3057\u3087\u3046\u3002",
        "teacher_intervention_needed": "\u6559\u5e2b\u306b\u69d8\u5b50\u3092\u5171\u6709\u3057\u3066\u307f\u307e\u3057\u3087\u3046\u3002",
        "monitor_only": "\u3053\u306e\u307e\u307e\u7d9a\u3051\u3066\u5927\u4e08\u592b\u3067\u3059\u3002",
    }
    iv = log_row.intervention_type or "monitor_only"
    next_unit_id = problem.full_unit_id
    if next_problem_id:
        np = db.get(ListeningProblem, next_problem_id)
        if np is not None:
            next_unit_id = np.full_unit_id
    return _templates().TemplateResponse(
        "student_listening_result.html",
        {
            "request": request,
            "student_id": student_id,
            "log": log_row,
            "problem": problem,
            "choices": choices,
            "next_problem_id": next_problem_id,
            "next_unit_id": next_unit_id,
            "intervention_message": messages.get(iv, messages["monitor_only"]),
            "is_student_view": True,
            "title": "\u7d50\u679c",
        },
    )


@router.get("/teachers/listening/stats")
def teacher_listening_stats(request: Request, classroom_id: int, db: Session = Depends(get_db)):
    auth = require_teacher_login(request)
    if auth is not None:
        return auth
    session = read_session(request)
    current_teacher = db.get(Teacher, session.get("teacher_id"))
    if current_teacher is None:
        raise HTTPException(status_code=403, detail="teacher access denied")
    ensure_session_classroom_access(session, current_teacher.classroom_id)
    if classroom_id != session.get("classroom_id"):
        raise HTTPException(status_code=403, detail="classroom mismatch")
    return JSONResponse(build_listening_stats(db, classroom_id))
