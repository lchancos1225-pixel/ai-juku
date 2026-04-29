from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import Classroom, ClassroomContract, Owner, Student, Teacher
from ..schemas import (
    ActivationRequest,
    ClassroomContractUpdateRequest,
    ClassroomCreateRequest,
    ClassroomPurgeRequest,
    ClassroomUpdateRequest,
    OptionalPasswordRequest,
    StudentCreateRequest,
    TeacherCreateRequest,
)
from ..services.auth_service import generate_password, generate_pin, hash_secret, read_session, require_owner_login
from ..services.classroom_ops_service import (
    allocate_classroom_code,
    assert_can_add_student,
    count_students_for_classroom,
    dependency_counts_for_classroom,
    get_contract_for_classroom,
    log_classroom_deletion,
    purge_classroom,
    normalize_classroom_code,
    validate_allowed_subjects,
    validate_classroom_code_format,
    validate_contract_status,
)
from ..services.state_service import ensure_student_state
from ..paths import TEMPLATES_DIR


router = APIRouter(prefix="/owner", tags=["owner"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _default_contract_fields(payload: ClassroomCreateRequest) -> dict:
    start = (payload.contract_start or "").strip() or datetime.utcnow().strftime("%Y-%m-%d")
    plan_name = (payload.plan_name or "").strip() or "QRelDo 30（スタンダードプラン）"
    max_students = payload.max_students if payload.max_students is not None else 30
    if max_students < 1:
        raise HTTPException(status_code=422, detail="max_students must be >= 1")
    allowed = validate_allowed_subjects(payload.allowed_subjects or "math_english")
    monthly = int(payload.monthly_price) if payload.monthly_price is not None else 29800
    yearly = int(payload.yearly_price) if payload.yearly_price is not None else 0
    cend = (payload.contract_end or "").strip() or None
    cstat = validate_contract_status(payload.contract_status or "active")
    memo = (payload.contract_memo or "").strip() or None
    return {
        "plan_name": plan_name,
        "max_students": max_students,
        "allowed_subjects": allowed,
        "monthly_price": monthly,
        "yearly_price": yearly,
        "contract_start": start,
        "contract_end": cend,
        "contract_status": cstat,
        "contract_memo": memo,
    }


@router.get("/dashboard", response_class=HTMLResponse)
def owner_dashboard(request: Request, db: Session = Depends(get_db)):
    auth = require_owner_login(request)
    if auth is not None:
        return auth

    session = read_session(request)
    owner = db.get(Owner, session.get("owner_id")) if session.get("owner_id") else None
    classrooms = db.scalars(
        select(Classroom).options(selectinload(Classroom.contract)).order_by(Classroom.classroom_id.asc())
    ).all()
    student_counts = {
        classroom_id: count
        for classroom_id, count in db.execute(
            select(Student.classroom_id, func.count(Student.student_id)).group_by(Student.classroom_id)
        ).all()
    }
    teacher_counts = {
        classroom_id: count
        for classroom_id, count in db.execute(
            select(Teacher.classroom_id, func.count(Teacher.teacher_id)).group_by(Teacher.classroom_id)
        ).all()
    }
    active_rows = [c for c in classrooms if not c.is_archived]
    archived_rows = [c for c in classrooms if c.is_archived]

    return templates.TemplateResponse(
        "owner_dashboard.html",
        {
            "request": request,
            "owner": owner,
            "classrooms": classrooms,
            "classrooms_active": active_rows,
            "classrooms_archived": archived_rows,
            "student_counts": student_counts,
            "teacher_counts": teacher_counts,
            "auth_role": "owner",
            "title": "教室運用センター",
        },
    )


@router.post("/classrooms/create")
def create_classroom(payload: ClassroomCreateRequest, request: Request, db: Session = Depends(get_db)):
    require_owner_login(request, api=True)

    classroom_name = payload.classroom_name.strip()
    login_id = payload.login_id.strip()
    ext_id = (payload.external_classroom_id or "").strip() or login_id
    if not classroom_name:
        raise HTTPException(status_code=422, detail="classroom_name required")
    if not login_id:
        raise HTTPException(status_code=422, detail="login_id required")
    if not ext_id:
        raise HTTPException(status_code=422, detail="external_classroom_id required")
    existing = db.scalar(select(Classroom).where(Classroom.login_id == login_id))
    if existing is not None:
        raise HTTPException(status_code=409, detail="login_id already exists")
    existing_ext = db.scalar(select(Classroom).where(Classroom.external_classroom_id == ext_id))
    if existing_ext is not None:
        raise HTTPException(status_code=409, detail="external_classroom_id already exists")

    password = (payload.password or "").strip() or generate_password()
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="password must be at least 8 characters")

    cf = _default_contract_fields(payload)
    now = datetime.utcnow().isoformat()
    classroom = Classroom(
        classroom_name=classroom_name,
        external_classroom_id=ext_id,
        login_id=login_id,
        password_hash=hash_secret(password),
        is_active=True,
        is_archived=False,
        created_at=now,
        updated_at=now,
        contact_name=(payload.contact_name or "").strip() or None,
        admin_email=(payload.admin_email or "").strip() or None,
        admin_phone=(payload.admin_phone or "").strip() or None,
        note=(payload.note or "").strip() or None,
    )
    db.add(classroom)
    db.flush()
    if payload.classroom_code and str(payload.classroom_code).strip():
        normalized = normalize_classroom_code(payload.classroom_code)
        validate_classroom_code_format(normalized)
        taken = db.scalar(select(Classroom).where(func.upper(Classroom.code) == normalized))
        if taken is not None:
            raise HTTPException(status_code=409, detail="classroom_code already exists")
        classroom.code = normalized
    else:
        classroom.code = allocate_classroom_code(db, login_id, classroom.classroom_id)
    db.add(classroom)
    contract = ClassroomContract(
        classroom_id=classroom.classroom_id,
        plan_name=cf["plan_name"],
        max_students=cf["max_students"],
        allowed_subjects=cf["allowed_subjects"],
        monthly_price=cf["monthly_price"],
        yearly_price=cf["yearly_price"],
        contract_start=cf["contract_start"],
        contract_end=cf["contract_end"],
        contract_status=cf["contract_status"],
        contract_memo=cf["contract_memo"],
        created_at=now,
        updated_at=now,
    )
    db.add(contract)
    db.commit()
    db.refresh(classroom)
    return {
        "status": "ok",
        "classroom_id": classroom.classroom_id,
        "classroom_name": classroom.classroom_name,
        "external_classroom_id": classroom.external_classroom_id,
        "login_id": classroom.login_id,
        "classroom_code": classroom.code,
        "new_password_once": password,
    }


@router.post("/classrooms/{classroom_id}/set_active")
def set_classroom_active(classroom_id: int, payload: ActivationRequest, request: Request, db: Session = Depends(get_db)):
    require_owner_login(request, api=True)

    classroom = db.get(Classroom, classroom_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="classroom not found")
    if classroom.is_archived:
        raise HTTPException(status_code=409, detail="archived classroom; unarchive first")

    classroom.is_active = payload.is_active
    classroom.updated_at = datetime.utcnow().isoformat()
    db.add(classroom)
    db.commit()
    return {"status": "ok", "classroom_id": classroom_id, "is_active": classroom.is_active}


@router.post("/classrooms/{classroom_id}/archive")
def archive_classroom(classroom_id: int, request: Request, db: Session = Depends(get_db)):
    require_owner_login(request, api=True)
    classroom = db.get(Classroom, classroom_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="classroom not found")
    classroom.is_archived = True
    classroom.is_active = False
    classroom.updated_at = datetime.utcnow().isoformat()
    db.add(classroom)
    db.commit()
    return {"status": "ok", "classroom_id": classroom_id, "is_archived": True}


@router.post("/classrooms/{classroom_id}/unarchive")
def unarchive_classroom(classroom_id: int, request: Request, db: Session = Depends(get_db)):
    require_owner_login(request, api=True)
    classroom = db.get(Classroom, classroom_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="classroom not found")
    classroom.is_archived = False
    classroom.updated_at = datetime.utcnow().isoformat()
    db.add(classroom)
    db.commit()
    return {"status": "ok", "classroom_id": classroom_id, "is_archived": False}


@router.get("/classrooms/{classroom_id}/purge_preview")
def purge_preview(classroom_id: int, request: Request, db: Session = Depends(get_db)):
    require_owner_login(request, api=True)
    classroom = db.get(Classroom, classroom_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="classroom not found")
    counts = dependency_counts_for_classroom(db, classroom_id)
    return {"status": "ok", "classroom_id": classroom_id, "dependencies": counts}


@router.post("/classrooms/{classroom_id}/purge")
def purge_classroom_route(
    classroom_id: int,
    payload: ClassroomPurgeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    require_owner_login(request, api=True)
    session = read_session(request)
    owner_id = session.get("owner_id")
    classroom = db.get(Classroom, classroom_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="classroom not found")
    if payload.confirm_text.strip() != "\u5b8c\u5168\u306b\u524a\u9664":
        raise HTTPException(status_code=422, detail="confirm_text mismatch")
    if payload.classroom_name.strip() != classroom.classroom_name.strip():
        raise HTTPException(status_code=422, detail="classroom_name mismatch")
    counts = dependency_counts_for_classroom(db, classroom_id)
    log_classroom_deletion(db, owner_id=owner_id, classroom=classroom, counts=counts)
    purge_classroom(db, classroom_id)
    db.commit()
    return {"status": "ok", "deleted_classroom_id": classroom_id}


@router.put("/classrooms/{classroom_id}")
def update_classroom(classroom_id: int, payload: ClassroomUpdateRequest, request: Request, db: Session = Depends(get_db)):
    require_owner_login(request, api=True)

    classroom = db.get(Classroom, classroom_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="classroom not found")

    if payload.classroom_name is not None:
        name = payload.classroom_name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="classroom_name cannot be empty")
        classroom.classroom_name = name

    if payload.login_id is not None:
        login_id = payload.login_id.strip()
        if not login_id:
            raise HTTPException(status_code=422, detail="login_id cannot be empty")
        existing = db.scalar(select(Classroom).where(Classroom.login_id == login_id, Classroom.classroom_id != classroom_id))
        if existing is not None:
            raise HTTPException(status_code=409, detail="login_id already in use")
        classroom.login_id = login_id

    if payload.contact_name is not None:
        classroom.contact_name = payload.contact_name.strip() or None

    if payload.note is not None:
        classroom.note = payload.note.strip() or None

    if payload.external_classroom_id is not None:
        ext = payload.external_classroom_id.strip()
        if not ext:
            raise HTTPException(status_code=422, detail="external_classroom_id cannot be empty")
        existing = db.scalar(select(Classroom).where(Classroom.external_classroom_id == ext, Classroom.classroom_id != classroom_id))
        if existing is not None:
            raise HTTPException(status_code=409, detail="external_classroom_id already in use")
        classroom.external_classroom_id = ext

    if payload.admin_email is not None:
        classroom.admin_email = payload.admin_email.strip() or None

    if payload.admin_phone is not None:
        classroom.admin_phone = payload.admin_phone.strip() or None

    if payload.classroom_code is not None:
        normalized = normalize_classroom_code(payload.classroom_code)
        validate_classroom_code_format(normalized)
        taken = db.scalar(
            select(Classroom).where(
                func.upper(Classroom.code) == normalized,
                Classroom.classroom_id != classroom_id,
            )
        )
        if taken is not None:
            raise HTTPException(status_code=409, detail="classroom_code already in use")
        classroom.code = normalized

    classroom.updated_at = datetime.utcnow().isoformat()
    db.add(classroom)
    db.commit()
    db.refresh(classroom)
    return {
        "status": "ok",
        "classroom_id": classroom.classroom_id,
        "classroom_name": classroom.classroom_name,
        "login_id": classroom.login_id,
        "external_classroom_id": classroom.external_classroom_id,
    }


@router.put("/classrooms/{classroom_id}/contract")
def update_contract(
    classroom_id: int,
    payload: ClassroomContractUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    require_owner_login(request, api=True)
    classroom = db.get(Classroom, classroom_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="classroom not found")
    contract = get_contract_for_classroom(db, classroom_id)
    now = datetime.utcnow().isoformat()

    if payload.plan_name is not None:
        pn = payload.plan_name.strip()
        if not pn:
            raise HTTPException(status_code=422, detail="plan_name cannot be empty")
        contract.plan_name = pn
    if payload.max_students is not None:
        if payload.max_students < 1:
            raise HTTPException(status_code=422, detail="max_students must be >= 1")
        current = count_students_for_classroom(db, classroom_id)
        if payload.max_students < current:
            raise HTTPException(
                status_code=409,
                detail=f"max_students cannot be below current student count ({current})",
            )
        contract.max_students = payload.max_students
    if payload.allowed_subjects is not None:
        contract.allowed_subjects = validate_allowed_subjects(payload.allowed_subjects)
    if payload.monthly_price is not None:
        contract.monthly_price = int(payload.monthly_price)
    if payload.yearly_price is not None:
        contract.yearly_price = int(payload.yearly_price)
    if payload.contract_start is not None:
        contract.contract_start = payload.contract_start.strip()
    if payload.contract_end is not None:
        contract.contract_end = payload.contract_end.strip() or None
    if payload.contract_status is not None:
        contract.contract_status = validate_contract_status(payload.contract_status)
    if payload.contract_memo is not None:
        contract.contract_memo = payload.contract_memo.strip() or None

    contract.updated_at = now
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return {"status": "ok", "contract_id": contract.contract_id, "classroom_id": classroom_id}


@router.post("/classrooms/{classroom_id}/reset_password")
def reset_classroom_password(
    classroom_id: int,
    request: Request,
    db: Session = Depends(get_db),
    payload: OptionalPasswordRequest | None = Body(default=None),
):
    require_owner_login(request, api=True)

    classroom = db.get(Classroom, classroom_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="classroom not found")

    if payload and payload.password:
        new_password = payload.password.strip()
        if len(new_password) < 8:
            raise HTTPException(status_code=422, detail="password must be at least 8 characters")
    else:
        new_password = generate_password()
    classroom.password_hash = hash_secret(new_password)
    classroom.updated_at = datetime.utcnow().isoformat()
    db.add(classroom)
    db.commit()
    return {"status": "ok", "classroom_id": classroom_id, "new_password_once": new_password}


@router.post("/students/create")
def create_student(payload: StudentCreateRequest, request: Request, db: Session = Depends(get_db)):
    require_owner_login(request, api=True)

    if db.get(Student, payload.student_id) is not None:
        raise HTTPException(status_code=409, detail="student_id already exists")
    classroom = db.get(Classroom, payload.classroom_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="classroom not found")
    assert_can_add_student(db, classroom.classroom_id)

    pin = (payload.pin or generate_pin()).strip()
    if not pin.isdigit() or len(pin) != 4:
        raise HTTPException(status_code=422, detail="pin must be 4 digits")

    student = Student(
        student_id=payload.student_id,
        display_name=payload.display_name.strip(),
        grade=payload.grade,
        classroom_id=classroom.classroom_id,
        login_pin_hash=hash_secret(pin),
        is_active=True,
        pin_last_reset_at=datetime.utcnow().isoformat(),
        status="active",
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    ensure_student_state(db, student)
    return {
        "status": "ok",
        "student_id": student.student_id,
        "display_name": student.display_name,
        "new_pin_once": pin,
    }


@router.post("/teachers/create")
def create_teacher(payload: TeacherCreateRequest, request: Request, db: Session = Depends(get_db)):
    require_owner_login(request, api=True)

    login_id = payload.login_id.strip()
    if not login_id:
        raise HTTPException(status_code=422, detail="login_id required")
    existing = db.scalar(select(Teacher).where(Teacher.login_id == login_id))
    if existing is not None:
        raise HTTPException(status_code=409, detail="login_id already exists")
    classroom = db.get(Classroom, payload.classroom_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="classroom not found")

    password = payload.password or generate_password()
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="password must be at least 8 characters")

    now = datetime.utcnow().isoformat()
    teacher = Teacher(
        classroom_id=classroom.classroom_id,
        login_id=login_id,
        password_hash=hash_secret(password),
        display_name=payload.display_name.strip() or login_id,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(teacher)
    db.commit()
    db.refresh(teacher)
    return {
        "status": "ok",
        "teacher_id": teacher.teacher_id,
        "login_id": teacher.login_id,
        "new_password_once": password,
    }


@router.post("/students/{student_id}/reset_pin")
def reset_student_pin(student_id: int, request: Request, db: Session = Depends(get_db)):
    require_owner_login(request, api=True)

    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="student not found")

    new_pin = generate_pin()
    student.login_pin_hash = hash_secret(new_pin)
    student.pin_last_reset_at = datetime.utcnow().isoformat()
    student.is_active = True
    db.add(student)
    db.commit()
    return {"status": "ok", "student_id": student_id, "new_pin_once": new_pin}


@router.post("/students/{student_id}/set_active")
def set_student_active(student_id: int, payload: ActivationRequest, request: Request, db: Session = Depends(get_db)):
    require_owner_login(request, api=True)

    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="student not found")

    student.is_active = payload.is_active
    db.add(student)
    db.commit()
    return {"status": "ok", "student_id": student_id, "is_active": student.is_active}


@router.post("/teachers/{teacher_id}/set_active")
def set_teacher_active(teacher_id: int, payload: ActivationRequest, request: Request, db: Session = Depends(get_db)):
    require_owner_login(request, api=True)

    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status_code=404, detail="teacher not found")

    teacher.is_active = payload.is_active
    teacher.updated_at = datetime.utcnow().isoformat()
    db.add(teacher)
    db.commit()
    return {"status": "ok", "teacher_id": teacher_id, "is_active": teacher.is_active}
