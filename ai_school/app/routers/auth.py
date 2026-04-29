from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Classroom, Owner, Student, Teacher
from ..paths import TEMPLATES_DIR
from ..schemas import UnifiedLoginRequest
from ..services.auth_service import (
    login_owner_session,
    login_student_session,
    login_teacher_session,
    logout_session,
    read_session,
    verify_secret,
)
from ..services.classroom_ops_service import classroom_login_allowed, normalize_classroom_code, validate_classroom_code_format

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _redirect_for_authenticated(session: dict):
    role = session.get("role")
    if role == "classroom":
        response = RedirectResponse(url="/login", status_code=303)
        logout_session(response)
        return response
    if role == "student" and session.get("student_id") is not None:
        return RedirectResponse(url=f"/students/{session['student_id']}/progress", status_code=303)
    if role == "teacher":
        return RedirectResponse(url="/teachers/dashboard", status_code=303)
    if role == "owner":
        return RedirectResponse(url="/owner/dashboard", status_code=303)
    return None


def _render_public_template(template_name: str, request: Request, **context):
    return templates.TemplateResponse(
        template_name,
        {
            "request": request,
            **context,
        },
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    redirect = _redirect_for_authenticated(read_session(request))
    if redirect is not None:
        return redirect
    return _render_public_template("login.html", request, error=None)


@router.post("/login")
def login_unified(
    body: UnifiedLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        code_norm = normalize_classroom_code(body.classroom_code)
        validate_classroom_code_format(code_norm)
    except HTTPException as exc:
        return JSONResponse({"ok": False, "detail": exc.detail}, status_code=exc.status_code)

    classroom = db.scalar(select(Classroom).where(func.upper(Classroom.code) == code_norm))
    if classroom is None or not classroom_login_allowed(classroom):
        return JSONResponse(
            {"ok": False, "detail": "教室コード・ログイン情報を確認してください。"},
            status_code=401,
        )

    if body.role == "student":
        ident = body.identifier.strip()
        if not ident:
            return JSONResponse({"ok": False, "detail": "なまえを入力してください。"}, status_code=422)
        clauses = [Student.display_name == ident]
        if ident.isdigit():
            clauses.append(Student.student_id == int(ident))
        student = db.scalar(
            select(Student).where(
                Student.classroom_id == classroom.classroom_id,
                Student.is_active.is_(True),
                or_(*clauses),
            )
        )
        if student is None:
            return JSONResponse(
                {"ok": False, "detail": "この教室で使えるなまえ・PINを確認してください。"},
                status_code=401,
            )
        pin = (body.pin or "").strip()
        if student.login_pin_hash and not verify_secret(pin, student.login_pin_hash):
            return JSONResponse(
                {"ok": False, "detail": "PINが違います。"},
                status_code=401,
            )
        classroom.last_activity_at = datetime.utcnow().isoformat()
        db.add(classroom)
        db.commit()
        response = JSONResponse(
            {
                "ok": True,
                "redirect": f"/students/{student.student_id}/progress",
                "classroom_name": classroom.classroom_name,
            }
        )
        login_student_session(response, student)
        return response

    ident = body.identifier.strip()
    if not ident:
        return JSONResponse({"ok": False, "detail": "教師IDを入力してください。"}, status_code=422)
    teacher = db.scalar(
        select(Teacher).where(
            Teacher.classroom_id == classroom.classroom_id,
            Teacher.login_id == ident,
            Teacher.is_active.is_(True),
        )
    )
    pw = (body.password or "").strip()
    if teacher is None or not verify_secret(pw, teacher.password_hash):
        return JSONResponse(
            {"ok": False, "detail": "この教室で使える教師ID・パスワードを確認してください。"},
            status_code=401,
        )
    classroom.last_activity_at = datetime.utcnow().isoformat()
    db.add(classroom)
    db.commit()
    response = JSONResponse({"ok": True, "redirect": "/teachers/dashboard"})
    login_teacher_session(response, teacher)
    return response


@router.get("/login/classroom-students")
def get_classroom_students(code: str, db: Session = Depends(get_db)):
    """教室コードから生徒一覧を返す（ログイン画面の名前選択用）。"""
    try:
        code_norm = normalize_classroom_code(code)
        validate_classroom_code_format(code_norm)
    except HTTPException as exc:
        return JSONResponse({"ok": False, "detail": exc.detail}, status_code=exc.status_code)

    classroom = db.scalar(select(Classroom).where(func.upper(Classroom.code) == code_norm))
    if classroom is None or not classroom_login_allowed(classroom):
        return JSONResponse({"ok": False, "detail": "教室コードが見つかりません。"}, status_code=404)

    students = db.scalars(
        select(Student).where(
            Student.classroom_id == classroom.classroom_id,
            Student.is_active.is_(True),
        ).order_by(Student.display_name)
    ).all()

    return JSONResponse({
        "ok": True,
        "classroom_name": classroom.classroom_name,
        "students": [
            {"student_id": s.student_id, "display_name": s.display_name, "grade": s.grade}
            for s in students
        ],
    })


@router.get("/login/classroom", include_in_schema=False)
@router.post("/login/classroom", include_in_schema=False)
def deprecate_login_classroom():
    return RedirectResponse(url="/login", status_code=301)


@router.get("/login/classroom/select", include_in_schema=False)
@router.post("/login/classroom/select", include_in_schema=False)
def deprecate_login_classroom_select():
    return RedirectResponse(url="/login", status_code=301)


@router.get("/login/student", include_in_schema=False)
@router.post("/login/student", include_in_schema=False)
def deprecate_login_student():
    return RedirectResponse(url="/login", status_code=301)


@router.get("/login/teacher", include_in_schema=False)
@router.post("/login/teacher", include_in_schema=False)
def deprecate_login_teacher():
    return RedirectResponse(url="/login", status_code=301)


@router.get("/login/owner", response_class=HTMLResponse)
def login_owner_page(request: Request):
    redirect = _redirect_for_authenticated(read_session(request))
    if redirect is not None:
        return redirect
    return _render_public_template("login_owner.html", request, error=None)


@router.post("/login/owner", response_class=HTMLResponse)
def login_owner(
    request: Request,
    login_id: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    owner = db.scalar(select(Owner).where(Owner.login_id == login_id.strip()))
    if owner is None or not owner.is_active or not verify_secret(password, owner.password_hash):
        return _render_public_template(
            "login_owner.html",
            request,
            error="ログインIDまたはパスワードが違います。",
        )
    response = RedirectResponse(url="/owner/dashboard", status_code=303)
    login_owner_session(response, owner)
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    logout_session(response)
    return response
