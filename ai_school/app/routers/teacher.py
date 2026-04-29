import json
from datetime import datetime, timezone
from html import escape

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Classroom, LearningLog, Problem, Student, StudentState, Teacher, TeacherAnnotation, UnitDependency, UnitMastery
from ..services.auth_service import ensure_session_classroom_access, generate_pin, hash_secret, read_session, require_teacher_login
from ..services.conversation_service import generate_teacher_summary
from ..services.diagram_display_name_service import get_diagram_display_info
from ..services.diagram_service import get_problem_diagram_status, render_problem_diagram_for_route
from ..services.diagnostic_service import VALID_DIAGNOSTIC_LABELS, build_diagnostic_snapshot
from ..services.parent_report_service import (
    aggregate_today_learning_logs,
    build_today_fallback_message,
    generate_today_parent_message_ai,
    generate_weekly_parent_message_ai,
    weekly_trend_text_for_prompt,
)
from ..services.answer_input_spec_service import normalize_answer_input_spec_for_storage
from ..services.error_pattern_service import KNOWN_ERROR_PATTERNS
from ..services.intervention_service import KNOWN_INTERVENTION_CANDIDATES
from ..services.listening_service import build_listening_stats
from ..services.problem_service import get_unit_label_map
from ..services.lecture_step_service import generate_lecture_steps
from ..services.routing_service import get_next_problem_candidate_ids, get_student_error_map
from ..services.state_service import (
    build_student_summary,
    build_teacher_student_metrics,
    effective_unit_unlock,
    ensure_student_state,
    slim_teacher_summary_context,
)
from ..services.test_service import (
    get_recent_test_sessions_for_classroom,
    get_recent_test_sessions_for_student,
    scope_label as test_scope_label,
    test_session_summary_row,
)
from ..services.text_display_service import render_math_text
from ..services.unit_map_service import get_unit_map_entry, load_all_unit_maps
from ..paths import TEMPLATES_DIR


router = APIRouter(prefix="/teachers", tags=["teachers"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["render_math_text"] = render_math_text
templates.env.filters["from_json"] = lambda s: json.loads(s) if s else []


VALID_REASON_CODES = {
    "teacher_observed_mastery",
    "temporary_state",
    "home_study_reflected",
    "system_misdiagnosis",
    "other_teacher_judgment",
}

DIAGNOSTIC_LABELS_JA = {
    "stable_mastery": "安定習熟",
    "hint_dependent": "ヒント依存",
    "slow_but_correct": "時間はかかるが正答",
    "unstable_understanding": "理解が不安定",
    "fallback_risk": "つまずき再発リスク",
    "prerequisite_gap": "前提単元の抜け",
    "in_progress": "学習途中",
    "not_enough_data": "データ不足",
    "not_started": "未着手",
}

REASON_CODE_LABELS_JA = {
    "teacher_observed_mastery": "教師観察で習熟確認",
    "temporary_state": "一時的な状態変化",
    "home_study_reflected": "家庭学習の反映",
    "system_misdiagnosis": "AI診断のずれ補正",
    "other_teacher_judgment": "その他の教師判断",
}

ROUTE_LABELS_JA = {
    "advance_next_unit": "次単元へ進行",
    "reinforce_current_unit": "現単元を継続",
    "fallback_prerequisite_unit": "前提単元へ戻る",
}

INTERVENTION_LABELS_JA = {
    "reinforce_same_pattern": "同型問題で補強",
    "retry_with_hint": "ヒント付きで再挑戦",
    "fallback_prerequisite": "前提単元を補強",
    "slow_down_and_confirm": "速度を落として確認",
    "explain_differently": "別の説明で補助",
    "teacher_intervention_needed": "教師の短時間介入が必要",
    "advance_with_confidence": "自信を持って次へ進む",
    "monitor_only": "経過観察",
}

SPEED_PROFILE_LABELS_JA = {
    "slow": "ゆっくり",
    "normal": "標準",
    "fast": "速い",
    "unknown": "不明",
}

FALLBACK_RISK_LABELS_JA = {
    "high": "高い",
    "medium": "中",
    "low": "低い",
}

HINT_LEVEL_LABELS_JA = {
    "high": "高い",
    "medium": "中",
    "low": "低い",
    "none": "なし",
}


class TeacherOverrideRequest(BaseModel):
    problem_id: int = Field(..., ge=1)
    reason: str | None = None


class TeacherAnnotationRequest(BaseModel):
    diagnostic_correction: str
    reason_code: str | None = None
    note: str | None = None
    expires_at: str | None = None


def _build_problem_option_label(problem: Problem, unit_labels: dict[str, str]) -> str:
    unit_label = unit_labels.get(problem.unit, problem.unit)
    text = " ".join(problem.question_text.split())
    preview = text[:28] + "..." if len(text) > 28 else text
    return f"{unit_label} / Lv{problem.difficulty} / #{problem.problem_id} / {preview}"


def _display_name_from_full_unit_id(full_unit_id: str | None) -> str | None:
    entry = get_unit_map_entry(full_unit_id)
    if entry is None:
        return None
    return entry.get("display_name")


def _parse_bool_filter(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    if value.lower() in {"true", "1", "yes"}:
        return True
    if value.lower() in {"false", "0", "no"}:
        return False
    return None


@router.get("/dashboard", response_class=HTMLResponse)
def teacher_dashboard(request: Request, db: Session = Depends(get_db)):
    auth = require_teacher_login(request)
    if auth is not None:
        return auth
    session = read_session(request)
    classroom_id = session.get("classroom_id")
    current_teacher = db.get(Teacher, session.get("teacher_id")) if session.get("teacher_id") else None
    if current_teacher is None:
        raise HTTPException(status_code=403, detail="teacher access denied")
    ensure_session_classroom_access(session, current_teacher.classroom_id)

    classroom = db.get(Classroom, classroom_id) if classroom_id is not None else None
    students = db.scalars(
        select(Student).where(Student.classroom_id == classroom_id).order_by(Student.student_id.asc())
    ).all()
    teachers = db.scalars(
        select(Teacher).where(Teacher.classroom_id == classroom_id).order_by(Teacher.teacher_id.asc())
    ).all()
    student_ids = [student.student_id for student in students]
    states = {
        state.student_id: state
        for state in db.scalars(select(StudentState).where(StudentState.student_id.in_(student_ids))).all()
    } if student_ids else {}
    metrics = {student.student_id: build_teacher_student_metrics(db, student.student_id) for student in students}
    teacher_ai = {}
    for student in students:
        st = states.get(student.student_id)
        if st and getattr(st, "ai_summary_text", None):
            teacher_ai[student.student_id] = {
                "summary": st.ai_summary_text,
                "updated_at": st.ai_summary_updated_at,
            }
        else:
            teacher_ai[student.student_id] = {
                "summary": None,
                "updated_at": None,
            }
    unit_labels = get_unit_label_map(db)
    classroom_labels = {classroom.classroom_id: classroom.classroom_name} if classroom is not None else {}
    for student in students:
        metric = metrics.get(student.student_id)
        if metric is None:
            continue
        metric["current_full_unit_display_name"] = metric.get("current_unit_display_name")
        metric["prerequisite_full_unit_display_name"] = _display_name_from_full_unit_id(metric.get("prerequisite_full_unit_id"))
        metric["next_full_unit_display_name"] = _display_name_from_full_unit_id(metric.get("next_full_unit_id"))
    problem_options = {}
    for student in students:
        state = states.get(student.student_id)
        if state is None:
            problem_options[student.student_id] = []
            continue

        current_problem = db.get(Problem, state.last_problem_id) if state.last_problem_id else None
        candidate_ids: list[int]
        if current_problem is not None:
            candidate_ids = get_next_problem_candidate_ids(db, state, current_problem, limit=5)
        elif state.current_unit is not None:
            stmt = (
                select(Problem)
                .where(Problem.unit == state.current_unit)
                .order_by(Problem.difficulty.asc(), Problem.problem_id.asc())
                .limit(5)
            )
            candidate_ids = [problem.problem_id for problem in db.scalars(stmt).all()]
        else:
            candidate_ids = []

        if state.teacher_override_problem_id and state.teacher_override_problem_id not in candidate_ids:
            candidate_ids.insert(0, state.teacher_override_problem_id)

        options = []
        for problem_id in candidate_ids:
            problem = db.get(Problem, problem_id)
            if problem is None:
                continue
            options.append(
                {
                    "problem_id": problem.problem_id,
                    "label": _build_problem_option_label(problem, unit_labels),
                }
            )
        problem_options[student.student_id] = options
    logs = db.execute(
        select(LearningLog, Problem, Student)
        .join(Problem, LearningLog.problem_id == Problem.problem_id)
        .join(Student, LearningLog.student_id == Student.student_id)
        .where(Student.classroom_id == classroom_id)
        .order_by(desc(LearningLog.created_at))
        .limit(20)
    ).all()

    # テストセッション集計（生徒ごと直近3件 + 教室全体直近20件）
    student_test_sessions = {
        student.student_id: get_recent_test_sessions_for_student(db, student.student_id, limit=3)
        for student in students
    }
    classroom_test_sessions = get_recent_test_sessions_for_classroom(db, student_ids, limit=20)

    test_session_meta: dict[int, dict] = {}
    for _lst in student_test_sessions.values():
        for _ts in _lst:
            test_session_meta[_ts.session_id] = test_session_summary_row(_ts)
    for _ts, _stu in classroom_test_sessions:
        test_session_meta[_ts.session_id] = test_session_summary_row(_ts)

    error_maps = {
        student.student_id: get_student_error_map(db, student.student_id, limit=20)
        for student in students
    }

    listening_stats = None
    if classroom_id is not None:
        listening_stats = build_listening_stats(db, classroom_id)
        stu_map = {s.student_id: s.display_name for s in students}
        listening_stats["teacher_flag_detail"] = [
            {"student_id": sid, "display_name": stu_map.get(sid, str(sid))}
            for sid in listening_stats.get("teacher_flag_students", [])
        ]

    effective_unlock_by_student = {
        student.student_id: effective_unit_unlock(classroom, states.get(student.student_id))
        for student in students
    }

    # ── 神システム: 誤概念テレパシーヒートマップ（過去7日間）──────────────
    from datetime import timedelta
    misconception_heatmap: list[dict] = []
    if student_ids:
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        stu_name_map = {s.student_id: s.display_name for s in students}
        miscon_rows = db.execute(
            select(
                LearningLog.misconception_tag,
                LearningLog.misconception_detail,
                func.count(LearningLog.log_id).label("cnt"),
            )
            .where(
                LearningLog.student_id.in_(student_ids),
                LearningLog.misconception_tag.isnot(None),
                LearningLog.created_at >= seven_days_ago,
            )
            .group_by(LearningLog.misconception_tag, LearningLog.misconception_detail)
            .order_by(desc("cnt"))
            .limit(8)
        ).all()

        max_count = miscon_rows[0][2] if miscon_rows else 1
        for row in miscon_rows:
            tag, detail, count = row[0], row[1], row[2]
            affected_ids = db.scalars(
                select(LearningLog.student_id)
                .where(
                    LearningLog.student_id.in_(student_ids),
                    LearningLog.misconception_tag == tag,
                    LearningLog.created_at >= seven_days_ago,
                )
                .distinct()
            ).all()
            affected_names = [stu_name_map.get(sid, str(sid)) for sid in affected_ids]
            misconception_heatmap.append({
                "tag": tag,
                "detail": detail or tag,
                "count": count,
                "pct": round(count / max_count * 100),
                "student_names": affected_names,
                "student_count": len(affected_names),
            })
    # ─────────────────────────────────────────────────────────────────────

    return templates.TemplateResponse(
        "teacher_dashboard.html",
        {
            "request": request,
            "classroom": classroom,
            "students": students,
            "teachers": teachers,
            "classroom_labels": classroom_labels,
            "current_teacher_id": session.get("teacher_id"),
            "states": states,
            "metrics": metrics,
            "teacher_ai": teacher_ai,
            "unit_labels": unit_labels,
            "problem_options": problem_options,
            "logs": logs,
            "student_test_sessions": student_test_sessions,
            "classroom_test_sessions": classroom_test_sessions,
            "error_maps": error_maps,
            "test_scope_label": test_scope_label,
            "auth_role": "teacher",
            "diagnostic_labels_ja": DIAGNOSTIC_LABELS_JA,
            "reason_code_labels_ja": REASON_CODE_LABELS_JA,
            "route_labels_ja": ROUTE_LABELS_JA,
            "intervention_labels_ja": INTERVENTION_LABELS_JA,
            "speed_profile_labels_ja": SPEED_PROFILE_LABELS_JA,
            "fallback_risk_labels_ja": FALLBACK_RISK_LABELS_JA,
            "hint_level_labels_ja": HINT_LEVEL_LABELS_JA,
            "all_units": db.scalars(select(UnitDependency).order_by(UnitDependency.display_order.asc())).all(),
            "listening_stats": listening_stats,
            "effective_unlock_by_student": effective_unlock_by_student,
            "test_session_meta": test_session_meta,
            "misconception_heatmap": misconception_heatmap,
        },
    )


@router.post("/students/{student_id}/ai_summary/refresh", response_class=HTMLResponse)
def refresh_ai_summary(request: Request, student_id: int, db: Session = Depends(get_db)):
    auth = require_teacher_login(request)
    if auth is not None:
        return auth
    session = read_session(request)
    current_teacher = db.get(Teacher, session.get("teacher_id")) if session.get("teacher_id") else None
    if current_teacher is None:
        raise HTTPException(status_code=403, detail="teacher access denied")

    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="student not found")
    ensure_session_classroom_access(session, student.classroom_id)

    summary_model = build_student_summary(db, student_id, current_user_role="teacher")
    slim = slim_teacher_summary_context(summary_model.model_dump())
    text, source = generate_teacher_summary(slim)

    st = ensure_student_state(db, student)
    st.ai_summary_text = text
    st.ai_summary_updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    db.add(st)
    db.commit()

    sid = student_id
    e_text, e_src, e_time = escape(text), escape(source), escape(st.ai_summary_updated_at or "")
    return HTMLResponse(
        f'<div class="teacher-ai-summary" id="ai-summary-{sid}">'
        f'<div class="teacher-ai-summary__head"><strong>AI要約</strong>'
        f'<button type="button" class="btn-summary-refresh" hx-post="/teachers/students/{sid}/ai_summary/refresh" '
        f'hx-target="#ai-summary-{sid}" hx-swap="outerHTML" hx-indicator="#ai-summary-indicator-{sid}">AI要約を更新</button></div>'
        f"<p>{e_text}</p>"
        f'<div class="meta-note">最終更新：{e_time}</div>'
        f'<span id="ai-summary-indicator-{sid}" class="htmx-indicator">更新中…</span>'
        f'<div class="meta-note summary-done">更新しました</div>'
        f'<div class="meta-note">表示元: {e_src}</div>'
        f"</div>"
    )


@router.post("/unit_unlock", response_class=HTMLResponse)
def update_unit_unlock(
    request: Request,
    unit_unlock_mode: str = Form(...),
    unit_unlock_up_to: str = Form(""),
    db: Session = Depends(get_db),
):
    auth = require_teacher_login(request)
    if auth is not None:
        return auth
    session = read_session(request)
    classroom_id = session.get("classroom_id")
    current_teacher = db.get(Teacher, session.get("teacher_id")) if session.get("teacher_id") else None
    if current_teacher is None:
        raise HTTPException(status_code=403, detail="teacher access denied")
    ensure_session_classroom_access(session, current_teacher.classroom_id)

    classroom = db.get(Classroom, classroom_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="Classroom not found")

    if unit_unlock_mode not in ("progressive", "up_to", "full"):
        raise HTTPException(status_code=400, detail="Invalid mode")
    if unit_unlock_mode == "up_to" and not (unit_unlock_up_to or "").strip():
        raise HTTPException(status_code=400, detail="開始単元を選択してください")

    classroom.unit_unlock_mode = unit_unlock_mode
    classroom.unit_unlock_up_to = unit_unlock_up_to.strip() or None if unit_unlock_mode == "up_to" else None
    db.add(classroom)
    db.commit()
    return RedirectResponse(url="/teachers/dashboard#teacher-unit-unlock", status_code=303)


@router.post("/students/{student_id}/unit_unlock", response_class=HTMLResponse)
def update_student_unit_unlock(
    request: Request,
    student_id: int,
    unit_unlock_mode: str = Form(...),
    unit_unlock_up_to: str = Form(""),
    db: Session = Depends(get_db),
):
    auth = require_teacher_login(request)
    if auth is not None:
        return auth
    session = read_session(request)
    classroom_id = session.get("classroom_id")
    current_teacher = db.get(Teacher, session.get("teacher_id")) if session.get("teacher_id") else None
    if current_teacher is None:
        raise HTTPException(status_code=403, detail="teacher access denied")
    ensure_session_classroom_access(session, current_teacher.classroom_id)

    student = db.get(Student, student_id)
    if student is None or student.classroom_id != classroom_id:
        raise HTTPException(status_code=404, detail="Student not found")

    st = ensure_student_state(db, student)
    if unit_unlock_mode == "inherit":
        st.unit_unlock_mode = None
        st.unit_unlock_up_to = None
    else:
        if unit_unlock_mode not in ("progressive", "up_to", "full"):
            raise HTTPException(status_code=400, detail="Invalid mode")
        if unit_unlock_mode == "up_to" and not (unit_unlock_up_to or "").strip():
            raise HTTPException(status_code=400, detail="開始単元を選択してください")
        st.unit_unlock_mode = unit_unlock_mode
        st.unit_unlock_up_to = unit_unlock_up_to.strip() or None if unit_unlock_mode == "up_to" else None
    db.add(st)
    db.commit()
    return RedirectResponse(url="/teachers/dashboard#teacher-unit-unlock", status_code=303)


@router.post("/students/add")
def add_student(
    request: Request,
    display_name: str = Form(...),
    grade: int = Form(...),
    pin: str = Form(""),
    db: Session = Depends(get_db),
):
    auth = require_teacher_login(request)
    if auth is not None:
        raise HTTPException(status_code=403, detail="teacher login required")
    session = read_session(request)
    classroom_id = session.get("classroom_id")
    current_teacher = db.get(Teacher, session.get("teacher_id")) if session.get("teacher_id") else None
    if current_teacher is None:
        raise HTTPException(status_code=403, detail="teacher access denied")
    ensure_session_classroom_access(session, current_teacher.classroom_id)

    classroom = db.get(Classroom, classroom_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="classroom not found")

    from ..services.classroom_ops_service import assert_can_add_student

    assert_can_add_student(db, classroom_id)

    name = display_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="名前を入力してください")
    if grade not in (7, 8, 9):
        raise HTTPException(status_code=422, detail="grade must be 7, 8, or 9")

    new_pin = pin.strip() or generate_pin()
    if not new_pin.isdigit() or len(new_pin) != 4:
        raise HTTPException(status_code=422, detail="PINは4桁の数字で入力してください")

    student = Student(
        display_name=name,
        grade=grade,
        classroom_id=classroom_id,
        login_pin_hash=hash_secret(new_pin),
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
        "new_pin_once": new_pin,
    }


@router.get("/problems", response_class=HTMLResponse)
def teacher_problem_list(
    request: Request,
    grade: int | None = None,
    unit: str | None = None,
    full_unit_id: str | None = None,
    problem_type: str | None = None,
    difficulty: int | None = None,
    diagram_required: str | None = None,
    db: Session = Depends(get_db),
):
    auth = require_teacher_login(request)
    if auth is not None:
        return auth

    diagram_required_bool = _parse_bool_filter(diagram_required)
    conditions: list = []
    if grade is not None:
        conditions.append(Problem.grade == grade)
    if unit:
        conditions.append(Problem.unit == unit)
    if full_unit_id:
        conditions.append(Problem.full_unit_id == full_unit_id)
    if problem_type:
        conditions.append(Problem.problem_type == problem_type)
    if difficulty is not None:
        conditions.append(Problem.difficulty == difficulty)
    if diagram_required_bool is not None:
        conditions.append(Problem.diagram_required == diagram_required_bool)

    stmt = select(Problem).where(*conditions)
    total_count = db.scalar(select(func.count(Problem.problem_id)).where(*conditions)) or 0
    diagram_required_count = (
        db.scalar(
            select(func.count(Problem.problem_id)).where(*conditions, Problem.diagram_required.is_(True))
        )
        or 0
    )
    diagram_problems_all = db.scalars(
        select(Problem)
        .where(*conditions, Problem.diagram_required.is_(True))
        .order_by(Problem.grade.asc(), Problem.unit.asc(), Problem.problem_id.asc())
    ).all()
    renderable_pairs: list[tuple[Problem, dict]] = []
    for p in diagram_problems_all:
        st = get_problem_diagram_status(p)
        if st["renderable"]:
            renderable_pairs.append((p, st))
    diagram_renderable_count = len(renderable_pairs)

    problems = db.scalars(stmt.order_by(Problem.grade.asc(), Problem.unit.asc(), Problem.problem_id.asc()).limit(500)).all()
    unit_labels = get_unit_label_map(db)
    grades = db.scalars(select(Problem.grade).distinct().order_by(Problem.grade.asc())).all()
    units = db.scalars(select(Problem.unit).distinct().order_by(Problem.unit.asc())).all()
    full_unit_ids = db.scalars(
        select(Problem.full_unit_id).where(Problem.full_unit_id.is_not(None)).distinct().order_by(Problem.full_unit_id.asc())
    ).all()
    difficulties = db.scalars(select(Problem.difficulty).distinct().order_by(Problem.difficulty.asc())).all()
    full_unit_labels = {item["full_unit_id"]: item["display_name"] for item in load_all_unit_maps()}
    pending_count = db.scalar(select(func.count(Problem.problem_id)).where(Problem.status == 'pending')) or 0
    problem_rows = []
    for problem in problems:
        diagram_status = get_problem_diagram_status(problem)
        diagram_display = get_diagram_display_info(problem, route="teacher_list")
        problem_rows.append(
            {
                "problem": problem,
                "unit_display_name_ja": full_unit_labels.get(problem.full_unit_id, unit_labels.get(problem.unit, problem.unit)),
                "question_preview": " ".join(problem.question_text.split()),
                "is_diagram_required": diagram_status["required"],
                "is_diagram_renderable": diagram_status["renderable"],
                "diagram_badge": diagram_status["diagram_badge"],
                "diagram_render_status": diagram_status["status_label"],
                "diagram_display_name": diagram_display["display_name"],
                "diagram_internal_key": diagram_display["internal_key"],
                "priority_rank": 0 if diagram_status["renderable"] else 1 if diagram_status["required"] else 2,
                "priority_label": "今すぐ確認" if diagram_status["renderable"] else "図あり未対応" if diagram_status["required"] else None,
                "is_priority_preview_target": bool(diagram_status["renderable"]),
            }
        )

    problem_rows.sort(key=lambda row: (row["priority_rank"], row["problem"].grade, row["problem"].problem_id))
    ready_rows = []
    for problem, diagram_status in renderable_pairs[:5]:
        diagram_display = get_diagram_display_info(problem, route="teacher_list")
        ready_rows.append(
            {
                "problem": problem,
                "unit_display_name_ja": full_unit_labels.get(
                    problem.full_unit_id, unit_labels.get(problem.unit, problem.unit)
                ),
                "question_preview": " ".join(problem.question_text.split()),
                "is_diagram_required": diagram_status["required"],
                "is_diagram_renderable": diagram_status["renderable"],
                "diagram_badge": diagram_status["diagram_badge"],
                "diagram_render_status": diagram_status["status_label"],
                "diagram_display_name": diagram_display["display_name"],
                "diagram_internal_key": diagram_display["internal_key"],
                "priority_rank": 0,
                "priority_label": "今すぐ確認",
                "is_priority_preview_target": True,
            }
        )

    return templates.TemplateResponse(
        "problem_list.html",
        {
            "request": request,
            "auth_role": "teacher",
            "problem_rows": problem_rows,
            "ready_rows": ready_rows,
            "unit_labels": unit_labels,
            "full_unit_labels": full_unit_labels,
            "grades": grades,
            "units": units,
            "full_unit_ids": full_unit_ids,
            "difficulties": difficulties,
            "counts": {
                "total": total_count,
                "diagram_required": diagram_required_count,
                "diagram_renderable": diagram_renderable_count,
                "pending": pending_count,
            },
            "filters": {
                "grade": grade,
                "unit": unit,
                "full_unit_id": full_unit_id,
                "problem_type": problem_type,
                "difficulty": difficulty,
                "diagram_required": diagram_required or "",
            },
        },
    )


@router.get("/problems/create", response_class=HTMLResponse)
def problem_create_form(request: Request, db: Session = Depends(get_db)):
    auth = require_teacher_login(request)
    if auth is not None:
        return auth

    all_units = db.scalars(
        select(UnitDependency).order_by(UnitDependency.display_order.asc())
    ).all()

    return templates.TemplateResponse(
        "teacher_problem_create.html",
        {
            "request": request,
            "auth_role": "teacher",
            "all_units": all_units,
            "known_error_patterns": sorted(KNOWN_ERROR_PATTERNS),
            "known_intervention_candidates": sorted(KNOWN_INTERVENTION_CANDIDATES),
            "error_pattern_labels": {
                "sign_error": "符号エラー",
                "arithmetic_error": "計算ミス",
                "absolute_value_error": "絶対値エラー",
                "operation_confusion": "演算混同",
                "careless_error": "ケアレスミス",
                "variable_handling_error": "文字の扱いミス",
                "formula_setup_error": "式の立て方ミス",
                "comprehension_gap": "理解不足",
                "prerequisite_gap": "前提知識の欠落",
                "unknown_error": "その他",
            },
            "intervention_labels": {
                "reinforce_same_pattern": "同型問題で補強",
                "retry_with_hint": "ヒント付きで再挑戦",
                "fallback_prerequisite": "前提単元を補強",
                "slow_down_and_confirm": "速度を落として確認",
                "explain_differently": "別の説明で補助",
                "teacher_intervention_needed": "教師の短時間介入",
                "advance_with_confidence": "自信を持って次へ",
                "monitor_only": "経過観察",
            },
        },
    )


@router.post("/problems/create", response_class=HTMLResponse)
def problem_create(
    request: Request,
    subject: str = Form(...),
    grade: int = Form(...),
    unit: str = Form(...),
    full_unit_id: str = Form(""),
    problem_type: str = Form(...),
    difficulty: int = Form(...),
    question_text: str = Form(...),
    answer_type: str = Form("numeric"),
    correct_answer: str = Form(...),
    choices_raw: str = Form(""),
    hint_1: str = Form(""),
    hint_2: str = Form(""),
    explanation_base: str = Form(""),
    answer_input_spec_raw: str = Form(""),
    error_pattern_candidates: list[str] = Form([]),
    intervention_candidates: list[str] = Form([]),
    auto_approve: str = Form(""),
    db: Session = Depends(get_db),
):
    auth = require_teacher_login(request)
    if auth is not None:
        raise HTTPException(status_code=403, detail="teacher login required")
    session = read_session(request)
    current_teacher = db.get(Teacher, session.get("teacher_id")) if session.get("teacher_id") else None
    if current_teacher is None:
        raise HTTPException(status_code=403, detail="teacher access denied")

    # バリデーション
    errors: list[str] = []
    question_text = question_text.strip()
    correct_answer = correct_answer.strip()
    if not question_text:
        errors.append("問題文を入力してください")
    if len(question_text) > 5000:
        errors.append("問題文は5000文字以内にしてください")
    if not correct_answer:
        errors.append("正解を入力してください")
    if len(correct_answer) > 100:
        errors.append("正解は100文字以内にしてください")
    if difficulty not in (1, 2, 3):
        errors.append("難易度は1〜3で選択してください")
    if grade not in (7, 8, 9):
        errors.append("学年は中1〜中3で選択してください")
    if subject not in ("math", "english"):
        errors.append("教科を選択してください")
    if problem_type not in ("practice", "unit_test"):
        errors.append("問題タイプを選択してください")
    if answer_type not in ("numeric", "text", "choice", "sort"):
        errors.append("解答形式を選択してください")

    answer_input_spec_val, spec_err = normalize_answer_input_spec_for_storage(answer_input_spec_raw)
    if spec_err:
        errors.append(spec_err)

    # choices のバリデーション（choice/sort の場合は必須）
    choices_list: list[str] = []
    if answer_type in ("choice", "sort"):
        choices_list = [c.strip() for c in choices_raw.split(",") if c.strip()]
        if len(choices_list) < 2:
            errors.append("選択肢 / 並び替え単語を2つ以上カンマ区切りで入力してください")
        if answer_type == "choice" and len(choices_list) > 8:
            errors.append("選択肢は8つ以内にしてください")

    unit_exists = db.scalar(select(UnitDependency).where(UnitDependency.unit_id == unit)) is not None
    if not unit_exists:
        errors.append("指定された単元が存在しません")

    invalid_errors = [p for p in error_pattern_candidates if p not in KNOWN_ERROR_PATTERNS]
    if invalid_errors:
        errors.append(f"不正な誤答パターン: {', '.join(invalid_errors)}")
    invalid_interventions = [p for p in intervention_candidates if p not in KNOWN_INTERVENTION_CANDIDATES]
    if invalid_interventions:
        errors.append(f"不正な介入タイプ: {', '.join(invalid_interventions)}")

    if errors:
        all_units = db.scalars(select(UnitDependency).order_by(UnitDependency.display_order.asc())).all()
        return templates.TemplateResponse(
            "teacher_problem_create.html",
            {
                "request": request,
                "auth_role": "teacher",
                "errors": errors,
                "all_units": all_units,
                "known_error_patterns": sorted(KNOWN_ERROR_PATTERNS),
                "known_intervention_candidates": sorted(KNOWN_INTERVENTION_CANDIDATES),
                "error_pattern_labels": {
                    "sign_error": "符号エラー", "arithmetic_error": "計算ミス",
                    "absolute_value_error": "絶対値エラー", "operation_confusion": "演算混同",
                    "careless_error": "ケアレスミス", "variable_handling_error": "文字の扱いミス",
                    "formula_setup_error": "式の立て方ミス", "comprehension_gap": "理解不足",
                    "prerequisite_gap": "前提知識の欠落", "unknown_error": "その他",
                },
                "intervention_labels": {
                    "reinforce_same_pattern": "同型問題で補強", "retry_with_hint": "ヒント付きで再挑戦",
                    "fallback_prerequisite": "前提単元を補強", "slow_down_and_confirm": "速度を落として確認",
                    "explain_differently": "別の説明で補助", "teacher_intervention_needed": "教師の短時間介入",
                    "advance_with_confidence": "自信を持って次へ", "monitor_only": "経過観察",
                },
                "form_values": {
                    "subject": subject, "grade": grade, "unit": unit,
                    "problem_type": problem_type, "difficulty": difficulty,
                    "question_text": question_text, "answer_type": answer_type,
                    "correct_answer": correct_answer, "hint_1": hint_1,
                    "choices_raw": choices_raw,
                    "answer_input_spec_raw": answer_input_spec_raw,
                    "hint_2": hint_2, "explanation_base": explanation_base,
                    "error_pattern_candidates": error_pattern_candidates,
                    "intervention_candidates": intervention_candidates,
                },
            },
            status_code=422,
        )

    import json as _json
    epc_json = _json.dumps(error_pattern_candidates or ["unknown_error"], ensure_ascii=False)
    ic_json = _json.dumps(intervention_candidates, ensure_ascii=False) if intervention_candidates else None
    choices_json = _json.dumps(choices_list, ensure_ascii=False) if choices_list else None

    status = "approved" if auto_approve == "1" else "pending"
    problem = Problem(
        subject=subject,
        grade=grade,
        unit=unit,
        full_unit_id=full_unit_id.strip() or None,
        problem_type=problem_type,
        difficulty=difficulty,
        question_text=question_text,
        answer_type=answer_type,
        choices=choices_json,
        correct_answer=correct_answer,
        hint_1=hint_1.strip() or None,
        hint_2=hint_2.strip() or None,
        explanation_base=explanation_base.strip() or None,
        error_pattern_candidates=epc_json,
        intervention_candidates=ic_json,
        answer_input_spec=answer_input_spec_val,
        status=status,
    )
    db.add(problem)
    db.commit()
    db.refresh(problem)

    if status == "approved":
        return RedirectResponse(url=f"/teachers/problems/{problem.problem_id}/preview", status_code=303)
    return RedirectResponse(url="/teachers/problems/pending", status_code=303)

# =============================================================================
# 将来実装予定: 画像OCRエンドポイント (Google Cloud Vision API)
# @router.post("/problems/ocr_extract")
# def ocr_extract_problem_text(image: UploadFile, request: Request):
#     """JPEG画像から問題文を抽出してフォームに流し込む用。
#     Google Cloud Vision API を使用予定。約0.2円/枚。
#     フロント側の「画像から読み込む」ボタンが実装されたときに有効化する。
#     """
#     pass
# =============================================================================


# ---------------------------------------------------------------------------
# 問題プリント作成
# ---------------------------------------------------------------------------

@router.get("/problems/print_set", response_class=HTMLResponse)
def print_set_form(request: Request, db: Session = Depends(get_db)):
    auth = require_teacher_login(request)
    if auth is not None:
        return auth

    math_units = db.scalars(
        select(UnitDependency)
        .where(UnitDependency.subject == "math")
        .order_by(UnitDependency.display_order.asc())
    ).all()

    return templates.TemplateResponse(
        "teacher_print_set_form.html",
        {
            "request": request,
            "auth_role": "teacher",
            "units": math_units,
        },
    )


@router.post("/problems/print_set/preview", response_class=HTMLResponse)
async def print_set_preview(request: Request, db: Session = Depends(get_db)):
    auth = require_teacher_login(request)
    if auth is not None:
        return auth

    form = await request.form()
    selected_units: list[str] = form.getlist("selected_units")
    raw_difficulties: list[str] = form.getlist("difficulties")
    count = int(form.get("count", "10"))
    count = count if count in (5, 10, 15) else 10
    output_type = form.get("output_type", "student")

    difficulties = [int(d) for d in raw_difficulties if d.isdigit()]

    errors: list[str] = []
    if not selected_units:
        errors.append("単元を1つ以上選択してください。")
    if not difficulties:
        errors.append("難易度を1つ以上選択してください。")

    problems = []
    if not errors:
        problems = db.scalars(
            select(Problem)
            .where(
                Problem.subject == "math",
                Problem.full_unit_id.in_(selected_units),
                Problem.difficulty.in_(difficulties),
                Problem.status == "approved",
                Problem.problem_type == "practice",
            )
            .order_by(func.random())
            .limit(count)
        ).all()

        if not problems:
            errors.append("指定した条件で問題が見つかりませんでした。単元・難易度の選択を確認してください。")

    unit_labels = get_unit_label_map(db)

    # 選択単元の表示名リスト（プリントヘッダー用）
    unit_names = [unit_labels.get(u, u) for u in selected_units]

    return templates.TemplateResponse(
        "teacher_print_preview.html",
        {
            "request": request,
            "problems": problems,
            "output_type": output_type,
            "unit_names": unit_names,
            "count": count,
            "difficulties": difficulties,
            "errors": errors,
        },
    )


@router.get("/problems/pending", response_class=HTMLResponse)
def teacher_approval_queue(request: Request, db: Session = Depends(get_db)):
    auth = require_teacher_login(request)
    if auth is not None:
        return auth

    pending_problems = db.scalars(
        select(Problem)
        .where(Problem.status == 'pending')
        .order_by(Problem.grade.asc(), Problem.unit.asc(), Problem.problem_id.asc())
    ).all()
    unit_labels = get_unit_label_map(db)
    full_unit_labels = {item["full_unit_id"]: item["display_name"] for item in load_all_unit_maps()}
    return templates.TemplateResponse(
        "teacher_approval_queue.html",
        {
            "request": request,
            "auth_role": "teacher",
            "pending_problems": pending_problems,
            "unit_labels": unit_labels,
            "full_unit_labels": full_unit_labels,
        },
    )


@router.post("/problems/{problem_id}/approve")
def approve_problem(problem_id: int, request: Request, db: Session = Depends(get_db)):
    require_teacher_login(request, api=True)
    problem = db.get(Problem, problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="problem not found")
    problem.status = 'approved'
    db.commit()
    return {"status": "ok", "problem_id": problem_id, "new_status": "approved"}


@router.post("/problems/{problem_id}/reject")
def reject_problem(problem_id: int, request: Request, db: Session = Depends(get_db)):
    require_teacher_login(request, api=True)
    problem = db.get(Problem, problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="problem not found")
    problem.status = 'rejected'
    db.commit()
    return {"status": "ok", "problem_id": problem_id, "new_status": "rejected"}


@router.get("/problems/{problem_id}/preview", response_class=HTMLResponse)
def teacher_problem_preview(request: Request, problem_id: int, db: Session = Depends(get_db)):
    auth = require_teacher_login(request)
    if auth is not None:
        return auth

    problem = db.get(Problem, problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="problem not found")

    unit_labels = get_unit_label_map(db)
    diagram_display = get_diagram_display_info(problem, route="teacher_preview")
    return templates.TemplateResponse(
        "problem_preview.html",
        {
            "request": request,
            "problem": problem,
            "diagram_svg": render_problem_diagram_for_route(problem, "teacher_preview"),
            "diagram_display": diagram_display,
            "unit_labels": unit_labels,
            "auth_role": "teacher",
        },
    )


@router.post("/override/{student_id}/next_problem")
def set_teacher_override(student_id: int, payload: TeacherOverrideRequest, request: Request, db: Session = Depends(get_db)):
    require_teacher_login(request, api=True)
    session = read_session(request)
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="student not found")
    ensure_session_classroom_access(session, student.classroom_id)

    state = db.get(StudentState, student_id)
    if state is None:
        raise HTTPException(status_code=404, detail="student_state not found")

    problem = db.get(Problem, payload.problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="problem not found")

    state.teacher_override_problem_id = payload.problem_id
    db.add(state)
    db.commit()
    return {"status": "ok", "override_problem_id": payload.problem_id}


@router.post("/annotation/{student_id}")
def create_teacher_annotation(student_id: int, payload: TeacherAnnotationRequest, request: Request, db: Session = Depends(get_db)):
    require_teacher_login(request, api=True)
    session = read_session(request)
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="student not found")
    ensure_session_classroom_access(session, student.classroom_id)
    if payload.diagnostic_correction not in VALID_DIAGNOSTIC_LABELS:
        raise HTTPException(status_code=422, detail="invalid diagnostic_correction")
    if payload.reason_code is not None and payload.reason_code not in VALID_REASON_CODES:
        raise HTTPException(status_code=422, detail="invalid reason_code")

    annotation = TeacherAnnotation(
        student_id=student_id,
        teacher_id=session.get("teacher_id"),
        diagnostic_correction=payload.diagnostic_correction,
        reason_code=payload.reason_code,
        note=payload.note,
        created_at=datetime.utcnow().isoformat(),
        expires_at=payload.expires_at,
    )
    db.add(annotation)
    db.commit()
    db.refresh(annotation)
    return {"status": "ok", "annotation_id": annotation.annotation_id}


class UnitIntroUpdateRequest(BaseModel):
    intro_html: str = Field(default="", max_length=2000)


@router.put("/units/{unit_id}/intro")
def update_unit_intro(unit_id: str, payload: UnitIntroUpdateRequest, request: Request, db: Session = Depends(get_db)):
    """単元の説明（intro_html）を更新する"""
    require_teacher_login(request, api=True)
    unit = db.get(UnitDependency, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="unit not found")
    unit.intro_html = payload.intro_html.strip() or None
    db.add(unit)
    db.commit()
    return {"status": "ok", "unit_id": unit_id}


@router.post("/units/{unit_id}/lecture/generate")
def generate_unit_lecture(unit_id: str, request: Request, db: Session = Depends(get_db)):
    """単元レクチャー（steps + intro）をcascadeテンプレートで再生成してDBに保存（教師専用）"""
    require_teacher_login(request, api=True)
    unit = db.get(UnitDependency, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="unit not found")

    import json as _json
    from ..services.unit_intro_service import generate_unit_intro

    steps_data = generate_lecture_steps(unit)
    unit.lecture_steps_json = _json.dumps(steps_data, ensure_ascii=False)

    intro_html = generate_unit_intro(unit)
    unit.intro_html = intro_html

    db.add(unit)
    db.commit()
    return {
        "status": "ok",
        "unit_id": unit_id,
        "step_count": len(steps_data.get("steps", [])),
        "intro_generated": True,
    }


@router.get("/students/{student_id}/weekly_report", response_class=HTMLResponse)
def weekly_report(
    request: Request,
    student_id: int,
    db: Session = Depends(get_db),
):
    auth = require_teacher_login(request)
    if auth is not None:
        return auth
    session = read_session(request)
    current_teacher = db.get(Teacher, session.get("teacher_id")) if session.get("teacher_id") else None
    if current_teacher is None:
        raise HTTPException(status_code=403, detail="teacher access denied")

    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="student not found")
    ensure_session_classroom_access(session, student.classroom_id)

    from datetime import timedelta

    today = datetime.utcnow()
    # 月曜 00:00 始まり（Python weekday は月曜=0）。以前の +1 は1 日ずれていた。
    week_start = today - timedelta(days=today.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)

    # 今週のログ
    week_logs = db.execute(
        select(LearningLog, Problem)
        .join(Problem, LearningLog.problem_id == Problem.problem_id)
        .where(
            LearningLog.student_id == student_id,
            LearningLog.created_at >= week_start,
            LearningLog.created_at < week_end,
        )
        .order_by(LearningLog.created_at.asc())
    ).all()

    total_problems = len(week_logs)
    correct_count = sum(1 for log, _ in week_logs if log.is_correct)
    correct_rate = round(correct_count / total_problems * 100) if total_problems > 0 else 0

    # 先週のログ（比較用）
    prev_start = week_start - timedelta(days=7)
    prev_logs = db.execute(
        select(LearningLog)
        .where(
            LearningLog.student_id == student_id,
            LearningLog.created_at >= prev_start,
            LearningLog.created_at < week_start,
        )
    ).all()
    prev_total = len(prev_logs)
    prev_correct = sum(1 for (log,) in prev_logs if log.is_correct)
    prev_rate = round(prev_correct / prev_total * 100) if prev_total > 0 else None

    # 単元別サマリー
    from collections import defaultdict
    unit_stats: dict[str, dict] = defaultdict(lambda: {"correct": 0, "total": 0, "unit_id": ""})
    for log, problem in week_logs:
        uid = problem.unit
        unit_stats[uid]["unit_id"] = uid
        unit_stats[uid]["total"] += 1
        if log.is_correct:
            unit_stats[uid]["correct"] += 1

    unit_labels = get_unit_label_map(db)

    # UnitMastery（今週活動した単元の習熟度）
    active_unit_ids = list(unit_stats.keys())
    mastery_rows = {
        m.unit_id: m
        for m in db.scalars(
            select(UnitMastery).where(
                UnitMastery.student_id == student_id,
                UnitMastery.unit_id.in_(active_unit_ids),
            )
        ).all()
    } if active_unit_ids else {}

    unit_summary = []
    for uid, stats in unit_stats.items():
        mastery = mastery_rows.get(uid)
        unit_summary.append({
            "unit_id": uid,
            "display_name": unit_labels.get(uid, uid),
            "total": stats["total"],
            "correct": stats["correct"],
            "rate": round(stats["correct"] / stats["total"] * 100) if stats["total"] > 0 else 0,
            "mastery_score": round(float(mastery.mastery_score or 0)) if mastery else 0,
        })
    unit_summary.sort(key=lambda x: x["total"], reverse=True)

    # 誤答パターン集計
    error_counts: dict[str, int] = defaultdict(int)
    for log, _ in week_logs:
        if not log.is_correct and log.error_pattern:
            error_counts[log.error_pattern] += 1
    error_summary = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:3]

    error_labels = {
        "sign_error": "符号ミス",
        "arithmetic_error": "計算ミス",
        "absolute_value_error": "絶対値エラー",
        "operation_confusion": "演算混同",
        "careless_error": "ケアレスミス",
        "variable_handling_error": "文字の扱いミス",
        "formula_setup_error": "式の立て方",
        "comprehension_gap": "理解不足",
        "prerequisite_gap": "前提知識の欠落",
        "unknown_error": "その他",
    }

    state = db.get(StudentState, student_id)
    current_unit_name = unit_labels.get(state.current_unit, state.current_unit) if state and state.current_unit else "-"

    classroom = db.get(Classroom, student.classroom_id) if student.classroom_id else None

    trend = None
    if prev_rate is not None:
        diff = correct_rate - prev_rate
        if diff >= 5:
            trend = "up"
        elif diff <= -5:
            trend = "down"
        else:
            trend = "flat"

    inclusive_week_end = week_end - timedelta(days=1)
    period_start_md = f"{week_start.month}月{week_start.day}日"
    period_end_md = f"{inclusive_week_end.month}月{inclusive_week_end.day}日"
    trend_prompt = weekly_trend_text_for_prompt(trend, prev_rate, correct_rate)
    unit_names_for_ai = "、".join(u["display_name"] for u in unit_summary[:10]) if unit_summary else "（なし）"
    top_errors_for_ai = (
        "、".join(f"{error_labels.get(p, p)}×{c}" for p, c in error_summary) if error_summary else "特になし"
    )
    try:
        ai_weekly_draft = (
            generate_weekly_parent_message_ai(
                period_start_md,
                period_end_md,
                total_problems,
                correct_rate,
                trend_prompt,
                unit_names_for_ai,
                top_errors_for_ai,
            )
            or ""
        )
    except Exception:
        ai_weekly_draft = ""

    return templates.TemplateResponse(
        "teacher_weekly_report.html",
        {
            "request": request,
            "auth_role": "teacher",
            "student": student,
            "classroom": classroom,
            "state": state,
            "current_unit_name": current_unit_name,
            "week_start": week_start,
            "week_end": inclusive_week_end,
            "period_start_md": period_start_md,
            "period_end_md": period_end_md,
            "total_problems": total_problems,
            "correct_count": correct_count,
            "correct_rate": correct_rate,
            "prev_rate": prev_rate,
            "trend": trend,
            "unit_summary": unit_summary,
            "error_summary": error_summary,
            "error_labels": error_labels,
            "ai_weekly_draft": ai_weekly_draft,
        },
    )


@router.get("/students/{student_id}/today_progress", response_class=HTMLResponse)
def today_progress(
    request: Request,
    student_id: int,
    db: Session = Depends(get_db),
):
    auth = require_teacher_login(request)
    if auth is not None:
        return auth
    session = read_session(request)
    current_teacher = db.get(Teacher, session.get("teacher_id")) if session.get("teacher_id") else None
    if current_teacher is None:
        raise HTTPException(status_code=403, detail="teacher access denied")

    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="student not found")
    ensure_session_classroom_access(session, student.classroom_id)

    agg = aggregate_today_learning_logs(db, student_id)
    diag = build_diagnostic_snapshot(db, student_id)
    diagnostic_label_ja = DIAGNOSTIC_LABELS_JA.get(
        diag.get("diagnostic_label", ""), diag.get("diagnostic_label", "-")
    )

    error_labels = {
        "sign_error": "符号ミス",
        "arithmetic_error": "計算ミス",
        "absolute_value_error": "絶対値エラー",
        "operation_confusion": "演算混同",
        "careless_error": "ケアレスミス",
        "variable_handling_error": "文字の扱いミス",
        "formula_setup_error": "式の立て方",
        "comprehension_gap": "理解不足",
        "prerequisite_gap": "前提知識の欠落",
        "unknown_error": "その他",
    }

    tp_key = agg["top_error_pattern_key"]
    top_err_ja = error_labels.get(tp_key, tp_key) if tp_key else "特になし"

    unit_join = "、".join(agg["unit_names"])
    has_logs = agg["total_count"] > 0
    parent_message = ""
    if has_logs:
        parent_message = generate_today_parent_message_ai(
            agg["jst_date_header"],
            unit_join,
            agg["total_count"],
            agg["correct_count"],
            diagnostic_label_ja,
            top_err_ja,
        ) or build_today_fallback_message(
            agg["jst_month_day"],
            unit_join,
            agg["total_count"],
            agg["correct_count"],
            agg["rate"],
            tp_key,
        )

    classroom = db.get(Classroom, student.classroom_id) if student.classroom_id else None

    return templates.TemplateResponse(
        "teacher_today_progress.html",
        {
            "request": request,
            "auth_role": "teacher",
            "student": student,
            "classroom": classroom,
            "jst_date_header": agg["jst_date_header"],
            "unit_names": agg["unit_names"],
            "unit_join": unit_join,
            "has_logs": has_logs,
            "total_count": agg["total_count"],
            "correct_count": agg["correct_count"],
            "wrong_count": agg["wrong_count"],
            "rate": agg["rate"],
            "hint_total": agg["hint_total"],
            "top_error_patterns": agg["top_error_patterns"],
            "error_labels": error_labels,
            "diagnostic_label_ja": diagnostic_label_ja,
            "parent_message": parent_message,
        },
    )
