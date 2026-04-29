import json

from sqlalchemy.orm import Session

from ..models import ListeningLog, ListeningProblem

_MACHINE_LISTENING_PATTERNS = frozenset(
    {
        "sound_discrimination_error",
        "vocabulary_listening_gap",
        "grammar_listening_gap",
        "meaning_capture_error",
        "info_capture_error",
        "attention_loss",
        "unknown_listening_error",
        "question_misread",
    }
)


def _choices_list(problem: ListeningProblem):
    try:
        raw = json.loads(problem.choices) if problem.choices else []
        return [str(x) for x in raw]
    except (json.JSONDecodeError, TypeError):
        return []


def _phonetically_close(a: str, b: str) -> bool:
    a, b = a.strip().lower(), b.strip().lower()
    if not a or not b:
        return False
    if abs(len(a) - len(b)) > 1:
        return False
    if a == b:
        return True
    if len(a) >= 2 and len(b) >= 2 and a[0] == b[0] and a[-1] == b[-1]:
        return True
    return False


def _parse_listening_error_candidates(raw: str | None) -> list[str]:
    if not raw or not str(raw).strip():
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [str(x) for x in data if x is not None and str(x).strip()]


def _listening_error_from_candidates(problem: ListeningProblem) -> str | None:
    for c in _parse_listening_error_candidates(getattr(problem, "error_pattern_candidates", None)):
        if c in _MACHINE_LISTENING_PATTERNS and c != "unknown_listening_error":
            return c
    return None


def classify_listening_error(
    db: Session,
    student_id: int,
    problem: ListeningProblem,
    selected_answer: str,
    is_correct: bool,
    hint_used: int,
    play_count: int,
    play_limit: int,
) -> str:
    if is_correct:
        return ""

    choices = _choices_list(problem)
    wrong = selected_answer.strip()
    correct = problem.correct_answer.strip()

    if problem.listening_type == "word_discrimination":
        close = any(_phonetically_close(wrong, c) for c in choices if c != correct)
        if close:
            return "sound_discrimination_error"
        return "vocabulary_listening_gap"

    if problem.listening_type == "short_sentence":
        ja_hints = ("動詞", "時制", "過去", "現在")
        uid = (problem.full_unit_id or "").lower()
        if (
            problem.listening_focus in ("grammar",)
            or "grammar" in uid
            or any(x in (problem.question_text or "") for x in ja_hints)
        ):
            return "grammar_listening_gap"
        return "meaning_capture_error"

    if problem.listening_type == "info_capture":
        return "info_capture_error"

    if problem.listening_type == "dialog_comprehension":
        lim = play_limit if play_limit > 0 else 999
        if play_count >= lim:
            return "attention_loss"
        return "meaning_capture_error"

    if problem.listening_type == "dialog_response":
        return "meaning_capture_error"

    return _listening_error_from_candidates(problem) or "unknown_listening_error"


def recent_accuracy_for_student(db: Session, student_id: int, limit: int = 12):
    logs = (
        db.query(ListeningLog)
        .filter(ListeningLog.student_id == student_id)
        .order_by(ListeningLog.id.desc())
        .limit(limit)
        .all()
    )
    if not logs:
        return None
    return sum(1 for x in logs if x.is_correct) / len(logs)


def refine_question_misread(db: Session, student_id: int, base_pattern: str) -> str:
    acc = recent_accuracy_for_student(db, student_id, limit=12)
    if acc is not None and acc < 0.25 and base_pattern not in (
        "sound_discrimination_error",
        "attention_loss",
    ):
        return "question_misread"
    return base_pattern
