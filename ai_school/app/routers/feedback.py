from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Feedback
from ..services.auth_service import read_session, require_owner_login
from ..paths import TEMPLATES_DIR

router = APIRouter(tags=["feedback"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)

CATEGORY_LABELS = {
    "bug": "🐛 バグ報告",
    "improvement": "💡 改善要望",
    "other": "💬 その他",
}


@router.post("/feedback", response_class=JSONResponse)
def submit_feedback(
    request: Request,
    category: str = Form(...),
    message: str = Form(...),
    page_url: str = Form(""),
    db: Session = Depends(get_db),
):
    if category not in CATEGORY_LABELS:
        return JSONResponse({"ok": False, "error": "invalid category"}, status_code=400)
    if not message.strip():
        return JSONResponse({"ok": False, "error": "empty message"}, status_code=400)

    feedback = Feedback(
        category=category,
        message=message.strip()[:1000],
        page_url=page_url[:500] if page_url else None,
        created_at=datetime.now(timezone.utc).isoformat(),
        is_resolved=False,
    )
    db.add(feedback)
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/owner/feedbacks/{feedback_id}/resolve", response_class=JSONResponse)
def resolve_feedback(
    feedback_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    auth = require_owner_login(request)
    if auth is not None:
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

    feedback = db.get(Feedback, feedback_id)
    if not feedback:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

    feedback.is_resolved = not feedback.is_resolved
    db.commit()
    return JSONResponse({"ok": True, "is_resolved": feedback.is_resolved})


@router.get("/owner/feedbacks", response_class=HTMLResponse)
def owner_feedbacks(request: Request, db: Session = Depends(get_db)):
    auth = require_owner_login(request)
    if auth is not None:
        return auth

    session = read_session(request)
    from ..models import Owner
    owner = db.get(Owner, session.get("owner_id")) if session.get("owner_id") else None

    feedbacks = db.scalars(
        select(Feedback).order_by(desc(Feedback.feedback_id))
    ).all()

    unresolved = sum(1 for f in feedbacks if not f.is_resolved)

    return templates.TemplateResponse("owner_feedbacks.html", {
        "request": request,
        "owner": owner,
        "feedbacks": feedbacks,
        "unresolved": unresolved,
        "category_labels": CATEGORY_LABELS,
    })
