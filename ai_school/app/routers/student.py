import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Classroom, Flashcard, FlashcardProgress, LearningLog, Student, StudentBoardCell, StudentState, UnitDependency, UnitMastery
from ..schemas import OCRRequest, OCRResponse, SubmissionResult
from ..services.auth_service import ensure_session_classroom_access, read_session, require_student_login
from ..services.diagram_display_name_service import get_diagram_display_info
from ..services.diagram_service import render_problem_diagram_for_route
from ..services.error_pattern_service import classify_error_pattern
from ..services.grading_service import grade_answer, grade_answer_detailed, update_student_discovered_nuances, get_student_badges_display
from ..services.intervention_service import build_intervention_snapshot
from ..services.review_service import count_due_reviews, get_next_review_problem, update_review_schedule
from ..services.ai_service import generate_text
from ..services.misconception_inference_service import infer_misconception
from ..services.counterexample_service import generate_socratic_questions
from ..services.session_service import get_today_session_info
from ..services.lecture_step_service import get_or_generate_steps
from .flashcard import UNIT_DISPLAY_NAMES, count_due_flashcards
from ..services.ocr_service import recognize_handwritten_answer_detail
from ..services.problem_service import (
    consume_teacher_override_problem,
    get_approved_challenge_problem,
    get_first_problem,
    get_first_problem_for_unit,
    get_problem_by_id,
    get_unit_label_map,
)
from ..services.progress_service import build_student_progress_view
from ..services.listening_service import build_listening_mastery_rows
from ..services.routing_service import (
    ADVANCE_ROUTE,
    FALLBACK_ROUTE,
    REINFORCE_ROUTE,
    choose_next_problem,
    get_dominant_error_pattern,
    get_recommended_route,
)
from ..services.adaptive_problem_service import generate_adaptive_problem_for_subject
from ..services.state_service import (
    apply_practice_attempt_to_unit_mastery,
    build_practice_submit_intervention_context,
    build_student_summary,
    effective_unit_unlock,
    ensure_student_state,
    update_student_state,
)
from ..services.test_service import (
    check_and_finalize_test_if_expired,
    complete_test_session_normal,
    count_pending_deferred,
    defer_test_problem,
    get_active_test_session,
    get_current_test_problem,
    get_test_remaining_seconds,
    get_test_result_detail,
    get_test_session_by_id,
    record_test_answer,
    should_trigger_test,
    start_test_session,
    scope_label as test_scope_label,
)
from ..services.answer_input_spec_service import build_answer_panel_template_context
from ..services.math_text_service import pair_for_student_numeric_result_display
from ..services.text_display_service import render_math_text
from ..paths import TEMPLATES_DIR

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/students", tags=["students"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["render_math_text"] = render_math_text
templates.env.filters["from_json"] = lambda s: json.loads(s) if s else []


# Phase 3-A: Meinメッセージキャッシュ（同じ文脈なら同じメッセージ）
_mein_message_cache: dict[str, str] = {}


def _generate_mein_message(streak: int, mastery_pct: float, unit_name: str) -> str | None:
    """MeinのひとことをAI生成。キャッシュ付き。"""
    cache_key = f"streak_{streak}_mastery_{mastery_pct:.0f}"
    if cache_key in _mein_message_cache:
        return _mein_message_cache[cache_key]

    system_prompt = """あなたはAI-Jukuのキャラクター「Mein」です。
生徒の学習状況に応じて、短く励ますメッセージ（20文字以内）を生成してください。
絵文字を1つ使ってください。

例:
- 「今日で3日連続だね！🔥 この調子！"
- 「この単元あと少し！💪 がんばれ！"
- """

    user_prompt = f"連続学習日数: {streak}日、単元習熟度: {mastery_pct:.0f}%、単元名: {unit_name}"

    message = generate_text(system_prompt, user_prompt, max_output_tokens=60)
    if message:
        _mein_message_cache[cache_key] = message
    return message


def _resolve_current_problem(db: Session, student_id: int):
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")

    state = ensure_student_state(db, student)
    override_problem = consume_teacher_override_problem(db, state)
    if override_problem is not None:
        state.current_unit = override_problem.full_unit_id or override_problem.unit
        state.current_level = override_problem.difficulty
        db.commit()
        db.refresh(state)
        return student, state, override_problem

    # 激ムズ問題（ショップ購入）をキューから取り出す
    if state.pending_challenge_problem_id is not None:
        challenge = get_problem_by_id(db, state.pending_challenge_problem_id)
        state.pending_challenge_problem_id = None
        db.add(state)
        db.commit()
        db.refresh(state)
        if challenge is not None:
            return student, state, challenge

    if state.last_problem_id:
        current_problem = get_problem_by_id(db, state.last_problem_id)
        if current_problem is not None:
            recent_log_stmt = (
                select(LearningLog)
                .where(LearningLog.student_id == student_id, LearningLog.problem_id == state.last_problem_id)
                .order_by(desc(LearningLog.created_at))
                .limit(1)
            )
            recent_log = db.scalar(recent_log_stmt)
            if recent_log is not None:
                next_problem = choose_next_problem(db, state, current_problem)
                if next_problem is not None:
                    return student, state, next_problem
                # choose_next が None (全問題消化) → 単元先頭へリセット

    current_problem = get_first_problem_for_unit(db, state.current_unit) if state.current_unit else None
    if current_problem is None:
        current_problem = get_first_problem(db)
    if current_problem is None:
        raise HTTPException(status_code=500, detail="No problems loaded")
    state.current_unit = current_problem.full_unit_id or current_problem.unit
    state.current_level = current_problem.difficulty
    db.add(state)
    db.commit()
    db.refresh(state)
    return student, state, current_problem


def _resolve_math_problem(db: Session, student_id: int):
    """常に数学問題を返す。現在のユニットが英語でも数学問題を優先する。"""
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access_from_db(db, student)

    state = ensure_student_state(db, student)

    # 直前が数学問題ならそのまま次の数学問題へ
    if state.last_problem_id:
        current_problem = get_problem_by_id(db, state.last_problem_id)
        if current_problem is not None and current_problem.subject == "math":
            recent_log_stmt = (
                select(LearningLog)
                .where(
                    LearningLog.student_id == student_id,
                    LearningLog.problem_id == state.last_problem_id,
                )
                .order_by(desc(LearningLog.created_at))
                .limit(1)
            )
            recent_log = db.scalar(recent_log_stmt)
            if recent_log is not None:
                next_problem = choose_next_problem(db, state, current_problem)
                if next_problem is not None and next_problem.subject == "math":
                    return student, state, next_problem

    # 数学単元の最初の問題へフォールバック
    math_unit = (
        state.current_unit
        if state.current_unit and not state.current_unit.startswith("eng_")
        else None
    )
    problem = get_first_problem_for_unit(db, math_unit) if math_unit else None
    if problem is None:
        problem = get_first_problem(db)
    if problem is None:
        raise HTTPException(status_code=500, detail="No math problems available")
    return student, state, problem


def _ensure_student_classroom_access_from_db(db: Session, student: Student) -> None:
    pass  # DB-only path: no request session check needed for internal resolvers


def _ensure_student_classroom_access(request: Request, student: Student) -> None:
    session = read_session(request)
    ensure_session_classroom_access(session, student.classroom_id)


@router.get("/me/progress", include_in_schema=False)
def my_progress(request: Request):
    session = read_session(request)
    if session.get("role") is None:
        return RedirectResponse(url="/login", status_code=303)
    if session.get("role") != "student" or session.get("student_id") is None:
        raise HTTPException(status_code=403, detail="student access denied")
    return RedirectResponse(url=f"/students/{session['student_id']}/progress", status_code=303)


@router.get("/{student_id}", response_class=HTMLResponse)
def student_home(request: Request, student_id: int, hint_level: int = 0, subject: str | None = None, db: Session = Depends(get_db)):
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth

    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)

    # テストセッション進行中ならテスト問題を表示
    active_test = get_active_test_session(db, student_id)
    if active_test is not None:
        if check_and_finalize_test_if_expired(db, active_test):
            return RedirectResponse(
                url=f"/students/{student_id}/test/{active_test.session_id}/result?time_up=1",
                status_code=303,
            )
        state = ensure_student_state(db, student)
        test_problem = get_current_test_problem(db, active_test)
        if test_problem is None:
            if complete_test_session_normal(db, active_test):
                return RedirectResponse(
                    url=f"/students/{student_id}/test/{active_test.session_id}/result",
                    status_code=303,
                )
            active_test.status = "completed"
            db.commit()
            return RedirectResponse(
                url=f"/students/{student_id}/test/{active_test.session_id}/result",
                status_code=303,
            )
        problem_ids: list[int] = json.loads(active_test.problem_ids)
        answered: list[dict] = json.loads(active_test.answers)
        test_current_q = len(answered) + 1
        test_total_q = len(problem_ids)
        test_remaining_sec = get_test_remaining_seconds(active_test)
        test_pending_deferred = count_pending_deferred(active_test)
        unit_labels = get_unit_label_map(db)
        diagram_display = get_diagram_display_info(test_problem, route="student")
        classroom = db.get(Classroom, student.classroom_id)

        # 今日の回答数を計算（テストセッション用）
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        today_count_row = db.execute(
            select(LearningLog).where(
                LearningLog.student_id == student_id,
                LearningLog.created_at >= datetime.strptime(today_str, "%Y-%m-%d"),
            )
        ).unique().all()
        today_answer_count = len(today_count_row)
        quest_goal = 10

        return templates.TemplateResponse(
            "student_home.html",
            {
                "request": request,
                "student": student,
                "state": state,
                "problem": test_problem,
                "diagram_svg": render_problem_diagram_for_route(test_problem, "student"),
                "diagram_display": diagram_display,
                "unit_labels": unit_labels,
                "hint_level": 0,
                "is_student_view": True,
                "active_test": active_test,
                "test_current_q": test_current_q,
                "test_total_q": test_total_q,
                "test_answered_count": len(answered),
                "test_remaining_sec": test_remaining_sec,
                "test_pending_deferred": test_pending_deferred,
                "test_scope_label": test_scope_label(active_test.test_scope),
                "test_suggestion": None,
                "classroom_name": classroom.classroom_name if classroom else None,
                "today_answer_count": today_answer_count,
                "quest_goal": quest_goal,
                **build_answer_panel_template_context(test_problem),
            },
        )

    # 通常練習モード
    if subject == "math":
        student, state, problem = _resolve_math_problem(db, student_id)
    else:
        student, state, problem = _resolve_current_problem(db, student_id)
    unit_id = state.current_unit or problem.full_unit_id or problem.unit
    test_suggestion = should_trigger_test(db, student_id, unit_id) if unit_id else None

    unit_labels = get_unit_label_map(db)
    diagram_display = get_diagram_display_info(problem, route="student")
    hint_level = max(0, min(2, hint_level))
    classroom = db.get(Classroom, student.classroom_id)
    review_count = count_due_reviews(db, student_id)
    flashcard_review_count = count_due_flashcards(db, student_id)
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    today_count_row = db.execute(
        select(LearningLog).where(
            LearningLog.student_id == student_id,
            LearningLog.created_at >= datetime.strptime(today_str, "%Y-%m-%d"),
        )
    ).unique().all()
    today_answer_count = len(today_count_row)
    quest_goal = 10

    # テストセッション進行中ならテスト問題を表示
    active_test = get_active_test_session(db, student_id)

    # ミニボード & 習熟データ（Phase 2-A）
    mini_board_cells_raw = db.scalars(
        select(StudentBoardCell)
        .where(StudentBoardCell.student_id == student_id, StudentBoardCell.unit_id == unit_id)
        .order_by(StudentBoardCell.cell_index.asc())
    ).all() if unit_id else []
    mini_board_cells = [
        {"cell_type": c.cell_type, "g_earned": c.g_earned}
        for c in mini_board_cells_raw[-14:]
    ]
    unit_mastery_obj = db.get(UnitMastery, (student_id, unit_id)) if unit_id else None
    mastery_pct = min(int((unit_mastery_obj.mastery_score if unit_mastery_obj else 0.0) / 0.55 * 100), 100)

    # Phase 3-A: Meinメッセージ生成
    unit_name = unit_labels.get(unit_id, unit_id) if unit_id else ""
    mein_message = _generate_mein_message(
        streak=(state.login_streak or 0),
        mastery_pct=mastery_pct,
        unit_name=unit_name
    )

    # Phase 3-B: 推奨ルート取得
    recommended_route = get_recommended_route(db, state, problem)

    # 神システム: 7分セッション情報
    try:
        session_info = get_today_session_info(db, student_id)
    except Exception:
        session_info = None

    return templates.TemplateResponse(
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
            "mini_board_cells": mini_board_cells,
            "mastery_pct": mastery_pct,
            "mein_message": mein_message,
            "recommended_route": recommended_route,
            "ADVANCE_ROUTE": ADVANCE_ROUTE,
            "REINFORCE_ROUTE": REINFORCE_ROUTE,
            "FALLBACK_ROUTE": FALLBACK_ROUTE,
            "session_info": session_info,
            **build_answer_panel_template_context(problem),
        },
    )


@router.get("/{student_id}/review", response_class=HTMLResponse)
def review_session(request: Request, student_id: int, db: Session = Depends(get_db)):
    """忘却曲線に基づく復習セッション。今日期限の問題を1問ずつ出題する。"""
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth

    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)

    problem = get_next_review_problem(db, student_id)
    if problem is None:
        # 復習ゼロ → ホームへリダイレクト
        return RedirectResponse(url=f"/students/{student_id}", status_code=303)

    remaining = count_due_reviews(db, student_id)
    unit_labels = get_unit_label_map(db)
    diagram_display = get_diagram_display_info(problem, route="student")

    return templates.TemplateResponse(
        "student_review.html",
        {
            "request": request,
            "student": student,
            "problem": problem,
            "diagram_svg": render_problem_diagram_for_route(problem, "student"),
            "diagram_display": diagram_display,
            "unit_labels": unit_labels,
            "review_remaining": remaining,
            "is_student_view": True,
            **build_answer_panel_template_context(problem),
        },
    )


@router.get("/{student_id}/progress", response_class=HTMLResponse)
def student_progress(request: Request, student_id: int, db: Session = Depends(get_db)):
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth

    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)

    progress_view = build_student_progress_view(db, student_id)
    if progress_view is None:
        raise HTTPException(status_code=404, detail="Student not found")

    # ── 単語帳進捗を集計 ─────────────────────────────────────────
    student_grade = student.grade  # 7/8/9
    all_cards = db.query(Flashcard).filter(Flashcard.grade == student_grade).all()
    prog_map: dict[int, int] = {
        p.flashcard_id: p.stage_cleared
        for p in db.query(FlashcardProgress).filter(
            FlashcardProgress.student_id == student_id
        ).all()
    }
    # ユニット別集計
    unit_totals: dict[str | None, int] = {}
    unit_done: dict[str | None, int] = {}
    for card in all_cards:
        uid = card.unit_id
        unit_totals[uid] = unit_totals.get(uid, 0) + 1
        if prog_map.get(card.flashcard_id, 0) >= 4:
            unit_done[uid] = unit_done.get(uid, 0) + 1

    def _flashcard_unit_sort_key(item: tuple) -> tuple:
        uid, _total = item
        return (uid is None, str(uid or ""))

    def _flashcard_unit_label(uid: str | None) -> str:
        if uid is None:
            return "未分類"
        return UNIT_DISPLAY_NAMES.get(uid, uid.replace("eng_", "").replace("_", " ").title())

    flashcard_units = [
        {
            "unit_id": uid,
            "display_name": _flashcard_unit_label(uid),
            "total": total,
            "done": unit_done.get(uid, 0),
            "percent": round(unit_done.get(uid, 0) / total * 100) if total else 0,
        }
        for uid, total in sorted(unit_totals.items(), key=_flashcard_unit_sort_key)
    ]
    total_all = sum(unit_totals.values())
    done_all  = sum(unit_done.values())
    started_all = sum(
        1 for card in all_cards
        if prog_map.get(card.flashcard_id, 0) > 0
    )
    flashcard_summary = {
        "total":   total_all,
        "done":    done_all,
        "started": started_all,
        "percent": round(done_all / total_all * 100) if total_all else 0,
    }
    # ────────────────────────────────────────────────────────────

    listening_mastery = build_listening_mastery_rows(db, student_id, student_grade)

    return templates.TemplateResponse(
        "student_progress.html",
        {
            "request": request,
            "progress": progress_view,
            "student": progress_view["student"],
            "flashcard_summary": flashcard_summary,
            "flashcard_units": flashcard_units,
            "listening_mastery": listening_mastery,
            "student_id": student_id,
            "is_student_view": True,
            "title": "あなたの進みぐあい",
            "heading": "AI塾 QRelDo",
        },
    )

@router.get("/{student_id}/units", response_class=HTMLResponse)
def unit_list(request: Request, student_id: int, db: Session = Depends(get_db)):
    """単元選択ページ"""
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth

    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)

    from ..models import UnitMastery, Classroom
    classroom = db.get(Classroom, student.classroom_id) if student.classroom_id else None
    state = ensure_student_state(db, student)
    unlock_mode, unlock_up_to = effective_unit_unlock(classroom, state)

    units = db.scalars(
        select(UnitDependency)
        .where(UnitDependency.subject == "math")
        .order_by(UnitDependency.display_order.asc())
    ).all()

    # unlock_up_to の display_order を取得
    unlock_limit_order = None
    if unlock_mode != "full" and unlock_up_to:
        for u in units:
            if u.unit_id == unlock_up_to:
                unlock_limit_order = u.display_order
                break

    unit_rows = []
    for u in units:
        mastery = db.get(UnitMastery, (student_id, u.unit_id))
        pre_mastery = db.get(UnitMastery, (student_id, u.prerequisite_unit_id)) if u.prerequisite_unit_id else None

        if unlock_mode == "full":
            unlocked = True
        elif unlock_limit_order is not None:
            unlocked = u.display_order <= unlock_limit_order
        else:
            unlocked = (
                u.prerequisite_unit_id is None
                or (pre_mastery is not None and pre_mastery.mastery_score >= 0.40)
            )

        unit_rows.append({
            "unit_id": u.unit_id,
            "display_name": u.display_name,
            "intro_html": u.intro_html,
            "unlocked": unlocked,
            "grade": u.grade if u.grade else 7,
            "mastery_score": round((mastery.mastery_score if mastery else 0.0) * 100),
            "status": (
                "mastered" if mastery and mastery.mastery_score >= 0.55
                else "in_progress" if mastery and (mastery.correct_count + mastery.wrong_count) > 0
                else "not_started"
            ),
        })

    # 英語単元も取得
    eng_units_raw = db.scalars(
        select(UnitDependency)
        .where(UnitDependency.subject == "english")
        .order_by(UnitDependency.display_order.asc())
    ).all()
    eng_unit_rows = []
    for u in eng_units_raw:
        mastery = db.get(UnitMastery, (student_id, u.unit_id))
        pre_mastery = db.get(UnitMastery, (student_id, u.prerequisite_unit_id)) if u.prerequisite_unit_id else None
        if unlock_mode == "full":
            unlocked = True
        elif unlock_limit_order is not None:
            unlocked = u.display_order <= unlock_limit_order
        else:
            unlocked = (
                u.prerequisite_unit_id is None
                or (pre_mastery is not None and pre_mastery.mastery_score >= 0.40)
            )
        eng_unit_rows.append({
            "unit_id": u.unit_id,
            "display_name": u.display_name,
            "unlocked": unlocked,
            "grade": u.grade if u.grade else 7,
            "mastery_score": round((mastery.mastery_score if mastery else 0.0) * 100),
            "status": (
                "mastered" if mastery and mastery.mastery_score >= 0.55
                else "in_progress" if mastery and (mastery.correct_count + mastery.wrong_count) > 0
                else "not_started"
            ),
        })

    return templates.TemplateResponse(
        "student_unit_list.html",
        {
            "request": request,
            "student": student,
            "current_unit_id": state.current_unit,
            "units": unit_rows,
            "eng_units": eng_unit_rows,
            "is_student_view": True,
        },
    )


@router.post("/{student_id}/switch_unit")
def switch_unit(request: Request, student_id: int, unit_id: str = Form(...), db: Session = Depends(get_db)):
    """生徒が単元を切り替える（HTMX対応: HX-Redirectでページ遷移なし）"""
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth

    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)

    unit = db.get(UnitDependency, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="Unit not found")

    state = ensure_student_state(db, student)
    state.current_unit = unit_id
    state.current_level = 1
    state.last_problem_id = None
    db.add(state)
    db.commit()

    # HTMX対応: HX-Redirectヘッダーでページ遷移なしリロード
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        return Response(
            status_code=200,
            headers={"HX-Redirect": f"/students/{student_id}"}
        )
    return RedirectResponse(url=f"/students/{student_id}", status_code=303)


@router.get("/{student_id}/lecture/{unit_id}", response_class=HTMLResponse)
def unit_lecture(request: Request, student_id: int, unit_id: str, db: Session = Depends(get_db)):
    """単元レクチャーページ"""
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth

    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)

    unit = db.get(UnitDependency, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="Unit not found")

    try:
        lecture_steps = get_or_generate_steps(db, unit)
    except (json.JSONDecodeError, ValueError, RuntimeError) as e:
        from ..services.lecture_step_service import _make_fallback_steps
        logger.warning("unit_lecture fallback: unit=%s err=%s", unit.unit_id, e)
        lecture_steps = _make_fallback_steps(unit.display_name)

    from ..services.unit_intro_service import get_or_generate_intro
    intro_html = get_or_generate_intro(db, unit)

    return templates.TemplateResponse(
        "student_lecture.html",
        {
            "request": request,
            "student": student,
            "unit": unit,
            "is_student_view": True,
            "lecture_steps": lecture_steps,
            "intro_html": intro_html,
        },
    )

@router.post("/{student_id}/ocr", response_model=OCRResponse)
def ocr_answer(request: Request, student_id: int, payload: OCRRequest, db: Session = Depends(get_db)):
    require_student_login(request, student_id, api=True)
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)
    result = recognize_handwritten_answer_detail(payload.image_data_url)
    return OCRResponse(
        status="ok" if result.ok else "fallback",
        recognized_text=result.text,
        error=result.error,
    )


@router.post("/{student_id}/submit", response_class=HTMLResponse)
def submit_answer(
    request: Request,
    student_id: int,
    problem_id: int = Form(...),
    answer: str = Form(...),
    elapsed_sec: int = Form(0),
    hint_used: int = Form(0),
    test_session_id: int | None = Form(None),
    canvas_image: str = Form(""),
    review_mode: int = Form(0),
    db: Session = Depends(get_db),
):
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)

    active_check = None
    if test_session_id is not None:
        active_check = get_test_session_by_id(db, test_session_id)
        if active_check is not None and (
            active_check.student_id != student_id or active_check.status != "in_progress"
        ):
            active_check = None
    if active_check is None:
        active_check = get_active_test_session(db, student_id)
    if active_check is not None and active_check.status == "in_progress":
        if check_and_finalize_test_if_expired(db, active_check):
            return RedirectResponse(
                url=f"/students/{student_id}/test/{active_check.session_id}/result?time_up=1",
                status_code=303,
            )

    state = ensure_student_state(db, student)
    problem = get_problem_by_id(db, problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    hint_used = max(0, min(2, int(hint_used)))
    grading_result = grade_answer_detailed(problem, answer)
    is_correct = grading_result["judgment"] == "correct"

    # near_missの場合、バッジ獲得処理
    new_badges = []
    if grading_result["judgment"] == "near_miss" and grading_result["near_miss_info"]:
        hint_key = grading_result["near_miss_info"]["hint_key"]
        _, new_badges = update_student_discovered_nuances(state, hint_key, False)
        db.add(state)  # stateの更新をコミットするため
    elif grading_result["judgment"] == "correct" and grading_result.get("near_miss_info"):
        # 正解の場合、以前のnear_missに対する克服バッジチェック
        hint_key = grading_result["near_miss_info"]["hint_key"]
        _, overcome_badges = update_student_discovered_nuances(state, hint_key, True)
        new_badges.extend(overcome_badges)
        if overcome_badges:
            db.add(state)

    # canvas_image のバリデーション（data URL 形式のみ許可、上限 500KB 相当）
    _canvas = canvas_image if canvas_image.startswith("data:image/") and len(canvas_image) < 700_000 else None

    # 常に LearningLog を記録（練習・テスト共通）
    log = LearningLog(
        student_id=student_id,
        problem_id=problem.problem_id,
        answer_payload=answer,
        is_correct=is_correct,
        elapsed_sec=elapsed_sec,
        attempt_count=1,
        hint_used=hint_used,
        canvas_image=_canvas,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    active_test = None
    if test_session_id is not None:
        active_test = get_test_session_by_id(db, test_session_id)
        if active_test is not None and (
            active_test.student_id != student_id or active_test.status != "in_progress"
        ):
            active_test = None
    if active_test is None:
        active_test = get_active_test_session(db, student_id)

    if active_test is not None and active_test.status == "in_progress":
        log.route_decision = None
        log.error_pattern = None
        log.intervention_type = None
        db.add(log)
        db.commit()
        is_complete = record_test_answer(
            db,
            session=active_test,
            problem_id=problem.problem_id,
            answer=answer,
            is_correct=is_correct,
            elapsed_sec=elapsed_sec,
            hint_used=hint_used,
        )
        if is_complete:
            return RedirectResponse(
                url=f"/students/{student_id}/test/{active_test.session_id}/result",
                status_code=303,
            )
        return RedirectResponse(url=f"/students/{student_id}", status_code=303)

    # Phase 2-B: マスタリー前スナップショット（ユニットクリア検出用）
    _unit_key = problem.full_unit_id or problem.unit
    _mastery_before_obj = db.get(UnitMastery, (student_id, _unit_key))
    mastery_score_before = _mastery_before_obj.mastery_score if _mastery_before_obj else 0.0

    apply_practice_attempt_to_unit_mastery(
        db,
        student_id,
        problem.full_unit_id or problem.unit,
        is_correct,
        hint_used,
        elapsed_sec,
    )
    db.flush()

    route_decision = get_recommended_route(db, state, problem)
    log.route_decision = route_decision
    if not is_correct:
        log.error_pattern = classify_error_pattern(problem, answer, route_decision, hint_used, elapsed_sec)

    db.add(log)
    db.flush()

    ictx = build_practice_submit_intervention_context(db, student_id)
    intervention_snapshot = build_intervention_snapshot(
        db,
        student_id=student_id,
        diagnostic_label=ictx["diagnostic_label"],
        dominant_error_pattern=ictx["dominant_error_pattern"],
        hint_dependency_level=ictx["hint_dependency_level"],
        speed_profile=ictx["speed_profile"],
        fallback_risk_level=ictx["fallback_risk_level"],
        recommended_route=route_decision,
        recent_results=ictx["recent_results"],
    )
    log.intervention_type = intervention_snapshot["recommended_intervention"]

    # 誤概念フィンガープリント推論（不正解時のみ）
    if not is_correct:
        try:
            m_tag, m_detail = infer_misconception(
                question_text=problem.question_text,
                answer=answer,
                correct_answer=problem.correct_answer,
                subject=problem.subject or "math",
                hint_text=getattr(problem, "hint_text", None),
                explanation_base=getattr(problem, "explanation_base", None),
            )
            log.misconception_tag = m_tag
            log.misconception_detail = m_detail
        except Exception as _e:
            logger.debug("misconception inference skipped: %s", _e)

    db.add(log)
    db.commit()
    db.refresh(log)

    # ----------------------------------------------------------------
    # 通常練習モード
    # ----------------------------------------------------------------
    # Phase C: 同パターン3連続ミス → 個人適応問題（連続2問まで、その後は通常ルート）
    # subject ごとに AI adaptive を分離（英語演習中に数学 adaptive を呼ばない）
    next_problem = None
    is_adapted = False
    streak = int(getattr(state, "adaptive_streak", 0) or 0)
    if not is_correct and log.error_pattern and streak < 2:
        dominant_unit = problem.full_unit_id if problem.full_unit_id else problem.unit
        dominant = get_dominant_error_pattern(db, student_id, dominant_unit, consecutive=3)
        if dominant == log.error_pattern:
            subj = (problem.subject or "").strip().lower()
            if subj in ("math", "english"):
                adaptive = generate_adaptive_problem_for_subject(
                    db,
                    student_id,
                    problem,
                    dominant,
                    state=state,
                    adaptive_streak=streak,
                )
                if adaptive is not None:
                    next_problem = adaptive
                    is_adapted = True
                    uk = dominant_unit
                    state.adaptive_last_generated_key = f"{uk}|{dominant}"
                    state.adaptive_last_generated_at = datetime.utcnow().replace(microsecond=0).isoformat()
                    logger.info(
                        "[phase_c] adaptive_applied student=%s subject=%s next_problem_id=%s",
                        student_id,
                        subj,
                        next_problem.problem_id,
                    )
                elif subj == "english":
                    logger.info(
                        "[phase_c_english] adaptive_failed_fallback_routing student=%s dominant=%s",
                        student_id,
                        dominant,
                    )
                else:
                    logger.info(
                        "[phase_c_math] adaptive_failed_fallback_routing student=%s dominant=%s",
                        student_id,
                        dominant,
                    )
            else:
                logger.info(
                    "[phase_c] skip_ai_adaptive subject=%r student=%s",
                    problem.subject,
                    student_id,
                )
    if next_problem is None:
        next_problem = choose_next_problem(db, state, problem)
    if is_adapted:
        state.adaptive_streak = streak + 1
    else:
        state.adaptive_streak = 0
    if is_correct:
        state.adaptive_last_generated_key = None
        state.adaptive_last_generated_at = None
    update_student_state(
        db,
        state,
        problem,
        next_problem,
        is_correct,
        hint_used,
        elapsed_sec,
        apply_unit_mastery=False,
    )

    # ----------------------------------------------------------------
    # 忘却曲線: 復習スケジュール更新（practice のみ）
    # ----------------------------------------------------------------
    update_review_schedule(db, student_id, problem, is_correct, hint_used, elapsed_sec)
    db.commit()

    # ----------------------------------------------------------------
    # G（ゴールド）の獲得 & ボードセル作成
    # ----------------------------------------------------------------
    db.refresh(state)
    g_earned = 0
    ai_event_text = None
    if is_correct:
        g_earned = 8 if hint_used == 0 else 5

    # AIイベント判定（連続正解 / エラーパターン検出）
    recent_logs_stmt = (
        select(LearningLog)
        .where(LearningLog.student_id == student_id)
        .order_by(desc(LearningLog.created_at))
        .limit(5)
    )
    recent_5 = db.scalars(recent_logs_stmt).all()
    consecutive_correct = 0
    for rl in recent_5:
        if rl.is_correct:
            consecutive_correct += 1
        else:
            break
    if consecutive_correct >= 3 and is_correct:
        ai_event_text = f"🔥 {consecutive_correct}問連続正解！ボーナス +10G"
        g_earned += 10
    elif log.error_pattern and not is_correct:
        ai_event_text = f"🎯 AIがパターンを検出：{log.error_pattern}"

    state.gold = (state.gold or 0) + g_earned

    # ストリーク & XP 更新
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    last_date = getattr(state, "last_activity_date", None)
    if last_date != today_str:
        if last_date is None or (datetime.strptime(today_str, "%Y-%m-%d") - datetime.strptime(last_date, "%Y-%m-%d")).days == 1:
            state.login_streak = (state.login_streak or 0) + 1
        else:
            state.login_streak = 1
        state.last_activity_date = today_str
    xp_earned = 10 if is_correct and hint_used == 0 else 5 if is_correct else 1
    xp_before = state.total_xp or 0
    level_before = (xp_before // 100) + 1
    state.total_xp = xp_before + xp_earned
    level_up = level_before < ((state.total_xp // 100) + 1)

    db.add(state)

    # ボードセルのcell_index（この単元での何問目か）
    cell_count = db.execute(
        select(StudentBoardCell).where(
            StudentBoardCell.student_id == student_id,
            StudentBoardCell.unit_id == (problem.full_unit_id or problem.unit),
        )
    ).unique().all()  # type: ignore
    cell_index = len(cell_count)

    if hint_used >= 1 and not is_correct:
        cell_type = "hint"
    elif is_correct and ai_event_text and "連続" in ai_event_text:
        cell_type = "bonus"
    elif is_correct:
        cell_type = "correct"
    else:
        cell_type = "wrong"

    board_cell = StudentBoardCell(
        student_id=student_id,
        unit_id=problem.full_unit_id or problem.unit,
        cell_index=cell_index,
        problem_id=problem.problem_id,
        is_correct=is_correct,
        hint_used=hint_used,
        cell_type=cell_type,
        ai_event_text=ai_event_text,
        g_earned=g_earned,
        created_at=datetime.utcnow().isoformat(),
    )
    db.add(board_cell)
    db.commit()

    # Phase 2-B: ユニットクリア検出
    _mastery_after_obj = db.get(UnitMastery, (student_id, _unit_key))
    unit_clear = (
        is_correct
        and _mastery_after_obj is not None
        and _mastery_after_obj.mastery_score >= 0.55
        and mastery_score_before < 0.55
    )
    # ----------------------------------------------------------------

    unit_labels = get_unit_label_map(db)

    result = SubmissionResult(
        problem_id=problem.problem_id,
        is_correct=is_correct,
        correct_answer=problem.correct_answer,
        explanation=problem.explanation_base,
        next_problem_id=next_problem.problem_id if next_problem else None,
        next_unit=next_problem.full_unit_id or next_problem.unit if next_problem else None,
        next_difficulty=next_problem.difficulty if next_problem else None,
        logged_at=datetime.utcnow(),
    )

    # テスト発動提案を計算
    unit_id = state.current_unit or problem.full_unit_id or problem.unit
    test_suggestion = should_trigger_test(db, student_id, unit_id) if unit_id else None

    next_url = (
        f"/students/{student_id}/review"
        if review_mode
        else f"/students/{student_id}/english/problem"
        if problem.subject == "english"
        else f"/students/{student_id}"
    )

    sub_main, sub_aux = pair_for_student_numeric_result_display(
        answer, subject=problem.subject, answer_type=problem.answer_type
    )
    corr_main, corr_aux = pair_for_student_numeric_result_display(
        problem.correct_answer, subject=problem.subject, answer_type=problem.answer_type
    )

    # ソクラテス式誘導質問（不正解時のみ生成）
    socratic_questions = None
    if not is_correct:
        try:
            socratic_questions = generate_socratic_questions(
                question_text=problem.question_text,
                correct_answer=problem.correct_answer,
                student_answer=answer,
                misconception_tag=getattr(log, "misconception_tag", None),
                misconception_detail=getattr(log, "misconception_detail", None),
                subject=problem.subject or "math",
            )
        except Exception as _e:
            logger.debug("socratic questions skipped: %s", _e)

    return templates.TemplateResponse(
        "student_result.html",
        {
            "request": request,
            "student": student,
            "problem": problem,
            "result": result,
            "next_problem": next_problem,
            "submitted_answer": answer,
            "submitted_display": {"main": sub_main, "aux": sub_aux},
            "correct_display": {"main": corr_main, "aux": corr_aux},
            "unit_labels": unit_labels,
            "hint_used": hint_used,
            "is_student_view": True,
            "is_adapted": is_adapted,
            "test_suggestion": test_suggestion,
            "test_suggestion_unit_id": unit_id if test_suggestion else None,
            "test_scope_label": test_scope_label(test_suggestion) if test_suggestion else None,
            "g_earned": g_earned,
            "ai_event_text": ai_event_text,
            "gold": state.gold,
            "next_url": next_url,
            "grading_result": grading_result,
            "new_badges": new_badges,
            "level_up": level_up,
            "new_level": (state.total_xp // 100) + 1,
            "xp_earned": xp_earned,
            "unit_clear": unit_clear,
            "socratic_questions": socratic_questions,
            "misconception_tag": getattr(log, "misconception_tag", None),
            "misconception_detail": getattr(log, "misconception_detail", None),
        },
    )


@router.post("/{student_id}/shop/buy_challenge")
def buy_challenge_problem(
    request: Request,
    student_id: int,
    problem_id: int = Form(...),
    db: Session = Depends(get_db),
):
    require_student_login(request, student_id, api=True)
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)

    state = ensure_student_state(db, student)
    CHALLENGE_COST = 100
    if (state.gold or 0) < CHALLENGE_COST:
        raise HTTPException(status_code=400, detail=f"G不足です。{CHALLENGE_COST}G必要です（現在: {state.gold or 0}G）")

    problem = get_approved_challenge_problem(db, problem_id)
    if problem is None:
        raise HTTPException(status_code=400, detail="選んだ問題は購入できません。一覧から選び直してください。")

    state.gold = (state.gold or 0) - CHALLENGE_COST
    state.pending_challenge_problem_id = problem.problem_id
    db.add(state)
    db.commit()

    # フォームからのPOSTはホームへリダイレクト、APIはJSONを返す
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return {"status": "ok", "problem_id": problem.problem_id, "remaining_gold": state.gold}
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/students/{student_id}", status_code=303)


@router.get("/{student_id}/context")
def student_context(request: Request, student_id: int, db: Session = Depends(get_db)):
    require_student_login(request, student_id, api=True)
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)
    summary = build_student_summary(db, student_id, current_user_role="student")
    if summary is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return summary


@router.get("/{student_id}/badges")
def get_student_badges(request: Request, student_id: int, db: Session = Depends(get_db)):
    """
    学生の獲得バッジを取得
    
    Returns:
        {
            "badges": [
                {
                    "key": "badge_key",
                    "name": "バッジ名",
                    "description": "説明",
                    "emoji": "絵文字"
                }
            ]
        }
    """
    require_student_login(request, student_id, api=True)
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)
    
    state = ensure_student_state(db, student)
    badges = get_student_badges_display(state)
    
    return {"badges": badges}


@router.post("/{student_id}/test/start", response_class=HTMLResponse)
def test_start(
    request: Request,
    student_id: int,
    test_scope: str = Form(...),
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

    if test_scope not in {"mini_test", "unit_test"}:
        raise HTTPException(status_code=400, detail="Invalid test_scope")

    # 既に進行中のテストがあれば中断せずそのままリダイレクト
    active = get_active_test_session(db, student_id)
    if active is not None:
        return RedirectResponse(url=f"/students/{student_id}", status_code=303)

    session = start_test_session(db, student_id, unit_id, test_scope)
    if session is None:
        # 問題が足りない場合は通常ページへ戻る
        return RedirectResponse(url=f"/students/{student_id}", status_code=303)

    return RedirectResponse(url=f"/students/{student_id}", status_code=303)


@router.post("/{student_id}/test/{session_id}/defer", response_class=HTMLResponse)
def test_defer_problem(
    request: Request,
    student_id: int,
    session_id: int,
    problem_id: int = Form(...),
    db: Session = Depends(get_db),
):
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)
    session = get_test_session_by_id(db, session_id)
    if session is None or session.student_id != student_id:
        raise HTTPException(status_code=404, detail="Test session not found")
    if session.status != "in_progress":
        return RedirectResponse(
            url=f"/students/{student_id}/test/{session_id}/result",
            status_code=303,
        )
    if check_and_finalize_test_if_expired(db, session):
        return RedirectResponse(
            url=f"/students/{student_id}/test/{session_id}/result?time_up=1",
            status_code=303,
        )
    try:
        defer_test_problem(db, session, student_id, problem_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="あとで解くを処理できませんでした")
    return RedirectResponse(url=f"/students/{student_id}", status_code=303)


@router.get("/{student_id}/test/{session_id}/result", response_class=HTMLResponse)
def test_result(
    request: Request,
    student_id: int,
    session_id: int,
    db: Session = Depends(get_db),
):
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)

    test_session = get_test_session_by_id(db, session_id)
    if test_session is None or test_session.student_id != student_id:
        raise HTTPException(status_code=404, detail="Test session not found")

    unit_labels = get_unit_label_map(db)
    detail = get_test_result_detail(db, test_session)

    return templates.TemplateResponse(
        "student_test_result.html",
        {
            "request": request,
            "student": student,
            "unit_labels": unit_labels,
            "is_student_view": True,
            **detail,
        },
    )


@router.get("/{student_id}/ranking", response_class=HTMLResponse)
def student_ranking(request: Request, student_id: int, db: Session = Depends(get_db)):
    """クラス内週間ランキング"""
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _ensure_student_classroom_access(request, student)

    week_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = week_start.replace(day=week_start.day - week_start.weekday())

    # 同じ教室の生徒を取得
    classroom_id = student.classroom_id
    if classroom_id:
        classmates_stmt = select(Student).where(
            Student.classroom_id == classroom_id,
            Student.is_active == True,
        )
        classmates = db.scalars(classmates_stmt).all()
    else:
        classmates = [student]

    # 各生徒の今週の正解数とXPを集計
    ranking_rows = []
    for s in classmates:
        logs_stmt = select(LearningLog).where(
            LearningLog.student_id == s.student_id,
            LearningLog.created_at >= week_start,
        )
        logs = db.scalars(logs_stmt).all()
        week_correct = sum(1 for l in logs if l.is_correct)
        week_xp = sum(10 if l.is_correct else 1 for l in logs)
        state_row = db.get(StudentState, s.student_id)
        ranking_rows.append({
            "student": s,
            "week_correct": week_correct,
            "week_xp": week_xp,
            "total_xp": state_row.total_xp if state_row else 0,
            "streak": state_row.login_streak if state_row else 0,
            "gold": state_row.gold if state_row else 0,
            "is_me": s.student_id == student_id,
        })

    ranking_rows.sort(key=lambda r: r["week_xp"], reverse=True)
    for i, row in enumerate(ranking_rows):
        row["rank"] = i + 1

    return templates.TemplateResponse(
        "student_ranking.html",
        {
            "request": request,
            "student": student,
            "ranking_rows": ranking_rows,
            "week_start": week_start.strftime("%m/%d"),
            "is_student_view": True,
        },
    )
