"""教室運用: 契約・定員・削除周りの共通ロジック。"""

from __future__ import annotations

import json
import re
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import (
    Classroom,
    ClassroomContract,
    ClassroomDeletionLog,
    ConversationLog,
    FlashcardProgress,
    LearningLog,
    ListeningLog,
    ListeningMastery,
    ProblemReview,
    Student,
    StudentBoardCell,
    StudentState,
    Teacher,
    TeacherAnnotation,
    TestSession,
    UnitMastery,
)

ALLOWED_SUBJECT_KEYS = frozenset({"math_english", "math_english_conversation"})
CONTRACT_STATUS_KEYS = frozenset({"active", "paused", "cancel_scheduled", "cancelled"})
CLASSROOM_CODE_RE = re.compile(r"^[A-Za-z0-9]{4,8}$")


def normalize_classroom_code(raw: str) -> str:
    return (raw or "").strip().upper()


def validate_classroom_code_format(code: str) -> None:
    if not CLASSROOM_CODE_RE.match(code):
        raise HTTPException(
            status_code=422,
            detail="教室コードは英数字4〜8文字で入力してください。",
        )


def _derive_code_seed(login_id: str, classroom_id: int) -> str:
    alnum = re.sub(r"[^A-Za-z0-9]", "", (login_id or "").strip()) or "C"
    base = alnum.upper()[:8]
    if len(base) < 4:
        base = (f"{alnum.upper()}C{classroom_id}")[:8]
    return base[:8]


def allocate_classroom_code(db: Session, login_id: str, classroom_id: int) -> str:
    used = {
        str(c).strip().upper()
        for c in db.scalars(select(Classroom.code).where(Classroom.code.isnot(None))).all()
        if c and str(c).strip()
    }
    candidate = _derive_code_seed(login_id, classroom_id)
    n = 0
    while candidate.upper() in used:
        n += 1
        prefix = re.sub(r"[^A-Za-z0-9]", "", (login_id or "").strip()) or "C"
        prefix = prefix.upper()[:4]
        candidate = f"{prefix}{classroom_id + n:04d}"[-8:]
    final = candidate.upper()
    used.add(final)
    return final


def validate_allowed_subjects(value: str) -> str:
    v = value.strip()
    if v not in ALLOWED_SUBJECT_KEYS:
        raise HTTPException(status_code=422, detail="invalid allowed_subjects")
    return v


def validate_contract_status(value: str) -> str:
    v = value.strip()
    if v not in CONTRACT_STATUS_KEYS:
        raise HTTPException(status_code=422, detail="invalid contract_status")
    return v


def get_contract_for_classroom(db: Session, classroom_id: int) -> ClassroomContract:
    contract = db.scalar(select(ClassroomContract).where(ClassroomContract.classroom_id == classroom_id))
    if contract is None:
        raise HTTPException(status_code=500, detail="classroom contract missing")
    return contract


def count_students_for_classroom(db: Session, classroom_id: int) -> int:
    return db.scalar(
        select(func.count(Student.student_id)).where(Student.classroom_id == classroom_id)
    ) or 0


def assert_can_add_student(db: Session, classroom_id: int) -> None:
    contract = get_contract_for_classroom(db, classroom_id)
    current = count_students_for_classroom(db, classroom_id)
    if current >= contract.max_students:
        raise HTTPException(
            status_code=409,
            detail=f"student limit reached ({current}/{contract.max_students})",
        )


def classroom_login_allowed(classroom: Classroom) -> bool:
    if not classroom.is_active:
        return False
    if classroom.is_archived:
        return False
    return True


def dependency_counts_for_classroom(db: Session, classroom_id: int) -> dict[str, int]:
    student_ids = list(
        db.scalars(select(Student.student_id).where(Student.classroom_id == classroom_id)).all()
    )
    n_students = len(student_ids)
    n_teachers = db.scalar(select(func.count(Teacher.teacher_id)).where(Teacher.classroom_id == classroom_id)) or 0
    n_logs = 0
    n_conv = 0
    if student_ids:
        n_logs = db.scalar(select(func.count(LearningLog.log_id)).where(LearningLog.student_id.in_(student_ids))) or 0
        n_conv = db.scalar(select(func.count(ConversationLog.log_id)).where(ConversationLog.student_id.in_(student_ids))) or 0
    n_listen = db.scalar(select(func.count(ListeningLog.id)).where(ListeningLog.classroom_id == classroom_id)) or 0
    return {
        "students": n_students,
        "teachers": n_teachers,
        "learning_logs": n_logs,
        "conversation_logs": n_conv,
        "listening_logs": n_listen,
    }


def purge_classroom(db: Session, classroom_id: int) -> None:
    student_ids = list(
        db.scalars(select(Student.student_id).where(Student.classroom_id == classroom_id)).all()
    )
    if student_ids:
        db.execute(delete(ProblemReview).where(ProblemReview.student_id.in_(student_ids)))
        db.execute(delete(FlashcardProgress).where(FlashcardProgress.student_id.in_(student_ids)))
        db.execute(delete(StudentState).where(StudentState.student_id.in_(student_ids)))
        db.execute(delete(StudentBoardCell).where(StudentBoardCell.student_id.in_(student_ids)))
        db.execute(delete(UnitMastery).where(UnitMastery.student_id.in_(student_ids)))
        db.execute(delete(LearningLog).where(LearningLog.student_id.in_(student_ids)))
        db.execute(delete(ConversationLog).where(ConversationLog.student_id.in_(student_ids)))
        db.execute(delete(TeacherAnnotation).where(TeacherAnnotation.student_id.in_(student_ids)))
        db.execute(delete(TestSession).where(TestSession.student_id.in_(student_ids)))
        db.execute(delete(ListeningLog).where(ListeningLog.student_id.in_(student_ids)))
        db.execute(delete(ListeningMastery).where(ListeningMastery.student_id.in_(student_ids)))
        db.execute(delete(Student).where(Student.student_id.in_(student_ids)))
    db.execute(delete(ListeningLog).where(ListeningLog.classroom_id == classroom_id))
    db.execute(delete(ListeningMastery).where(ListeningMastery.classroom_id == classroom_id))
    db.execute(delete(Teacher).where(Teacher.classroom_id == classroom_id))
    db.execute(delete(ClassroomContract).where(ClassroomContract.classroom_id == classroom_id))
    db.execute(delete(Classroom).where(Classroom.classroom_id == classroom_id))


def log_classroom_deletion(
    db: Session,
    *,
    owner_id: int | None,
    classroom: Classroom,
    counts: dict[str, int],
) -> None:
    snap = json.dumps(counts, ensure_ascii=False)
    db.add(
        ClassroomDeletionLog(
            owner_id=owner_id,
            deleted_classroom_id=classroom.classroom_id,
            classroom_name_snapshot=classroom.classroom_name,
            external_classroom_id_snapshot=classroom.external_classroom_id,
            login_id_snapshot=classroom.login_id,
            dependency_snapshot=snap,
            deleted_at=datetime.utcnow().isoformat(),
        )
    )
