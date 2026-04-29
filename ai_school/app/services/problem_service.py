import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..models import Classroom, Problem, Student, StudentState, Teacher, UnitDependency, UnitMastery
from .auth_service import seed_auth_credentials
from .classroom_ops_service import allocate_classroom_code
from .unit_map_service import resolve_full_unit_id


def load_seed_payload() -> dict:
    seed_path = Path(__file__).resolve().parents[3] / "data" / "seed_problems.json"
    with seed_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_english_seed_payload() -> dict:
    seed_path = Path(__file__).resolve().parents[3] / "data" / "seed_english_units.json"
    with seed_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def seed_initial_data(db: Session) -> None:
    payload = load_seed_payload()

    for unit_data in payload["unit_dependencies"]:
        existing_unit = db.get(UnitDependency, unit_data["unit_id"])
        if existing_unit is None:
            db.add(UnitDependency(**unit_data))
        else:
            for key, value in unit_data.items():
                setattr(existing_unit, key, value)

    for problem_data in payload["problems"]:
        if "full_unit_id" not in problem_data:
            problem_data["full_unit_id"] = resolve_full_unit_id(problem_data.get("unit"), problem_data.get("sub_unit"))
        if "sub_unit" not in problem_data:
            problem_data["sub_unit"] = None
        if "diagram" not in problem_data:
            problem_data["diagram"] = None
        if "diagram_required" not in problem_data:
            problem_data["diagram_required"] = False
        if "diagram_params" not in problem_data:
            problem_data["diagram_params"] = None
        if "hint_1" not in problem_data:
            problem_data["hint_1"] = problem_data.get("hint_text")
        if "hint_2" not in problem_data:
            problem_data["hint_2"] = problem_data.get("explanation_base")
        if "problem_type" not in problem_data:
            problem_data["problem_type"] = "practice"
        if "test_scope" not in problem_data:
            problem_data["test_scope"] = None
        if "error_pattern_candidates" in problem_data and isinstance(problem_data["error_pattern_candidates"], list):
            problem_data["error_pattern_candidates"] = json.dumps(problem_data["error_pattern_candidates"], ensure_ascii=False)
        if "intervention_candidates" in problem_data and isinstance(problem_data["intervention_candidates"], list):
            problem_data["intervention_candidates"] = json.dumps(problem_data["intervention_candidates"], ensure_ascii=False)
        if "diagram_params" in problem_data and isinstance(problem_data["diagram_params"], dict):
            problem_data["diagram_params"] = json.dumps(problem_data["diagram_params"], ensure_ascii=False)
        if "answer_input_spec" not in problem_data:
            problem_data["answer_input_spec"] = None
        if "answer_input_spec" in problem_data and isinstance(problem_data["answer_input_spec"], dict):
            problem_data["answer_input_spec"] = json.dumps(problem_data["answer_input_spec"], ensure_ascii=False)
        existing_problem = db.get(Problem, problem_data["problem_id"])
        if existing_problem is None:
            db.add(Problem(**problem_data))
        else:
            for key, value in problem_data.items():
                setattr(existing_problem, key, value)

    for student_data in payload["students"]:
        if "classroom_id" not in student_data:
            student_data["classroom_id"] = None
        existing_student = db.get(Student, student_data["student_id"])
        if existing_student is None:
            db.add(Student(**student_data))
        else:
            for key, value in student_data.items():
                setattr(existing_student, key, value)
            existing_student.is_active = True

    db.flush()

    for state_data in payload["student_state"]:
        existing_state = db.get(StudentState, state_data["student_id"])
        if existing_state is None:
            db.add(StudentState(**state_data))
        else:
            for key, value in state_data.items():
                setattr(existing_state, key, value)

    unit_ids = [unit["unit_id"] for unit in payload["unit_dependencies"]]
    for student_data in payload["students"]:
        for unit_id in unit_ids:
            existing_mastery = db.get(UnitMastery, (student_data["student_id"], unit_id))
            if existing_mastery is None:
                db.add(
                    UnitMastery(
                        student_id=student_data["student_id"],
                        unit_id=unit_id,
                        mastery_score=0.0,
                        correct_count=0,
                        wrong_count=0,
                        hint_count=0,
                        avg_elapsed_sec=0.0,
                    )
                )

    db.commit()
    seed_auth_credentials(db)

    # 英語単元をシード
    _seed_english_units(db)


def _seed_english_units(db: Session) -> None:
    payload = load_english_seed_payload()
    for unit_data in payload["unit_dependencies"]:
        existing_unit = db.get(UnitDependency, unit_data["unit_id"])
        if existing_unit is None:
            db.add(UnitDependency(**unit_data))
        else:
            for key, value in unit_data.items():
                setattr(existing_unit, key, value)
    db.commit()


def ensure_runtime_schema(db: Session) -> None:
    problem_columns = {row[1] for row in db.execute(text("PRAGMA table_info(problems)")).all()}
    log_columns = {row[1] for row in db.execute(text("PRAGMA table_info(learning_log)")).all()}
    student_columns = {row[1] for row in db.execute(text("PRAGMA table_info(students)")).all()}
    student_state_columns = {row[1] for row in db.execute(text("PRAGMA table_info(student_state)")).all()}
    teacher_columns = {row[1] for row in db.execute(text("PRAGMA table_info(teachers)")).all()}
    classroom_columns = {row[1] for row in db.execute(text("PRAGMA table_info(classrooms)")).all()}
    owner_columns = {row[1] for row in db.execute(text("PRAGMA table_info(owners)")).all()}
    if "hint_1" not in problem_columns:
        db.execute(text("ALTER TABLE problems ADD COLUMN hint_1 TEXT"))
    if "hint_2" not in problem_columns:
        db.execute(text("ALTER TABLE problems ADD COLUMN hint_2 TEXT"))
    if "full_unit_id" not in problem_columns:
        db.execute(text("ALTER TABLE problems ADD COLUMN full_unit_id TEXT"))
    if "sub_unit" not in problem_columns:
        db.execute(text("ALTER TABLE problems ADD COLUMN sub_unit TEXT"))
    if "diagram" not in problem_columns:
        db.execute(text("ALTER TABLE problems ADD COLUMN diagram TEXT"))
    if "diagram_required" not in problem_columns:
        db.execute(text("ALTER TABLE problems ADD COLUMN diagram_required BOOLEAN NOT NULL DEFAULT 0"))
    if "diagram_params" not in problem_columns:
        db.execute(text("ALTER TABLE problems ADD COLUMN diagram_params TEXT"))
    if "error_pattern_candidates" not in problem_columns:
        db.execute(text("ALTER TABLE problems ADD COLUMN error_pattern_candidates TEXT"))
    if "intervention_candidates" not in problem_columns:
        db.execute(text("ALTER TABLE problems ADD COLUMN intervention_candidates TEXT"))
    if "status" not in problem_columns:
        db.execute(text("ALTER TABLE problems ADD COLUMN status TEXT NOT NULL DEFAULT 'approved'"))
    if "problem_type" not in problem_columns:
        db.execute(text("ALTER TABLE problems ADD COLUMN problem_type TEXT NOT NULL DEFAULT 'practice'"))
    if "test_scope" not in problem_columns:
        db.execute(text("ALTER TABLE problems ADD COLUMN test_scope TEXT"))
    if "choices" not in problem_columns:
        db.execute(text("ALTER TABLE problems ADD COLUMN choices TEXT"))
    if "answer_input_spec" not in problem_columns:
        db.execute(text("ALTER TABLE problems ADD COLUMN answer_input_spec TEXT"))
    if "route_decision" not in log_columns:
        db.execute(text("ALTER TABLE learning_log ADD COLUMN route_decision TEXT"))
    if "error_pattern" not in log_columns:
        db.execute(text("ALTER TABLE learning_log ADD COLUMN error_pattern TEXT"))
    if "intervention_type" not in log_columns:
        db.execute(text("ALTER TABLE learning_log ADD COLUMN intervention_type TEXT"))
    if "canvas_image" not in log_columns:
        db.execute(text("ALTER TABLE learning_log ADD COLUMN canvas_image TEXT"))
    if "login_pin_hash" not in student_columns:
        db.execute(text("ALTER TABLE students ADD COLUMN login_pin_hash TEXT"))
    if "is_active" not in student_columns:
        db.execute(text("ALTER TABLE students ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
    if "pin_last_reset_at" not in student_columns:
        db.execute(text("ALTER TABLE students ADD COLUMN pin_last_reset_at TEXT"))
    if "classroom_id" not in student_columns:
        db.execute(text("ALTER TABLE students ADD COLUMN classroom_id INTEGER"))
    if "teacher_override_problem_id" not in student_state_columns:
        db.execute(text("ALTER TABLE student_state ADD COLUMN teacher_override_problem_id INTEGER"))
    if "ai_summary_text" not in student_state_columns:
        db.execute(text("ALTER TABLE student_state ADD COLUMN ai_summary_text TEXT"))
    if "ai_summary_updated_at" not in student_state_columns:
        db.execute(text("ALTER TABLE student_state ADD COLUMN ai_summary_updated_at TEXT"))
    if "adaptive_streak" not in student_state_columns:
        db.execute(text("ALTER TABLE student_state ADD COLUMN adaptive_streak INTEGER NOT NULL DEFAULT 0"))
    if "adaptive_last_generated_key" not in student_state_columns:
        db.execute(text("ALTER TABLE student_state ADD COLUMN adaptive_last_generated_key TEXT"))
    if "adaptive_last_generated_at" not in student_state_columns:
        db.execute(text("ALTER TABLE student_state ADD COLUMN adaptive_last_generated_at TEXT"))
    if "unit_unlock_mode" not in student_state_columns:
        db.execute(text("ALTER TABLE student_state ADD COLUMN unit_unlock_mode TEXT"))
    if "unit_unlock_up_to" not in student_state_columns:
        db.execute(text("ALTER TABLE student_state ADD COLUMN unit_unlock_up_to TEXT"))
    if "discovered_nuances" not in student_state_columns:
        db.execute(text("ALTER TABLE student_state ADD COLUMN discovered_nuances TEXT"))
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS conversation_log ("
            "log_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "student_id INTEGER NOT NULL,"
            "role TEXT NOT NULL,"
            "entry_type TEXT NOT NULL DEFAULT 'ai_feedback',"
            "content TEXT NOT NULL,"
            "intervention_type TEXT,"
            "problem_id INTEGER,"
            "created_at TEXT NOT NULL)"
        )
    )
    conversation_columns = {row[1] for row in db.execute(text("PRAGMA table_info(conversation_log)")).all()}
    if "entry_type" not in conversation_columns:
        db.execute(text("ALTER TABLE conversation_log ADD COLUMN entry_type TEXT NOT NULL DEFAULT 'ai_feedback'"))
    db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_conversation_student_created_at "
            "ON conversation_log(student_id, created_at)"
        )
    )
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS teacher_annotation ("
            "annotation_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "student_id INTEGER NOT NULL,"
            "teacher_id INTEGER,"
            "diagnostic_correction TEXT NOT NULL,"
            "reason_code TEXT,"
            "note TEXT,"
            "created_at TEXT NOT NULL,"
            "expires_at TEXT)"
        )
    )
    db.execute(
        text("CREATE INDEX IF NOT EXISTS idx_teacher_annotation_student_id ON teacher_annotation(student_id)")
    )
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS teachers ("
            "teacher_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "classroom_id INTEGER,"
            "login_id TEXT NOT NULL UNIQUE,"
            "password_hash TEXT NOT NULL,"
            "display_name TEXT NOT NULL,"
            "is_active BOOLEAN NOT NULL DEFAULT 1,"
            "created_at TEXT NOT NULL,"
            "updated_at TEXT)"
        )
    )
    if "classroom_id" not in teacher_columns:
        db.execute(text("ALTER TABLE teachers ADD COLUMN classroom_id INTEGER"))
    if "updated_at" not in teacher_columns:
        db.execute(text("ALTER TABLE teachers ADD COLUMN updated_at TEXT"))
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS classrooms ("
            "classroom_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "classroom_name TEXT NOT NULL,"
            "login_id TEXT NOT NULL UNIQUE,"
            "password_hash TEXT NOT NULL,"
            "is_active BOOLEAN NOT NULL DEFAULT 1,"
            "created_at TEXT NOT NULL,"
            "updated_at TEXT,"
            "contact_name TEXT,"
            "note TEXT)"
        )
    )
    classroom_columns = {row[1] for row in db.execute(text("PRAGMA table_info(classrooms)")).all()}
    if "updated_at" not in classroom_columns:
        db.execute(text("ALTER TABLE classrooms ADD COLUMN updated_at TEXT"))
    if "unit_unlock_mode" not in classroom_columns:
        db.execute(text("ALTER TABLE classrooms ADD COLUMN unit_unlock_mode TEXT NOT NULL DEFAULT 'progressive'"))
    if "unit_unlock_up_to" not in classroom_columns:
        db.execute(text("ALTER TABLE classrooms ADD COLUMN unit_unlock_up_to TEXT"))
    classroom_columns = {row[1] for row in db.execute(text("PRAGMA table_info(classrooms)")).all()}
    if "external_classroom_id" not in classroom_columns:
        db.execute(text("ALTER TABLE classrooms ADD COLUMN external_classroom_id TEXT"))
    if "is_archived" not in classroom_columns:
        db.execute(text("ALTER TABLE classrooms ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0"))
    if "admin_email" not in classroom_columns:
        db.execute(text("ALTER TABLE classrooms ADD COLUMN admin_email TEXT"))
    if "admin_phone" not in classroom_columns:
        db.execute(text("ALTER TABLE classrooms ADD COLUMN admin_phone TEXT"))
    if "last_activity_at" not in classroom_columns:
        db.execute(text("ALTER TABLE classrooms ADD COLUMN last_activity_at TEXT"))
    classroom_columns = {row[1] for row in db.execute(text("PRAGMA table_info(classrooms)")).all()}
    if "code" not in classroom_columns:
        db.execute(text("ALTER TABLE classrooms ADD COLUMN code TEXT"))
    if "tablet_mode" not in classroom_columns:
        db.execute(text("ALTER TABLE classrooms ADD COLUMN tablet_mode INTEGER NOT NULL DEFAULT 0"))
    for cid, lid, code in db.execute(
        text("SELECT classroom_id, login_id, code FROM classrooms ORDER BY classroom_id")
    ).all():
        if code is not None and str(code).strip():
            continue
        new_code = allocate_classroom_code(db, lid or "", cid)
        db.execute(
            text("UPDATE classrooms SET code = :c WHERE classroom_id = :id"),
            {"c": new_code, "id": cid},
        )
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS classroom_contracts ("
            "contract_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "classroom_id INTEGER NOT NULL UNIQUE,"
            "plan_name TEXT NOT NULL,"
            "max_students INTEGER NOT NULL,"
            "allowed_subjects TEXT NOT NULL,"
            "monthly_price INTEGER NOT NULL DEFAULT 0,"
            "yearly_price INTEGER NOT NULL DEFAULT 0,"
            "contract_start TEXT NOT NULL,"
            "contract_end TEXT,"
            "contract_status TEXT NOT NULL DEFAULT 'active',"
            "contract_memo TEXT,"
            "created_at TEXT NOT NULL,"
            "updated_at TEXT)"
        )
    )
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS classroom_deletion_logs ("
            "log_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "owner_id INTEGER,"
            "deleted_classroom_id INTEGER NOT NULL,"
            "classroom_name_snapshot TEXT NOT NULL,"
            "external_classroom_id_snapshot TEXT,"
            "login_id_snapshot TEXT,"
            "dependency_snapshot TEXT NOT NULL,"
            "deleted_at TEXT NOT NULL)"
        )
    )
    db.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_classrooms_external_classroom_id "
            "ON classrooms(external_classroom_id) WHERE external_classroom_id IS NOT NULL"
        )
    )
    db.execute(
        text(
            "UPDATE classrooms SET external_classroom_id = login_id "
            "WHERE external_classroom_id IS NULL OR trim(COALESCE(external_classroom_id, '')) = ''"
        )
    )
    for (cid,) in db.execute(text("SELECT classroom_id FROM classrooms")).all():
        exists = db.execute(
            text("SELECT 1 FROM classroom_contracts WHERE classroom_id = :cid LIMIT 1"),
            {"cid": cid},
        ).first()
        if exists is None:
            now = datetime.utcnow().isoformat()
            start = datetime.utcnow().strftime("%Y-%m-%d")
            db.execute(
                text(
                    "INSERT INTO classroom_contracts ("
                    "classroom_id, plan_name, max_students, allowed_subjects, "
                    "monthly_price, yearly_price, contract_start, contract_end, "
                    "contract_status, contract_memo, created_at, updated_at"
                    ") VALUES ("
                    ":cid, :plan_name, :max_students, :allowed_subjects, "
                    ":monthly_price, 0, :contract_start, NULL, 'active', NULL, :now, :now)"
                ),
                {
                    "cid": cid,
                    "plan_name": "QRelDo 30（スタンダードプラン・既存データ）",
                    "max_students": 30,
                    "allowed_subjects": "math_english",
                    "monthly_price": 29800,
                    "contract_start": start,
                    "now": now,
                },
            )
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS owners ("
            "owner_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "login_id TEXT NOT NULL UNIQUE,"
            "password_hash TEXT NOT NULL,"
            "display_name TEXT NOT NULL,"
            "is_active BOOLEAN NOT NULL DEFAULT 1,"
            "created_at TEXT NOT NULL,"
            "updated_at TEXT)"
        )
    )
    owner_columns = {row[1] for row in db.execute(text("PRAGMA table_info(owners)")).all()}
    if "updated_at" not in owner_columns:
        db.execute(text("ALTER TABLE owners ADD COLUMN updated_at TEXT"))
    if "gold" not in student_state_columns:
        db.execute(text("ALTER TABLE student_state ADD COLUMN gold INTEGER NOT NULL DEFAULT 0"))
    if "pending_challenge_problem_id" not in student_state_columns:
        db.execute(text("ALTER TABLE student_state ADD COLUMN pending_challenge_problem_id INTEGER"))
    unit_dep_columns = {row[1] for row in db.execute(text("PRAGMA table_info(unit_dependency)")).all()}
    if "intro_html" not in unit_dep_columns:
        db.execute(text("ALTER TABLE unit_dependency ADD COLUMN intro_html TEXT"))
    if "grade" not in unit_dep_columns:
        db.execute(text("ALTER TABLE unit_dependency ADD COLUMN grade INTEGER"))
    if "subject" not in unit_dep_columns:
        db.execute(text("ALTER TABLE unit_dependency ADD COLUMN subject TEXT NOT NULL DEFAULT 'math'"))
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS student_board_cells ("
            "cell_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "student_id INTEGER NOT NULL,"
            "unit_id TEXT NOT NULL,"
            "cell_index INTEGER NOT NULL,"
            "problem_id INTEGER NOT NULL,"
            "is_correct BOOLEAN NOT NULL,"
            "hint_used INTEGER NOT NULL DEFAULT 0,"
            "cell_type TEXT NOT NULL,"
            "ai_event_text TEXT,"
            "g_earned INTEGER NOT NULL DEFAULT 0,"
            "created_at TEXT NOT NULL)"
        )
    )
    db.execute(
        text("CREATE INDEX IF NOT EXISTS idx_board_cells_student_unit ON student_board_cells(student_id, unit_id)")
    )
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS listening_problems ("
            "id TEXT PRIMARY KEY,"
            "subject TEXT NOT NULL DEFAULT 'english',"
            "skill TEXT NOT NULL DEFAULT 'listening',"
            "grade_band INTEGER NOT NULL,"
            "full_unit_id TEXT NOT NULL,"
            "unit_id TEXT NOT NULL,"
            "problem_type TEXT NOT NULL DEFAULT 'practice',"
            "difficulty INTEGER NOT NULL DEFAULT 1,"
            "listening_type TEXT NOT NULL,"
            "listening_focus TEXT,"
            "audio_url TEXT NOT NULL,"
            "audio_script TEXT NOT NULL,"
            "audio_speed TEXT NOT NULL DEFAULT 'normal',"
            "play_limit INTEGER NOT NULL DEFAULT 2,"
            "question_text TEXT NOT NULL,"
            "choices TEXT NOT NULL,"
            "correct_answer TEXT NOT NULL,"
            "hint_1 TEXT,"
            "hint_2 TEXT,"
            "explanation_base TEXT NOT NULL,"
            "script_keyword TEXT,"
            "error_pattern_candidates TEXT,"
            "intervention_candidates TEXT,"
            "status TEXT NOT NULL DEFAULT 'pending',"
            "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
    )
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS listening_logs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "student_id INTEGER NOT NULL,"
            "classroom_id INTEGER NOT NULL,"
            "problem_id TEXT NOT NULL,"
            "is_correct INTEGER NOT NULL,"
            "selected_answer TEXT NOT NULL,"
            "play_count INTEGER NOT NULL DEFAULT 1,"
            "elapsed_sec INTEGER,"
            "hint_used INTEGER NOT NULL DEFAULT 0,"
            "error_pattern TEXT,"
            "intervention_type TEXT,"
            "route TEXT,"
            "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
    )
    db.execute(
        text("CREATE INDEX IF NOT EXISTS idx_listening_logs_classroom_created ON listening_logs(classroom_id, created_at)")
    )
    db.execute(
        text("CREATE INDEX IF NOT EXISTS idx_listening_logs_student_created ON listening_logs(student_id, created_at)")
    )
    try:
        test_session_columns = {row[1] for row in db.execute(text("PRAGMA table_info(test_sessions)")).all()}
    except Exception:
        test_session_columns = set()
    if test_session_columns:
        if "time_limit_sec" not in test_session_columns:
            db.execute(text("ALTER TABLE test_sessions ADD COLUMN time_limit_sec INTEGER NOT NULL DEFAULT 300"))
        if "time_spent_sec" not in test_session_columns:
            db.execute(text("ALTER TABLE test_sessions ADD COLUMN time_spent_sec INTEGER"))
        if "time_expired" not in test_session_columns:
            db.execute(text("ALTER TABLE test_sessions ADD COLUMN time_expired INTEGER NOT NULL DEFAULT 0"))
        if "deferred_problem_ids" not in test_session_columns:
            db.execute(text("ALTER TABLE test_sessions ADD COLUMN deferred_problem_ids TEXT"))
        if "defer_count" not in test_session_columns:
            db.execute(text("ALTER TABLE test_sessions ADD COLUMN defer_count INTEGER NOT NULL DEFAULT 0"))
        db.execute(
            text(
                "UPDATE test_sessions SET deferred_problem_ids = '[]' "
                "WHERE deferred_problem_ids IS NULL OR trim(COALESCE(deferred_problem_ids, '')) = ''"
            )
        )
        db.execute(
            text(
                "UPDATE test_sessions SET time_limit_sec = 600 "
                "WHERE test_scope = 'unit_test' AND COALESCE(time_limit_sec, 300) = 300"
            )
        )
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS listening_mastery ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "student_id INTEGER NOT NULL,"
            "classroom_id INTEGER NOT NULL,"
            "full_unit_id TEXT NOT NULL,"
            "mastery_score REAL NOT NULL DEFAULT 0.0,"
            "correct_count INTEGER NOT NULL DEFAULT 0,"
            "wrong_count INTEGER NOT NULL DEFAULT 0,"
            "hint_count INTEGER NOT NULL DEFAULT 0,"
            "avg_play_count REAL NOT NULL DEFAULT 1.0,"
            "avg_elapsed_sec REAL,"
            "updated_at TEXT NOT NULL DEFAULT (datetime('now')),"
            "UNIQUE(student_id, full_unit_id))"
        )
    )
    db.commit()


def get_problem_by_id(db: Session, problem_id: int) -> Problem | None:
    return db.get(Problem, problem_id)


def get_first_problem(db: Session) -> Problem | None:
    first_unit = db.scalar(
        select(UnitDependency)
        .where(UnitDependency.subject == "math")
        .order_by(UnitDependency.display_order.asc())
    )
    if first_unit is not None:
        stmt = (
            select(Problem)
            .where(Problem.full_unit_id == first_unit.unit_id, Problem.difficulty < 5, Problem.problem_type == 'practice', Problem.status == 'approved')
            .order_by(Problem.difficulty.asc(), Problem.problem_id.asc())
        )
        first_problem = db.scalar(stmt)
        if first_problem is not None:
            return first_problem
    stmt = select(Problem).where(Problem.problem_type == 'practice', Problem.status == 'approved', Problem.difficulty < 5).order_by(Problem.unit.asc(), Problem.difficulty.asc(), Problem.problem_id.asc())
    return db.scalar(stmt)


def get_first_problem_for_unit(db: Session, unit_id: str) -> Problem | None:
    subject = 'english' if unit_id.startswith('eng_') else 'math'
    stmt = (
        select(Problem)
        .where(
            Problem.full_unit_id == unit_id,
            Problem.subject == subject,
            Problem.difficulty < 5,
            Problem.problem_type == 'practice',
            Problem.status == 'approved',
        )
        .order_by(Problem.difficulty.asc(), Problem.problem_id.asc())
    )
    return db.scalar(stmt)


def get_challenge_problem(db: Session, student_id: int) -> "Problem | None":
    """難易度5の激ムズ問題をランダムに1問返す（通常ルーティングには載らない）"""
    from sqlalchemy import func
    stmt = (
        select(Problem)
        .where(Problem.difficulty == 5, Problem.problem_type == 'practice', Problem.status == 'approved')
        .order_by(func.random())
        .limit(1)
    )
    return db.scalar(stmt)


def get_approved_challenge_problem(db: Session, problem_id: int) -> "Problem | None":
    """Shop: difficulty 5, practice, approved only."""
    problem = db.get(Problem, problem_id)
    if problem is None:
        return None
    if problem.difficulty != 5 or problem.problem_type != "practice" or problem.status != "approved":
        return None
    return problem


def get_unit_dependency(db: Session, unit_id: str) -> UnitDependency | None:
    return db.get(UnitDependency, unit_id)


def get_unit_dependencies(db: Session) -> list[UnitDependency]:
    return db.scalars(select(UnitDependency).order_by(UnitDependency.display_order.asc())).all()


def get_unit_label_map(db: Session) -> dict[str, str]:
    return {unit.unit_id: unit.display_name for unit in get_unit_dependencies(db)}


def consume_teacher_override_problem(db: Session, state: StudentState) -> Problem | None:
    if state.teacher_override_problem_id is None:
        return None
    problem = db.get(Problem, state.teacher_override_problem_id)
    state.teacher_override_problem_id = None
    db.add(state)
    db.commit()
    db.refresh(state)
    return problem
