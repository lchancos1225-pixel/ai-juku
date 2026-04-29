from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Classroom, LearningLog, Problem, Student, Teacher
from ..services.auth_service import read_session, require_teacher_login
from ..services.problem_service import get_unit_label_map
from ..paths import TEMPLATES_DIR


router = APIRouter(prefix="/classrooms", tags=["classrooms"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/dashboard", response_class=HTMLResponse)
def classroom_dashboard(request: Request, db: Session = Depends(get_db)):
    auth = require_teacher_login(request)
    if auth is not None:
        return auth

    session = read_session(request)
    classroom_id = session.get("classroom_id")
    classroom = db.get(Classroom, classroom_id)
    students = db.scalars(
        select(Student).where(Student.classroom_id == classroom_id).order_by(Student.student_id.asc())
    ).all()
    teachers = db.scalars(
        select(Teacher).where(Teacher.classroom_id == classroom_id).order_by(Teacher.teacher_id.asc())
    ).all()
    logs = db.execute(
        select(LearningLog, Problem, Student)
        .join(Problem, LearningLog.problem_id == Problem.problem_id)
        .join(Student, LearningLog.student_id == Student.student_id)
        .where(Student.classroom_id == classroom_id)
        .order_by(desc(LearningLog.created_at))
        .limit(20)
    ).all()
    return templates.TemplateResponse(
        "classroom_dashboard.html",
        {
            "request": request,
            "classroom": classroom,
            "students": students,
            "teachers": teachers,
            "logs": logs,
            "unit_labels": get_unit_label_map(db),
            "auth_role": "teacher",
        },
    )
