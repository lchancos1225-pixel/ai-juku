import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Classroom, ClassroomContract, Owner, Student, Teacher
from .classroom_ops_service import allocate_classroom_code


PBKDF2_ITERATIONS = 120_000
_DEFAULT_SESSION_SECRET_VALUE = "ai-school-dev-session-secret"
SESSION_SECRET = os.getenv("AI_SCHOOL_SESSION_SECRET") or _DEFAULT_SESSION_SECRET_VALUE
SESSION_COOKIE_NAME = "ai_school_session"
_logger = logging.getLogger(__name__)

DEFAULT_STUDENT_PINS = {
    1: "1111",
    2: "2222",
}
DEFAULT_OWNER_LOGIN_ID = os.getenv("AI_SCHOOL_SEED_OWNER_LOGIN_ID") or "junsato"
LEGACY_OWNER_LOGIN_ID = "owner1"
DEFAULT_OWNER_PASSWORD = os.getenv("AI_SCHOOL_SEED_OWNER_PASSWORD") or "1225"
DEFAULT_OWNER_DISPLAY_NAME = os.getenv("AI_SCHOOL_SEED_OWNER_DISPLAY_NAME") or "JUN"
DEFAULT_CLASSROOM_LOGIN_ID = os.getenv("AI_SCHOOL_SEED_CLASSROOM_LOGIN_ID") or "classroom1"
DEFAULT_CLASSROOM_PASSWORD = os.getenv("AI_SCHOOL_SEED_CLASSROOM_PASSWORD") or "1234"
DEFAULT_CLASSROOM_NAME = os.getenv("AI_SCHOOL_SEED_CLASSROOM_NAME") or "サンプル教室"
DEFAULT_CLASSROOM_TEACHER_LOGIN_ID = os.getenv("AI_SCHOOL_SEED_TEACHER_LOGIN_ID") or "teacher1"
DEFAULT_CLASSROOM_TEACHER_PASSWORD = os.getenv("AI_SCHOOL_SEED_TEACHER_PASSWORD") or "1234"
DEFAULT_CLASSROOM_TEACHER_DISPLAY_NAME = os.getenv("AI_SCHOOL_SEED_TEACHER_DISPLAY_NAME") or "担当講師"


def hash_secret(secret: str) -> str:
    salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${derived.hex()}"


def verify_secret(secret: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        algorithm, iterations, salt, digest = hashed.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        derived = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt.encode("utf-8"), int(iterations))
        return hmac.compare_digest(derived.hex(), digest)
    except Exception:
        return False


def generate_pin() -> str:
    return f"{secrets.randbelow(10_000):04d}"


def generate_password(length: int = 10) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def check_startup_security() -> None:
    """本番環境向けの設定不備を起動時に警告する。"""
    if SESSION_SECRET == _DEFAULT_SESSION_SECRET_VALUE:
        _logger.warning(
            "AI_SCHOOL_SESSION_SECRET にデフォルト値が使われています。"
            "本番環境では必ず長いランダム文字列を設定してください"
            " (例: python -c 'import secrets; print(secrets.token_hex(32))')。"
        )
    if DEFAULT_OWNER_PASSWORD == "1225":
        _logger.warning(
            "AI_SCHOOL_SEED_OWNER_PASSWORD がデフォルト値 '1225' のままです。"
            "本番環境では AI_SCHOOL_SEED_OWNER_PASSWORD を強いパスワードに設定してください。"
        )
    if DEFAULT_CLASSROOM_PASSWORD == "1234":
        _logger.warning(
            "AI_SCHOOL_SEED_CLASSROOM_PASSWORD がデフォルト値 '1234' のままです。"
            "本番環境では AI_SCHOOL_SEED_CLASSROOM_PASSWORD を強いパスワードに設定してください。"
        )
    if DEFAULT_CLASSROOM_TEACHER_PASSWORD == "1234":
        _logger.warning(
            "AI_SCHOOL_SEED_TEACHER_PASSWORD がデフォルト値 '1234' のままです。"
            "本番環境では AI_SCHOOL_SEED_TEACHER_PASSWORD を強いパスワードに設定してください。"
        )


def seed_auth_credentials(db: Session) -> None:
    now = datetime.utcnow().isoformat()
    changed = False

    classroom = db.scalar(select(Classroom).where(Classroom.login_id == DEFAULT_CLASSROOM_LOGIN_ID))
    if classroom is None:
        classroom = Classroom(
            classroom_name=DEFAULT_CLASSROOM_NAME,
            external_classroom_id=DEFAULT_CLASSROOM_LOGIN_ID,
            login_id=DEFAULT_CLASSROOM_LOGIN_ID,
            password_hash=hash_secret(DEFAULT_CLASSROOM_PASSWORD),
            is_active=True,
            is_archived=False,
            created_at=now,
            updated_at=now,
            contact_name="JUN",
            note="既存データをぶら下げる初期教室",
        )
        db.add(classroom)
        db.flush()
        classroom.code = allocate_classroom_code(db, DEFAULT_CLASSROOM_LOGIN_ID, classroom.classroom_id)
        start = datetime.utcnow().strftime("%Y-%m-%d")
        db.add(
            ClassroomContract(
                classroom_id=classroom.classroom_id,
                plan_name="QRelDo 30（スタンダードプラン）",
                max_students=30,
                allowed_subjects="math_english",
                monthly_price=29800,
                yearly_price=0,
                contract_start=start,
                contract_end=None,
                contract_status="active",
                contract_memo=None,
                created_at=now,
                updated_at=now,
            )
        )
        changed = True
    else:
        classroom_changed = False
        if not verify_secret(DEFAULT_CLASSROOM_PASSWORD, classroom.password_hash):
            classroom.password_hash = hash_secret(DEFAULT_CLASSROOM_PASSWORD)
            classroom_changed = True
        if classroom.external_classroom_id is None:
            classroom.external_classroom_id = classroom.login_id
            classroom_changed = True
        if classroom.updated_at is None:
            classroom.updated_at = now
            classroom_changed = True
        if not classroom.code or not str(classroom.code).strip():
            classroom.code = allocate_classroom_code(db, classroom.login_id, classroom.classroom_id)
            classroom_changed = True
        if classroom_changed:
            db.add(classroom)
            changed = True

    owner = db.scalar(select(Owner).where(Owner.login_id == DEFAULT_OWNER_LOGIN_ID))
    if owner is None:
        legacy_owner = db.scalar(select(Owner).where(Owner.login_id == LEGACY_OWNER_LOGIN_ID))
        if legacy_owner is not None:
            legacy_owner.login_id = DEFAULT_OWNER_LOGIN_ID
            legacy_owner.updated_at = now
            db.add(legacy_owner)
            changed = True
        else:
            db.add(
                Owner(
                    login_id=DEFAULT_OWNER_LOGIN_ID,
                    password_hash=hash_secret(DEFAULT_OWNER_PASSWORD),
                    display_name=DEFAULT_OWNER_DISPLAY_NAME,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            )
            changed = True
    elif owner.updated_at is None:
        owner.updated_at = now
        db.add(owner)
        changed = True
    elif not verify_secret(DEFAULT_OWNER_PASSWORD, owner.password_hash):
        owner.password_hash = hash_secret(DEFAULT_OWNER_PASSWORD)
        owner.updated_at = now
        db.add(owner)
        changed = True

    for student in db.scalars(select(Student)).all():
        student_changed = False
        if not student.login_pin_hash:
            plain_pin = DEFAULT_STUDENT_PINS.get(student.student_id, generate_pin())
            student.login_pin_hash = hash_secret(plain_pin)
            student.pin_last_reset_at = now
            student.is_active = True
            student_changed = True
        if classroom is not None and student.classroom_id is None:
            student.classroom_id = classroom.classroom_id
            student_changed = True
        if student_changed:
            db.add(student)
            changed = True

    default_teacher = db.scalar(select(Teacher).where(Teacher.login_id == DEFAULT_CLASSROOM_TEACHER_LOGIN_ID))
    if default_teacher is None:
        db.add(
            Teacher(
                classroom_id=classroom.classroom_id if classroom is not None else None,
                login_id=DEFAULT_CLASSROOM_TEACHER_LOGIN_ID,
                password_hash=hash_secret(DEFAULT_CLASSROOM_TEACHER_PASSWORD),
                display_name=DEFAULT_CLASSROOM_TEACHER_DISPLAY_NAME,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        changed = True
    else:
        teacher_changed = False
        if classroom is not None and default_teacher.classroom_id is None:
            default_teacher.classroom_id = classroom.classroom_id
            teacher_changed = True
        if not verify_secret(DEFAULT_CLASSROOM_TEACHER_PASSWORD, default_teacher.password_hash):
            default_teacher.password_hash = hash_secret(DEFAULT_CLASSROOM_TEACHER_PASSWORD)
            teacher_changed = True
        if default_teacher.updated_at is None:
            default_teacher.updated_at = now
            teacher_changed = True
        if teacher_changed:
            default_teacher.updated_at = now
        if teacher_changed:
            db.add(default_teacher)
            changed = True

    for other_teacher in db.scalars(select(Teacher)).all():
        teacher_changed = False
        if classroom is not None and other_teacher.classroom_id is None:
            other_teacher.classroom_id = classroom.classroom_id
            teacher_changed = True
        if other_teacher.updated_at is None:
            other_teacher.updated_at = now
            teacher_changed = True
        if teacher_changed:
            db.add(other_teacher)
            changed = True

    if changed:
        db.commit()


def _serialize_session(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("utf-8")
    signature = hmac.new(SESSION_SECRET.encode("utf-8"), encoded.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def read_session(request: Request) -> dict:
    value = request.cookies.get(SESSION_COOKIE_NAME)
    if not value or "." not in value:
        return {}
    encoded, signature = value.rsplit(".", 1)
    expected = hmac.new(SESSION_SECRET.encode("utf-8"), encoded.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return {}
    try:
        raw = base64.urlsafe_b64decode(encoded.encode("utf-8"))
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def _set_session(response, payload: dict) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        _serialize_session(payload),
        httponly=True,
        samesite="lax",
        max_age=28800,  # 8 時間でセッションを自動失効させる
    )


def login_classroom_session(response, classroom: Classroom) -> None:
    _set_session(
        response,
        {
            "role": "classroom",
            "classroom_id": classroom.classroom_id,
            "classroom_name": classroom.classroom_name,
            "login_at": datetime.utcnow().isoformat(),
        },
    )


def login_student_session(response, student: Student) -> None:
    _set_session(
        response,
        {
            "role": "student",
            "student_id": student.student_id,
            "classroom_id": student.classroom_id,
            "login_at": datetime.utcnow().isoformat(),
        },
    )


def login_teacher_session(response, teacher: Teacher) -> None:
    _set_session(
        response,
        {
            "role": "teacher",
            "teacher_id": teacher.teacher_id,
            "classroom_id": teacher.classroom_id,
            "login_at": datetime.utcnow().isoformat(),
        },
    )


def login_owner_session(response, owner: Owner) -> None:
    _set_session(
        response,
        {
            "role": "owner",
            "owner_id": owner.owner_id,
            "login_at": datetime.utcnow().isoformat(),
        },
    )


def logout_session(response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME)


def _redirect_for_missing_role(api: bool, login_path: str):
    if api:
        raise HTTPException(status_code=401, detail="login required")
    return RedirectResponse(url=login_path, status_code=303)


def require_classroom_login(request: Request, api: bool = False):
    session = read_session(request)
    role = session.get("role")
    if role is None:
        return _redirect_for_missing_role(api, "/login")
    if role != "classroom":
        raise HTTPException(status_code=403, detail="classroom access denied")
    return None


def require_student_login(request: Request, student_id: int, api: bool = False):
    session = read_session(request)
    role = session.get("role")
    current_student_id = session.get("student_id")
    if role is None:
        return _redirect_for_missing_role(api, "/login")
    if role != "student" or current_student_id != student_id:
        raise HTTPException(status_code=403, detail="student access denied")
    return None


def require_teacher_login(request: Request, api: bool = False):
    session = read_session(request)
    role = session.get("role")
    if role is None:
        return _redirect_for_missing_role(api, "/login")
    if role != "teacher":
        raise HTTPException(status_code=403, detail="teacher access denied")
    return None


def require_owner_login(request: Request, api: bool = False):
    session = read_session(request)
    role = session.get("role")
    if role is None:
        return _redirect_for_missing_role(api, "/login/owner")
    if role != "owner":
        raise HTTPException(status_code=403, detail="owner access denied")
    return None


def require_classroom_context(request: Request, api: bool = False) -> dict:
    session = read_session(request)
    role = session.get("role")
    if role is None:
        if api:
            raise HTTPException(status_code=401, detail="classroom login required")
        raise HTTPException(status_code=403, detail="classroom login required")
    if role != "classroom" or session.get("classroom_id") is None:
        raise HTTPException(status_code=403, detail="classroom login required")
    return session


def ensure_session_classroom_access(session: dict, classroom_id: int | None) -> None:
    if classroom_id is None or session.get("classroom_id") != classroom_id:
        raise HTTPException(status_code=403, detail="classroom access denied")
