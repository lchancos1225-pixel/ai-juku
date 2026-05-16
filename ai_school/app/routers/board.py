from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Classroom, Student, Teacher
from ..paths import TEMPLATES_DIR
from ..services.auth_service import read_session
from ..utils.grade_display import grade_label

router = APIRouter(tags=["board"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["grade_label"] = grade_label

BOARD_TAG_LABELS: dict[str, str] = {
    "question": "質問",
    "note": "メモ・気づき",
    "praise": "がんばった！",
    "request": "先生へのお願い",
    "notice": "お知らせ（先生）",
}

_ALLOWED_TAGS = set(BOARD_TAG_LABELS)


def _get_classroom_id_from_session(request: Request) -> int | None:
    session = read_session(request)
    return session.get("classroom_id")


def _require_classroom_id(request: Request) -> int:
    cid = _get_classroom_id_from_session(request)
    if cid is None:
        raise HTTPException(status_code=403, detail="ログインが必要です")
    return cid


@router.get("/board/{classroom_id}", response_class=HTMLResponse)
def board_list(
    request: Request,
    classroom_id: int,
    db: Session = Depends(get_db),
):
    session = read_session(request)
    role = session.get("role")
    if role not in ("student", "teacher", "classroom"):
        return RedirectResponse(url="/login", status_code=303)

    session_classroom_id = session.get("classroom_id")
    if session_classroom_id != classroom_id:
        raise HTTPException(status_code=403, detail="アクセス権限がありません")

    classroom = db.get(Classroom, classroom_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="教室が見つかりません")

    rows = db.execute(
        text(
            "SELECT post_id, author_role, author_name, tag, body, is_hidden, created_at "
            "FROM board_posts "
            "WHERE classroom_id = :cid AND is_hidden = 0 "
            "ORDER BY created_at DESC LIMIT 100"
        ),
        {"cid": classroom_id},
    ).all()

    posts = [
        {
            "post_id": r.post_id,
            "author_role": r.author_role,
            "author_name": r.author_name,
            "tag": r.tag,
            "tag_label": BOARD_TAG_LABELS.get(r.tag, r.tag),
            "body": r.body,
            "created_at": r.created_at,
        }
        for r in rows
    ]

    return templates.TemplateResponse(
        "board.html",
        {
            "request": request,
            "classroom": classroom,
            "posts": posts,
            "role": role,
            "tag_labels": BOARD_TAG_LABELS,
            "auth_role": role,
            "session": session,
        },
    )


@router.post("/board/{classroom_id}/post")
def board_post(
    request: Request,
    classroom_id: int,
    tag: str = Form("question"),
    body: str = Form(...),
    db: Session = Depends(get_db),
):
    session = read_session(request)
    role = session.get("role")
    if role not in ("student", "teacher"):
        raise HTTPException(status_code=403, detail="ログインが必要です")
    if session.get("classroom_id") != classroom_id:
        raise HTTPException(status_code=403, detail="アクセス権限がありません")

    if tag not in _ALLOWED_TAGS:
        tag = "question"

    body = body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="本文を入力してください")
    if len(body) > 1000:
        raise HTTPException(status_code=400, detail="本文は1000文字以内にしてください")

    if role == "student":
        author_id = session.get("student_id") or 0
        student = db.get(Student, author_id)
        author_name = student.display_name if student else "生徒"
    else:
        author_id = session.get("teacher_id") or 0
        teacher = db.get(Teacher, author_id)
        author_name = teacher.login_id if teacher else "先生"

    now = datetime.utcnow().isoformat()
    db.execute(
        text(
            "INSERT INTO board_posts "
            "(classroom_id, author_role, author_id, author_name, tag, body, created_at) "
            "VALUES (:cid, :role, :aid, :name, :tag, :body, :now)"
        ),
        {
            "cid": classroom_id,
            "role": role,
            "aid": author_id,
            "name": author_name,
            "tag": tag,
            "body": body,
            "now": now,
        },
    )
    db.commit()
    return RedirectResponse(url=f"/board/{classroom_id}", status_code=303)


@router.post("/board/{classroom_id}/hide/{post_id}")
def board_hide(
    request: Request,
    classroom_id: int,
    post_id: int,
    db: Session = Depends(get_db),
):
    session = read_session(request)
    role = session.get("role")
    if role != "teacher":
        raise HTTPException(status_code=403, detail="先生のみ非表示にできます")
    if session.get("classroom_id") != classroom_id:
        raise HTTPException(status_code=403, detail="アクセス権限がありません")

    db.execute(
        text("UPDATE board_posts SET is_hidden = 1 WHERE post_id = :pid AND classroom_id = :cid"),
        {"pid": post_id, "cid": classroom_id},
    )
    db.commit()
    return RedirectResponse(url=f"/board/{classroom_id}", status_code=303)


def get_recent_board_posts(db: Session, classroom_id: int, limit: int = 5) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT post_id, author_role, author_name, tag, body, created_at "
            "FROM board_posts "
            "WHERE classroom_id = :cid AND is_hidden = 0 "
            "ORDER BY created_at DESC LIMIT :lim"
        ),
        {"cid": classroom_id, "lim": limit},
    ).all()
    return [
        {
            "post_id": r.post_id,
            "author_role": r.author_role,
            "author_name": r.author_name,
            "tag": r.tag,
            "tag_label": BOARD_TAG_LABELS.get(r.tag, r.tag),
            "body": r.body,
            "created_at": r.created_at,
        }
        for r in rows
    ]
