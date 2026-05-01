from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Classroom(Base):
    __tablename__ = "classrooms"

    classroom_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    classroom_name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str | None] = mapped_column(String(16), unique=True, nullable=True, index=True)
    tablet_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    external_classroom_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    login_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    admin_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    admin_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_activity_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    unit_unlock_mode: Mapped[str] = mapped_column(String(20), default="progressive", nullable=False)
    unit_unlock_up_to: Mapped[str | None] = mapped_column(String(100), nullable=True)

    contract: Mapped["ClassroomContract | None"] = relationship(
        back_populates="classroom",
        uselist=False,
    )


class ClassroomContract(Base):
    """教室ごとの契約（プラン）。最大生徒数・利用可能科目はここを主とする。"""

    __tablename__ = "classroom_contracts"

    contract_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.classroom_id"), unique=True, nullable=False, index=True)
    plan_name: Mapped[str] = mapped_column(String(200), nullable=False)
    max_students: Mapped[int] = mapped_column(Integer, nullable=False)
    allowed_subjects: Mapped[str] = mapped_column(String(60), nullable=False)
    monthly_price: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    yearly_price: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    contract_start: Mapped[str] = mapped_column(String(20), nullable=False)
    contract_end: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contract_status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    contract_memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)

    classroom: Mapped["Classroom"] = relationship(back_populates="contract")


class ClassroomDeletionLog(Base):
    """教室完全削除の実行ログ。"""

    __tablename__ = "classroom_deletion_logs"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deleted_classroom_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    classroom_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    external_classroom_id_snapshot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    login_id_snapshot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dependency_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    deleted_at: Mapped[str] = mapped_column(String(40), nullable=False)


class Problem(Base):
    __tablename__ = "problems"

    problem_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    subject: Mapped[str] = mapped_column(String(50), default="math")
    grade: Mapped[int] = mapped_column(Integer, default=7)
    unit: Mapped[str] = mapped_column(String(100), index=True)
    full_unit_id: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    sub_unit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    problem_type: Mapped[str] = mapped_column(String(30), default='practice', index=True)
    test_scope: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    difficulty: Mapped[int] = mapped_column(Integer, index=True)
    question_text: Mapped[str] = mapped_column(Text)
    diagram: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagram_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    diagram_params: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_type: Mapped[str] = mapped_column(String(30), default="numeric")
    choices: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array for choice/sort
    # Optional JSON: blanks[].id, label, input_mode, input_hint, input_example
    answer_input_spec: Mapped[str | None] = mapped_column(Text, nullable=True)
    correct_answer: Mapped[str] = mapped_column(String(100))
    hint_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    hint_1: Mapped[str | None] = mapped_column(Text, nullable=True)
    hint_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_base: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_pattern_candidates: Mapped[str | None] = mapped_column(Text, nullable=True)
    intervention_candidates: Mapped[str | None] = mapped_column(Text, nullable=True)
    prerequisite_unit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    next_if_correct: Mapped[int | None] = mapped_column(ForeignKey("problems.problem_id"), nullable=True)
    next_if_wrong: Mapped[int | None] = mapped_column(ForeignKey("problems.problem_id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='approved')


class UnitDependency(Base):
    __tablename__ = "unit_dependency"

    unit_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))
    subject: Mapped[str] = mapped_column(String(30), default="math", nullable=False)
    prerequisite_unit_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    next_unit_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, index=True)
    grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    intro_html: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    lecture_steps_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class UnitPrerequisite(Base):
    """Many-to-many prerequisite edges between units.

    Each row declares ``prerequisite_id`` is a foundation for ``unit_id``.
    ``weight`` is the multiplicative cost used by the recursive CTE in
    :mod:`ai_school.app.services.diagnostic_sql` for tie-breaking and future
    weighted-routing extensions; defaults to 1.0 (uniform).

    ``edge_kind`` distinguishes "hard" prerequisites (must be mastered first)
    from "soft" ones (helpful but not strictly required).
    """

    __tablename__ = "unit_prerequisites"
    __table_args__ = (
        UniqueConstraint("unit_id", "prerequisite_id", name="uq_unit_prerequisites_pair"),
    )

    unit_id: Mapped[str] = mapped_column(
        ForeignKey("unit_dependency.unit_id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    prerequisite_id: Mapped[str] = mapped_column(
        ForeignKey("unit_dependency.unit_id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    edge_kind: Mapped[str] = mapped_column(String(20), default="hard", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Student(Base):
    __tablename__ = "students"

    student_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    grade: Mapped[int] = mapped_column(Integer)
    classroom_id: Mapped[int | None] = mapped_column(ForeignKey("classrooms.classroom_id"), nullable=True, index=True)
    login_pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    pin_last_reset_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(30), default="active")

    state: Mapped["StudentState"] = relationship(back_populates="student", uselist=False)
    logs: Mapped[list["LearningLog"]] = relationship(back_populates="student")


class StudentState(Base):
    __tablename__ = "student_state"

    student_id: Mapped[int] = mapped_column(ForeignKey("students.student_id"), primary_key=True)
    current_unit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    current_level: Mapped[int] = mapped_column(Integer, default=1)
    mastery_score: Mapped[float] = mapped_column(Float, default=0.0)
    weak_unit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_problem_id: Mapped[int | None] = mapped_column(ForeignKey("problems.problem_id"), nullable=True)
    teacher_override_problem_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gold: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pending_challenge_problem_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ai_summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_summary_updated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    adaptive_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    adaptive_last_generated_key: Mapped[str | None] = mapped_column(String(220), nullable=True)
    adaptive_last_generated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    unit_unlock_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    unit_unlock_up_to: Mapped[str | None] = mapped_column(String(100), nullable=True)
    discovered_nuances: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string for discovered nuance badges
    login_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_activity_date: Mapped[str | None] = mapped_column(String(10), nullable=True)  # YYYY-MM-DD
    total_xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    student: Mapped[Student] = relationship(back_populates="state")


class StudentBoardCell(Base):
    __tablename__ = "student_board_cells"

    cell_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    unit_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    cell_index: Mapped[int] = mapped_column(Integer, nullable=False)
    problem_id: Mapped[int] = mapped_column(Integer, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    hint_used: Mapped[int] = mapped_column(Integer, default=0)
    cell_type: Mapped[str] = mapped_column(String(20), nullable=False)  # correct/wrong/hint/bonus
    ai_event_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    g_earned: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class UnitMastery(Base):
    __tablename__ = "unit_mastery"

    student_id: Mapped[int] = mapped_column(ForeignKey("students.student_id"), primary_key=True)
    unit_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    mastery_score: Mapped[float] = mapped_column(Float, default=0.0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)
    hint_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_elapsed_sec: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LearningLog(Base):
    __tablename__ = "learning_log"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.student_id"), index=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.problem_id"), index=True)
    answer_payload: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    elapsed_sec: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    hint_used: Mapped[int] = mapped_column(Integer, default=0)
    route_decision: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_pattern: Mapped[str | None] = mapped_column(String(50), nullable=True)
    intervention_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    canvas_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    misconception_tag: Mapped[str | None] = mapped_column(String(120), nullable=True)
    misconception_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    student: Mapped[Student] = relationship(back_populates="logs")
    problem: Mapped[Problem] = relationship()


class ConversationLog(Base):
    __tablename__ = "conversation_log"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(40), nullable=False, default="ai_feedback")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intervention_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    problem_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class TeacherAnnotation(Base):
    __tablename__ = "teacher_annotation"

    annotation_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(Integer, index=True)
    teacher_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diagnostic_correction: Mapped[str] = mapped_column(String(50), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    expires_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class TestSession(Base):
    __tablename__ = "test_sessions"

    session_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.student_id"), index=True)
    unit_id: Mapped[str] = mapped_column(String(100))
    full_unit_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    test_scope: Mapped[str] = mapped_column(String(30))  # 'mini_test' or 'unit_test'
    status: Mapped[str] = mapped_column(String(20), default="in_progress")  # 'in_progress', 'completed', 'abandoned'
    problem_ids: Mapped[str] = mapped_column(Text)  # JSON list of problem IDs
    answers: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of answer records
    score_correct: Mapped[int] = mapped_column(Integer, default=0)
    score_total: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    time_limit_sec: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    time_spent_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_expired: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deferred_problem_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON list, "あとで解く" の順
    defer_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Teacher(Base):
    __tablename__ = "teachers"

    teacher_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    classroom_id: Mapped[int | None] = mapped_column(ForeignKey("classrooms.classroom_id"), nullable=True, index=True)
    login_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Owner(Base):
    __tablename__ = "owners"

    owner_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    login_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class ProblemReview(Base):
    """忘却曲線に基づく問題ごとの復習スケジュール（SM-2アルゴリズム）。

    - repetitions: これまでの連続正解回数
    - interval: 次の復習までの日数
    - ease_factor: 難易度係数（初期 2.5、最小 1.3）
    - next_review_date: 次回復習予定日（YYYY-MM-DD 形式）
    """
    __tablename__ = "problem_review"

    student_id: Mapped[int] = mapped_column(ForeignKey("students.student_id"), primary_key=True, index=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.problem_id"), primary_key=True, index=True)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    interval: Mapped[int] = mapped_column(Integer, default=1)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    next_review_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Feedback(Base):
    __tablename__ = "feedbacks"

    feedback_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(20), nullable=False)  # 'bug' | 'improvement' | 'other'
    message: Mapped[str] = mapped_column(Text, nullable=False)
    page_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Flashcard(Base):
    """英単語マスターデータ。"""
    __tablename__ = "flashcards"

    flashcard_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    english: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    japanese: Mapped[str] = mapped_column(String(200), nullable=False)
    part_of_speech: Mapped[str | None] = mapped_column(String(20), nullable=True)  # noun/verb/adj/adv/prep/conj
    phonetics: Mapped[str | None] = mapped_column(String(100), nullable=True)       # /dɒg/ など
    example_en: Mapped[str | None] = mapped_column(Text, nullable=True)             # 例文（英）
    example_ja: Mapped[str | None] = mapped_column(Text, nullable=True)             # 例文（日）
    grade: Mapped[int] = mapped_column(Integer, default=7, index=True)              # 7=中1, 8=中2, 9=中3
    unit_id: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)  # FK相当（unit_dependency）


class FlashcardProgress(Base):
    """生徒ごとの単語習得ステージ＆SM-2スケジュール。

    stage_cleared: 0=未学習, 1=インプット済, 2=認識クリア, 3=定着クリア, 4=実践クリア（SM-2対象）
    """
    __tablename__ = "flashcard_progress"

    student_id: Mapped[int] = mapped_column(ForeignKey("students.student_id"), primary_key=True, index=True)
    flashcard_id: Mapped[int] = mapped_column(ForeignKey("flashcards.flashcard_id"), primary_key=True, index=True)
    stage_cleared: Mapped[int] = mapped_column(Integer, default=0)  # 0-4
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    interval: Mapped[int] = mapped_column(Integer, default=1)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    next_review_date: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)  # YYYY-MM-DD
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ListeningProblem(Base):
    __tablename__ = "listening_problems"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    subject: Mapped[str] = mapped_column(String(40), default="english")
    skill: Mapped[str] = mapped_column(String(40), default="listening")
    grade_band: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    full_unit_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    unit_id: Mapped[str] = mapped_column(String(120), nullable=False)
    problem_type: Mapped[str] = mapped_column(String(30), default="practice")
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    listening_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    listening_focus: Mapped[str | None] = mapped_column(String(40), nullable=True)
    audio_url: Mapped[str] = mapped_column(String(500), nullable=False)
    audio_script: Mapped[str] = mapped_column(Text, nullable=False)
    audio_speed: Mapped[str] = mapped_column(String(20), default="normal")
    play_limit: Mapped[int] = mapped_column(Integer, default=2)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    choices: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    correct_answer: Mapped[str] = mapped_column(String(500), nullable=False)
    hint_1: Mapped[str | None] = mapped_column(Text, nullable=True)
    hint_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_base: Mapped[str] = mapped_column(Text, nullable=False)
    script_keyword: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_pattern_candidates: Mapped[str | None] = mapped_column(Text, nullable=True)
    intervention_candidates: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class ListeningLog(Base):
    __tablename__ = "listening_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    classroom_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    problem_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    is_correct: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_answer: Mapped[str] = mapped_column(String(500), nullable=False)
    play_count: Mapped[int] = mapped_column(Integer, default=1)
    elapsed_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hint_used: Mapped[int] = mapped_column(Integer, default=0)
    error_pattern: Mapped[str | None] = mapped_column(String(80), nullable=True)
    intervention_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    route: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class ListeningMastery(Base):
    __tablename__ = "listening_mastery"
    __table_args__ = (UniqueConstraint("student_id", "full_unit_id", name="uq_listening_mastery_student_unit"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    classroom_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    full_unit_id: Mapped[str] = mapped_column(String(120), nullable=False)
    mastery_score: Mapped[float] = mapped_column(Float, default=0.0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)
    hint_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_play_count: Mapped[float] = mapped_column(Float, default=1.0)
    avg_elapsed_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
