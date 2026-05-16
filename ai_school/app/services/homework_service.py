import json
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import Problem


def create_homework(
    db: Session,
    classroom_id: int,
    teacher_id: int,
    title: str,
    unit_id: str | None,
    due_date: str | None,
    target_student_ids: list[int] | None,
    num_problems: int = 5,
) -> int:
    problems = db.execute(
        text(
            "SELECT problem_id FROM problems "
            "WHERE status = 'approved' AND problem_type = 'practice' AND difficulty < 5 "
            + ("AND full_unit_id = :uid " if unit_id else "")
            + "ORDER BY RANDOM() LIMIT :n"
        ),
        {"uid": unit_id, "n": num_problems} if unit_id else {"n": num_problems},
    ).all()

    problem_ids = [r.problem_id for r in problems]
    now = datetime.utcnow().isoformat()

    result = db.execute(
        text(
            "INSERT INTO homework_sets "
            "(classroom_id, title, unit_id, due_date, problem_ids, target_student_ids, created_by, created_at) "
            "VALUES (:cid, :title, :uid, :due, :pids, :tids, :by, :now)"
        ),
        {
            "cid": classroom_id,
            "title": title,
            "uid": unit_id,
            "due": due_date,
            "pids": json.dumps(problem_ids),
            "tids": json.dumps(target_student_ids) if target_student_ids else None,
            "by": teacher_id,
            "now": now,
        },
    )
    db.commit()
    return result.lastrowid


def _get_target_ids(row_target: str | None) -> list[int] | None:
    if not row_target:
        return None
    try:
        ids = json.loads(row_target)
        if isinstance(ids, list) and ids:
            return [int(x) for x in ids]
        return None
    except Exception:
        return None


def list_homework_for_classroom(db: Session, classroom_id: int) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT hw_id, title, unit_id, due_date, problem_ids, target_student_ids, created_at "
            "FROM homework_sets WHERE classroom_id = :cid ORDER BY created_at DESC"
        ),
        {"cid": classroom_id},
    ).all()
    result = []
    for r in rows:
        tids = _get_target_ids(r.target_student_ids)
        if tids:
            names = db.execute(
                text("SELECT student_id, display_name FROM students WHERE student_id IN :ids"),
                {"ids": tuple(tids) if len(tids) > 1 else (tids[0], tids[0])},
            ).all()
            target_names = [n.display_name for n in names]
        else:
            target_names = []
        result.append({
            "hw_id": r.hw_id,
            "title": r.title,
            "unit_id": r.unit_id,
            "due_date": r.due_date,
            "problem_count": len(json.loads(r.problem_ids or "[]")),
            "target_student_ids": tids,
            "target_names": target_names,
            "created_at": r.created_at,
        })
    return result


def list_homework_for_student(db: Session, classroom_id: int, student_id: int) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT h.hw_id, h.title, h.unit_id, h.due_date, h.problem_ids, "
            "h.target_student_ids, h.created_at, "
            "s.sub_id, s.score, s.total, s.submitted_at "
            "FROM homework_sets h "
            "LEFT JOIN homework_submissions s "
            "  ON h.hw_id = s.hw_id AND s.student_id = :sid "
            "WHERE h.classroom_id = :cid ORDER BY h.created_at DESC"
        ),
        {"cid": classroom_id, "sid": student_id},
    ).all()
    result = []
    for r in rows:
        tids = _get_target_ids(r.target_student_ids)
        # 個別指定がある場合、対象生徒のみ表示
        if tids is not None and student_id not in tids:
            continue
        pids = json.loads(r.problem_ids or "[]")
        result.append({
            "hw_id": r.hw_id,
            "title": r.title,
            "unit_id": r.unit_id,
            "due_date": r.due_date,
            "problem_count": len(pids),
            "created_at": r.created_at,
            "submitted": r.sub_id is not None,
            "score": r.score,
            "total": r.total,
            "submitted_at": r.submitted_at,
        })
    return result


def get_homework_detail(db: Session, hw_id: int) -> dict | None:
    row = db.execute(
        text(
            "SELECT hw_id, classroom_id, title, unit_id, due_date, problem_ids, "
            "target_student_ids, created_at "
            "FROM homework_sets WHERE hw_id = :id"
        ),
        {"id": hw_id},
    ).first()
    if row is None:
        return None
    problem_ids = json.loads(row.problem_ids or "[]")
    problems = []
    for pid in problem_ids:
        p = db.get(Problem, pid)
        if p:
            problems.append(p)
    tids = _get_target_ids(row.target_student_ids)
    target_students = []
    if tids:
        from sqlalchemy import text as _t
        st_rows = db.execute(
            _t("SELECT student_id, display_name FROM students WHERE student_id IN :ids"),
            {"ids": tuple(tids) if len(tids) > 1 else (tids[0], tids[0])},
        ).all()
        target_students = [{"student_id": s.student_id, "display_name": s.display_name} for s in st_rows]
    return {
        "hw_id": row.hw_id,
        "classroom_id": row.classroom_id,
        "title": row.title,
        "unit_id": row.unit_id,
        "due_date": row.due_date,
        "problem_ids": problem_ids,
        "problems": problems,
        "target_student_ids": tids,
        "target_students": target_students,
        "created_at": row.created_at,
    }


def get_submission(db: Session, hw_id: int, student_id: int) -> dict | None:
    row = db.execute(
        text(
            "SELECT sub_id, answers, score, total, submitted_at "
            "FROM homework_submissions WHERE hw_id = :hw AND student_id = :sid"
        ),
        {"hw": hw_id, "sid": student_id},
    ).first()
    if row is None:
        return None
    return {
        "sub_id": row.sub_id,
        "answers": json.loads(row.answers or "{}"),
        "score": row.score,
        "total": row.total,
        "submitted_at": row.submitted_at,
    }


def get_homework_results(db: Session, hw_id: int) -> list[dict]:
    # 対象生徒が個別指定されている場合はその生徒に絞る
    hw_row = db.execute(
        text("SELECT target_student_ids FROM homework_sets WHERE hw_id = :hw"),
        {"hw": hw_id},
    ).first()
    tids = _get_target_ids(hw_row.target_student_ids) if hw_row else None

    if tids:
        rows = db.execute(
            text(
                "SELECT s.sub_id, s.student_id, st.display_name, s.score, s.total, s.submitted_at "
                "FROM homework_submissions s "
                "JOIN students st ON s.student_id = st.student_id "
                "WHERE s.hw_id = :hw AND s.student_id IN :ids "
                "ORDER BY s.submitted_at DESC"
            ),
            {"hw": hw_id, "ids": tuple(tids) if len(tids) > 1 else (tids[0], tids[0])},
        ).all()
    else:
        rows = db.execute(
            text(
                "SELECT s.sub_id, s.student_id, st.display_name, s.score, s.total, s.submitted_at "
                "FROM homework_submissions s "
                "JOIN students st ON s.student_id = st.student_id "
                "WHERE s.hw_id = :hw ORDER BY s.submitted_at DESC"
            ),
            {"hw": hw_id},
        ).all()
    return [
        {
            "sub_id": r.sub_id,
            "student_id": r.student_id,
            "display_name": r.display_name,
            "score": r.score,
            "total": r.total,
            "pct": int(r.score * 100 / r.total) if r.total else 0,
            "submitted_at": r.submitted_at,
        }
        for r in rows
    ]
