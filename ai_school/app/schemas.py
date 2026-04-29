from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator


class StudentStateSummary(BaseModel):
    student_id: int
    display_name: str
    current_user_role: str | None
    current_unit: str | None
    current_full_unit_id: str | None
    current_unit_display_name: str | None
    prerequisite_full_unit_id: str | None
    next_full_unit_id: str | None
    current_position_summary: str | None
    current_level: int
    mastery_score: float
    unit_mastery_summary: list[dict]
    recent_results: list[dict]
    recent_hint_usage: list[int]
    hint_dependency_level: str
    unit_hint_summary: list[dict]
    diagnostic_label: str
    recent_signal_summary: dict
    unit_diagnostic_summary: list[dict]
    speed_profile: str
    fallback_risk_level: str
    recent_error_patterns: list[str]
    dominant_error_pattern: str | None
    unit_error_summary: dict[str, dict[str, int]]
    recent_conversation_turns: list[dict]
    current_intervention: str
    recommended_intervention: str
    recent_interventions: list[str]
    intervention_reason: str
    teacher_intervention_needed: bool
    teacher_override_pending: bool
    teacher_annotation: dict
    weak_points: list[dict]
    next_problem_candidate_ids: list[int]
    recommended_route: str


class SubmissionResult(BaseModel):
    problem_id: int
    is_correct: bool
    correct_answer: str
    explanation: str | None
    next_problem_id: int | None
    next_unit: str | None
    next_difficulty: int | None
    logged_at: datetime



class OCRRequest(BaseModel):
    image_data_url: str


class OCRResponse(BaseModel):
    status: str
    recognized_text: str
    error: str = ""


class StudentCreateRequest(BaseModel):
    student_id: int
    display_name: str
    grade: int
    pin: str | None = None
    classroom_id: int


class TeacherCreateRequest(BaseModel):
    login_id: str
    display_name: str
    password: str | None = None
    classroom_id: int


class UnifiedLoginRequest(BaseModel):
    classroom_code: str
    identifier: str
    role: Literal["student", "teacher"]
    pin: str | None = None
    password: str | None = None

    @model_validator(mode="after")
    def _require_secret_for_role(self):
        if self.role == "teacher":
            if not (self.password and str(self.password).strip()):
                raise ValueError("password required for teacher login")
        return self


class ClassroomCreateRequest(BaseModel):
    classroom_name: str
    login_id: str
    classroom_code: str | None = None
    password: str | None = None
    contact_name: str | None = None
    note: str | None = None
    external_classroom_id: str | None = None
    admin_email: str | None = None
    admin_phone: str | None = None
    plan_name: str | None = None
    max_students: int | None = None
    allowed_subjects: str | None = None
    monthly_price: int | None = None
    yearly_price: int | None = None
    contract_start: str | None = None
    contract_end: str | None = None
    contract_status: str | None = None
    contract_memo: str | None = None


class ClassroomUpdateRequest(BaseModel):
    classroom_name: str | None = None
    login_id: str | None = None
    classroom_code: str | None = None
    contact_name: str | None = None
    note: str | None = None
    external_classroom_id: str | None = None
    admin_email: str | None = None
    admin_phone: str | None = None


class ClassroomContractUpdateRequest(BaseModel):
    plan_name: str | None = None
    max_students: int | None = None
    allowed_subjects: str | None = None
    monthly_price: int | None = None
    yearly_price: int | None = None
    contract_start: str | None = None
    contract_end: str | None = None
    contract_status: str | None = None
    contract_memo: str | None = None


class OptionalPasswordRequest(BaseModel):
    password: str | None = None


class ClassroomPurgeRequest(BaseModel):
    confirm_text: str
    classroom_name: str


class ActivationRequest(BaseModel):
    is_active: bool = True


class SynonymMapRequest(BaseModel):
    """英語の類義語使い分けマップ生成リクエスト"""
    submitted_word: str
    correct_word: str
    hint_key: str | None = None


class SynonymComparisonWord(BaseModel):
    """類義語比較情報"""
    word: str
    nuance: str
    emoji: str
    example: str


class SynonymMapResponse(BaseModel):
    """使い分けマップレスポンス"""
    message: str
    comparison: list[SynonymComparisonWord]
