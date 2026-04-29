"""Adaptive problem generation: math and English are separated."""
import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from ..models import LearningLog, Problem, StudentState, UnitMastery
from .ai_service import DEFAULT_CLAUDE_MODEL, generate_claude_text
from .error_pattern_service import KNOWN_ERROR_PATTERNS
from .intervention_service import KNOWN_INTERVENTION_CANDIDATES
from .prompt_builder import build_adaptive_english_problem_prompts
from .state_service import infer_weak_points
from .unit_map_service import get_unit_map_entry

logger = logging.getLogger(__name__)

# 同一 unit + error_pattern での連続 Claude 呼び出しを抑止（streak==0 のときのみ適用。2問連続 adaptive の2 回目は除外）
ADAPTIVE_GENERATION_COOLDOWN_SEC = 120

# Conditional Sonnet strategy (auxiliary). In-memory cache + TTL only.
ADAPTIVE_STRATEGY_CACHE_TTL_SEC = int(os.getenv("ADAPTIVE_STRATEGY_CACHE_TTL_SEC", "3600"))
CLAUDE_STRATEGY_MODEL = os.getenv("CLAUDE_STRATEGY_MODEL", "claude-sonnet-4-20250514")

STRATEGY_REQUIRED_KEYS = ("difficulty", "problem_type", "step_level", "hint_level", "focus_point")

STRATEGY_SONNET_SYSTEM = (
    "\u3042\u306a\u305f\u306f\u4e2d\u5b66\u6570\u5b66\u30fb\u82f1\u8a9e\u306e\u9069\u5fdc\u5b66\u7fd2\u7528"
    "\u300c\u751f\u6210\u65b9\u91dd\u300d\u3092JSON\u3060\u3051\u3067\u8fd4\u3059\u30a2\u30b7\u30b9\u30bf\u30f3\u30c8\u3067\u3059\u3002\n"
    "\u51fa\u529b\u306f\u6709\u52b9\u306aJSON\u30aa\u30d6\u30b8\u30a7\u30af\u30c81\u3064\u3060\u3051\u3002"
    "\u30de\u30fc\u30af\u30c0\u30a6\u30f3\u3084\u30b3\u30fc\u30c9\u30d5\u30a7\u30f3\u30b9\u7981\u6b62\u3002\n"
    "\u30ad\u30fc\u306f\u6b21\u306e5\u3064\u5fc5\u9808\uff08\u5024\u306f\u3059\u3079\u3066\u6587\u5b57\u5217\u3002"
    "\u77ed\u6587\u306e\u65e5\u672c\u8a9e\u3067\u3088\u3044\uff09:\n"
    "difficulty, problem_type, step_level, hint_level, focus_point\n"
    "\u3053\u308c\u306f\u554f\u984c\u6587\u3067\u306f\u306a\u304f\u3001"
    "\u3042\u3068\u304b\u3089\u5225\u30e2\u30c7\u30eb\u304c\u554f\u984c\u3092\u4f5c\u308b\u3068\u304d\u306e\u65b9\u91dd\u30e1\u30e2\u3067\u3042\u308b\u3002\n"
    "focus_point \u306f1\u6587\u3067\u3001\u4eca\u306e\u751f\u5f92\u306e\u3064\u307e\u305a\u304d\u306b\u5408\u308f\u305b\u305f\u6ce8\u76ee\u70b9\u3092\u66f8\u304f\u3002\n"
)

_strategy_cache: dict[str, tuple[dict[str, Any], datetime]] = {}

STRATEGY_USER_PROMPT_AUX = (
    "\n\n\u3010\u51fa\u984c\u65b9\u91dd\uff08\u88dc\u52a9\u60c5\u5831\u30fb\u4efb\u610f\uff09\u3011\n"
    "\u4ee5\u4e0b\u306f\u5225\u30eb\u30fc\u30c8\u3067\u5f97\u305f\u65b9\u91dd\u30e1\u30e2\u3067\u3059\u3002"
    "**\u65e2\u5b58\u306e\u30eb\u30fc\u30eb\u30fb\u51fa\u529b\u5f62\u5f0f\u30fb\u6587\u4f53\u3092\u6700\u512a\u5148**\u3057\u3001"
    "\u77db\u76fe\u3059\u308b\u5834\u5408\u306f\u3053\u306e\u30d6\u30ed\u30c3\u30af\u3092\u7121\u8996\u3057\u3066\u304b\u307e\u3044\u307e\u305b\u3093\u3002\n"
    "{block}\n"
)


def _weak_points_signature_top3(weak_points: list[dict]) -> str:
    top = weak_points[:3]
    items = sorted(
        (str(wp.get("unit_id", "")), int(wp.get("difficulty") or 0)) for wp in top
    )
    return json.dumps(items, separators=(",", ":"))


def _strategy_cache_key(student_id: int, full_unit_id: str, weak_sig: str) -> str:
    return f"{student_id}|{full_unit_id}|{weak_sig}"


def _validate_strategy(obj: Any) -> dict[str, str] | None:
    if not isinstance(obj, dict):
        return None
    out: dict[str, str] = {}
    for k in STRATEGY_REQUIRED_KEYS:
        v = obj.get(k)
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        out[k] = s
    return out


def _parse_strategy_json(raw: str) -> dict[str, str] | None:
    try:
        clean = re.sub(r"```[a-z]*\n?", "", raw).strip()
        data = json.loads(clean)
    except Exception:
        return None
    return _validate_strategy(data)


def _unit_scope_filter(full_unit_id: str):
    return or_(Problem.full_unit_id == full_unit_id, Problem.unit == full_unit_id)


def _should_use_strategy_path(
    db: Session,
    student_id: int,
    full_unit_id: str,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    recent_logs = db.scalars(
        select(LearningLog)
        .join(Problem, LearningLog.problem_id == Problem.problem_id)
        .where(LearningLog.student_id == student_id, Problem.problem_type == "practice")
        .order_by(desc(LearningLog.created_at))
        .limit(3)
    ).all()
    if len(recent_logs) == 3 and all(not r.is_correct for r in recent_logs):
        reasons.append("consecutive_3_wrong")

    wps = infer_weak_points(db, student_id)
    if len(wps) >= 2:
        reasons.append("multiple_weak_points")

    um = db.get(UnitMastery, (student_id, full_unit_id))
    if um is not None:
        tot = um.correct_count + um.wrong_count
        if tot >= 4 and tot > 0 and (um.correct_count / tot) < 0.45:
            reasons.append("low_unit_accuracy")

    recent_unit = db.scalars(
        select(LearningLog)
        .join(Problem, LearningLog.problem_id == Problem.problem_id)
        .where(
            LearningLog.student_id == student_id,
            Problem.problem_type == "practice",
            _unit_scope_filter(full_unit_id),
        )
        .order_by(desc(LearningLog.created_at))
        .limit(12)
    ).all()
    if len(recent_unit) >= 6:
        wrong_n = sum(1 for r in recent_unit if not r.is_correct)
        if wrong_n >= 4:
            reasons.append("strong_unit_stumble")

    return (len(reasons) > 0, reasons)


def _build_strategy_user_prompt_fragment(
    *,
    subject: str,
    full_unit_id: str,
    error_pattern: str,
    pattern_desc_ja: str,
    reasons: list[str],
    weak_sig: str,
) -> str:
    return (
        f"subject: {subject}\n"
        f"full_unit_id: {full_unit_id}\n"
        f"dominant_error_pattern: {error_pattern}\n"
        f"pattern_hint_ja: {pattern_desc_ja}\n"
        f"trigger_reasons: {', '.join(reasons)}\n"
        f"weak_points_top3_signature: {weak_sig}\n"
        "Return only the JSON object."
    )


def _resolve_strategy(
    db: Session,
    student_id: int,
    full_unit_id: str,
    error_pattern: str,
    pattern_desc_ja: str,
    *,
    subject: str,
    reasons: list[str],
) -> tuple[dict[str, str] | None, dict[str, Any]]:
    meta: dict[str, Any] = {
        "strategy_used": False,
        "strategy_cache_hit": False,
        "sonnet_fired": False,
        "strategy_fallback": False,
    }
    wps = infer_weak_points(db, student_id)
    weak_sig = _weak_points_signature_top3(wps)
    key = _strategy_cache_key(student_id, full_unit_id, weak_sig)
    now = datetime.utcnow()

    ent = _strategy_cache.get(key)
    if ent is not None:
        strat_raw, exp = ent
        if exp > now:
            validated = _validate_strategy(strat_raw)
            if validated is not None:
                meta["strategy_used"] = True
                meta["strategy_cache_hit"] = True
                logger.info(
                    "[adaptive_strategy] cache_hit student=%s unit=%s",
                    student_id,
                    full_unit_id,
                )
                return validated, meta
        del _strategy_cache[key]

    meta["sonnet_fired"] = True
    up = _build_strategy_user_prompt_fragment(
        subject=subject,
        full_unit_id=full_unit_id,
        error_pattern=error_pattern,
        pattern_desc_ja=pattern_desc_ja,
        reasons=reasons,
        weak_sig=weak_sig,
    )
    raw = generate_claude_text(
        STRATEGY_SONNET_SYSTEM,
        up,
        max_output_tokens=500,
        model=CLAUDE_STRATEGY_MODEL,
    )
    if not raw:
        meta["strategy_fallback"] = True
        logger.warning(
            "[adaptive_strategy] sonnet_empty_fallback student=%s unit=%s",
            student_id,
            full_unit_id,
        )
        return None, meta

    parsed = _parse_strategy_json(raw)
    if parsed is None:
        meta["strategy_fallback"] = True
        logger.warning(
            "[adaptive_strategy] strategy_invalid_fallback student=%s unit=%s",
            student_id,
            full_unit_id,
        )
        return None, meta

    _strategy_cache[key] = (parsed, now + timedelta(seconds=ADAPTIVE_STRATEGY_CACHE_TTL_SEC))
    meta["strategy_used"] = True
    logger.info(
        "[adaptive_strategy] sonnet_ok_cached student=%s unit=%s ttl_sec=%s",
        student_id,
        full_unit_id,
        ADAPTIVE_STRATEGY_CACHE_TTL_SEC,
    )
    return parsed, meta


def _maybe_attach_strategy(
    db: Session,
    student_id: int | None,
    full_unit_id: str,
    error_pattern: str,
    pattern_desc_ja: str,
    *,
    subject: str,
    user_prompt: str,
) -> str:
    if student_id is None:
        logger.debug("[adaptive_strategy] skip_no_student_id subject=%s unit=%s", subject, full_unit_id)
        return user_prompt
    use_path, reasons = _should_use_strategy_path(db, student_id, full_unit_id)
    if not use_path:
        logger.info(
            "[adaptive_strategy] conditions_false student=%s unit=%s subject=%s",
            student_id,
            full_unit_id,
            subject,
        )
        return user_prompt
    strat, meta = _resolve_strategy(
        db,
        student_id,
        full_unit_id,
        error_pattern,
        pattern_desc_ja,
        subject=subject,
        reasons=reasons,
    )
    logger.info(
        "[adaptive_strategy] trace student=%s unit=%s subject=%s reasons=%s "
        "strategy_used=%s cache_hit=%s sonnet_fired=%s fallback=%s",
        student_id,
        full_unit_id,
        subject,
        reasons,
        meta.get("strategy_used"),
        meta.get("strategy_cache_hit"),
        meta.get("sonnet_fired"),
        meta.get("strategy_fallback"),
    )
    if not strat:
        return user_prompt
    block = json.dumps(strat, ensure_ascii=False, indent=2)
    logger.info(
        "[adaptive_strategy] haiku_with_aux student=%s unit=%s subject=%s",
        student_id,
        full_unit_id,
        subject,
    )
    return user_prompt + STRATEGY_USER_PROMPT_AUX.format(block=block)


def _adaptive_generation_on_cooldown(
    state: StudentState | None, unit_key: str, pattern: str, *, adaptive_streak: int
) -> bool:
    if state is None or adaptive_streak > 0:
        return False
    expected = f"{unit_key}|{pattern}"
    if (state.adaptive_last_generated_key or "") != expected:
        return False
    raw = state.adaptive_last_generated_at
    if not raw:
        return False
    try:
        last = datetime.fromisoformat(raw)
    except ValueError:
        return False
    return (datetime.utcnow() - last).total_seconds() < ADAPTIVE_GENERATION_COOLDOWN_SEC


ERROR_PATTERN_JA: dict[str, str] = {
    "sign_error": "\u7b26\u53f7\uff08\u30d7\u30e9\u30b9\u30fb\u30de\u30a4\u30ca\u30b9\uff09\u3067\u9593\u9055\u3048\u3084\u3059\u3044",
    "arithmetic_error": "\u56db\u5247\u8a08\u7b97\u3067\u30df\u30b9\u3092\u3057\u3084\u3059\u3044",
    "formula_setup_error": "\u5f0f\u3092\u6b63\u3057\u304f\u7acb\u3066\u3089\u308c\u306a\u3044",
    "variable_handling_error": "\u6587\u5b57\uff08x \u306a\u3069\uff09\u306e\u6271\u3044\u3067\u6df7\u4e71\u3057\u3084\u3059\u3044",
    "operation_confusion": "\u305f\u3057\u7b97\u30fb\u304b\u3051\u7b97\u306a\u3069\u6f14\u7b97\u306e\u7a2e\u985e\u3092\u6df7\u540c\u3057\u3084\u3059\u3044",
    "careless_error": "\u30b1\u30a2\u30ec\u30b9\u30df\u30b9\u3092\u3057\u3084\u3059\u3044",
    "comprehension_gap": "\u554f\u984c\u306e\u610f\u5473\u306e\u7406\u89e3\u304c\u4e0d\u5341\u5206",
    "prerequisite_gap": "\u524d\u306e\u5358\u5143\u304c\u4e0d\u8db3\u3057\u3066\u3044\u308b",
    "absolute_value_error": "\u7d76\u5bfe\u5024\u306e\u6271\u3044\u3067\u9593\u9055\u3048\u3084\u3059\u3044",
    "unknown_error": "\u539f\u56e0\u4e0d\u660e\u306e\u30df\u30b9",
}

MATH_SYSTEM_PROMPT = (
    "\u3042\u306a\u305f\u306f\u4e2d\u5b66\u6570\u5b66\u306e\u6559\u6750\u4f5c\u6210\u306e\u5c02\u9580\u5bb6\u3067\u3059\u3002\n"
    "\u4ee5\u4e0b\u306e\u30eb\u30fc\u30eb\u3092\u53b3\u5b88\u3057\u3066\u554f\u984c\u30921\u554f\u751f\u6210\u3057\u3066\u304f\u3060\u3055\u3044\u3002\n\n"
    "1. \u51fa\u529b\u306f JSON \u306e\u307f\u3002\u8aac\u660e\u6587\u30fb\u30de\u30fc\u30af\u30c0\u30a6\u30f3\u30b3\u30fc\u30c9\u30d6\u30ed\u30c3\u30af\u4e0d\u8981\u3002\n"
    "2. hint_1: correct_answer \u306e\u5024\u3092\u305d\u306e\u307e\u307e\u542b\u3081\u3066\u306f\u306a\u3089\u306a\u3044\u3002\u6570\u5b66\u7684\u7528\u8a9e\u3092\u4f7f\u3046\u3002\n"
    "3. hint_2: \u9014\u4e2d\u5f0f\u306e\u307f\u3002correct_answer \u3092\u305d\u306e\u307e\u307e\u542b\u3081\u3066\u306f\u306a\u3089\u306a\u3044\u3002\n"
    "4. error_pattern_candidates \u3068 intervention_candidates \u306f\u6307\u5b9a\u30ea\u30b9\u30c8\u306e\u5024\u306e\u307f\u4f7f\u3046\u3002\n"
    '5. \u5fc5\u305a {"problems": [...]} \u5f62\u5f0f\u3067\u51fa\u529b\u3059\u308b\u3002\n'
    "6. \u96e3\u6613\u5ea6\u304c easy\uff08\u6570\u50241\uff09\u306e\u3068\u304d\u306f1\u30b9\u30c6\u30c3\u30d7\u3067\u89e3\u3051\u308b\u6700\u5c0f\u306e\u554f\u984c\u306b\u3057\u3001\u554f\u984c\u6587\u306f\u77ed\u304f\u3059\u308b\u3002\n"
)


def _get_next_problem_id(db: Session) -> int:
    current_max = db.scalar(select(func.max(Problem.problem_id)))
    return (current_max or 0) + 1


def _adjusted_difficulty(
    db: Session,
    student_id: int,
    current_problem: Problem,
    dominant_error_pattern: str,
) -> int:
    recent_logs = db.scalars(
        select(LearningLog)
        .join(Problem, LearningLog.problem_id == Problem.problem_id)
        .where(LearningLog.student_id == student_id, Problem.problem_type == "practice")
        .order_by(desc(LearningLog.created_at))
        .limit(3)
    ).all()
    consecutive_wrong = len(recent_logs) == 3 and all(not r.is_correct for r in recent_logs)

    adjusted = int(current_problem.difficulty)
    if consecutive_wrong:
        adjusted = max(1, adjusted - 1)
    if dominant_error_pattern == "prerequisite_gap":
        adjusted = 1
    return adjusted


def generate_adaptive_math_problem(
    db: Session,
    unit_id: str,
    full_unit_id: str,
    sub_unit: str | None,
    difficulty: int,
    error_pattern: str,
    student_id: int | None = None,
) -> Problem | None:
    map_entry = get_unit_map_entry(full_unit_id)
    grade = map_entry.get("grade", 7) if map_entry else 7

    diff_label = {1: "easy", 2: "normal", 3: "hard"}.get(difficulty, "easy")
    pattern_desc = ERROR_PATTERN_JA.get(error_pattern, error_pattern)

    valid_errors = list(KNOWN_ERROR_PATTERNS)
    valid_interventions = list(KNOWN_INTERVENTION_CANDIDATES)

    user_prompt = f"""\
\u5358\u5143: {full_unit_id}
\u96e3\u6613\u5ea6: {diff_label}
\u3053\u306e\u751f\u5f92\u304c\u7279\u306b\u9593\u9055\u3048\u3084\u3059\u3044\u30d1\u30bf\u30fc\u30f3: \u300c{pattern_desc}\u300d\uff08error_pattern: {error_pattern}\uff09

\u3010\u5404\u30d5\u30a3\u30fc\u30eb\u30c9\u3011
- full_unit_id: "{full_unit_id}"
- unit_id: "{unit_id}"
- sub_unit: {json.dumps(sub_unit, ensure_ascii=False)}
- problem_type: "practice"
- difficulty: "{diff_label}"
- question_text, correct_answer, hint_1, hint_2, explanation_base
- error_pattern_candidates\uff08{error_pattern} \u3092\u5fc5\u305a\u542b\u3081\u308b\u3053\u3068\uff09: {valid_errors}
- intervention_candidates: {valid_interventions}

\u4e0a\u8a18\u306e\u30df\u30b9\u30d1\u30bf\u30fc\u30f3\u3067\u9593\u9055\u3048\u3084\u3059\u3044\u554f\u984c\u30921\u554f\u751f\u6210\u3057\u3001{{"problems": [...]}} \u3067\u51fa\u529b\u3057\u3066\u304f\u3060\u3055\u3044\u3002
"""

    user_prompt = _maybe_attach_strategy(
        db,
        student_id,
        full_unit_id,
        error_pattern,
        pattern_desc,
        subject="math",
        user_prompt=user_prompt,
    )

    logger.info("[adaptive_math] ai_call full_unit=%s pattern=%s", full_unit_id, error_pattern)
    raw = generate_claude_text(
        MATH_SYSTEM_PROMPT, user_prompt, max_output_tokens=800, model=DEFAULT_CLAUDE_MODEL
    )
    if not raw:
        logger.warning("[adaptive_math] ai_empty full_unit=%s", full_unit_id)
        return None

    try:
        clean = re.sub(r"```[a-z]*\n?", "", raw).strip()
        data = json.loads(clean)
        problems: list[dict[str, Any]] = data.get("problems", [])
        if not problems:
            return None
        p = problems[0]
    except Exception:
        logger.exception("[adaptive_math] json_parse_fail full_unit=%s", full_unit_id)
        return None

    question_text = str(p.get("question_text", "")).strip()
    correct_answer = str(p.get("correct_answer", "")).strip()
    hint_1 = str(p.get("hint_1", "")).strip()
    hint_2 = str(p.get("hint_2", "")).strip()
    explanation_base = str(p.get("explanation_base", "")).strip()
    if not all([question_text, correct_answer, hint_1, hint_2, explanation_base]):
        logger.warning("[adaptive_math] validation_fail missing fields")
        return None

    epc = p.get("error_pattern_candidates", [error_pattern])
    if not isinstance(epc, list):
        epc = [error_pattern]
    epc = [e for e in epc if e in KNOWN_ERROR_PATTERNS] or [error_pattern]

    ic = p.get("intervention_candidates", ["retry_with_hint"])
    if not isinstance(ic, list):
        ic = ["retry_with_hint"]
    ic = [i for i in ic if i in KNOWN_INTERVENTION_CANDIDATES] or ["retry_with_hint"]

    new_id = _get_next_problem_id(db)
    problem = Problem(
        problem_id=new_id,
        subject="math",
        grade=grade,
        unit=unit_id,
        full_unit_id=full_unit_id,
        sub_unit=sub_unit,
        problem_type="practice",
        difficulty=difficulty,
        question_text=question_text,
        correct_answer=correct_answer,
        hint_1=hint_1,
        hint_text=hint_1,
        hint_2=hint_2,
        explanation_base=explanation_base,
        error_pattern_candidates=json.dumps(epc, ensure_ascii=False),
        intervention_candidates=json.dumps(ic, ensure_ascii=False),
        status="approved",
        answer_type="numeric",
    )
    try:
        db.add(problem)
        db.commit()
        db.refresh(problem)
        logger.info("[adaptive_math] saved problem_id=%s", new_id)
        return problem
    except Exception:
        logger.exception("[adaptive_math] db_fail")
        db.rollback()
        return None


def generate_adaptive_english_problem(
    db: Session,
    unit_id: str,
    full_unit_id: str,
    sub_unit: str | None,
    grade: int,
    error_pattern: str,
    student_id: int | None = None,
) -> Problem | None:
    if error_pattern not in KNOWN_ERROR_PATTERNS:
        logger.warning("[adaptive_english] bad_pattern %s", error_pattern)
        return None

    pattern_desc = ERROR_PATTERN_JA.get(error_pattern, error_pattern)
    valid_errors = list(KNOWN_ERROR_PATTERNS)
    valid_interventions = list(KNOWN_INTERVENTION_CANDIDATES)

    system_prompt, user_prompt = build_adaptive_english_problem_prompts(
        full_unit_id=full_unit_id,
        unit_id=unit_id,
        sub_unit=sub_unit,
        diff_label="easy",
        error_pattern=error_pattern,
        pattern_desc_ja=pattern_desc,
        grade=grade,
        valid_errors=valid_errors,
        valid_interventions=valid_interventions,
    )

    user_prompt = _maybe_attach_strategy(
        db,
        student_id,
        full_unit_id,
        error_pattern,
        pattern_desc,
        subject="english",
        user_prompt=user_prompt,
    )

    logger.info(
        "[adaptive_english] ai_call unit=%s full=%s pattern=%s grade=%s",
        unit_id,
        full_unit_id,
        error_pattern,
        grade,
    )
    raw = generate_claude_text(
        system_prompt, user_prompt, max_output_tokens=1200, model=DEFAULT_CLAUDE_MODEL
    )
    if not raw:
        logger.warning("[adaptive_english] ai_empty unit=%s", full_unit_id)
        return None

    try:
        clean = re.sub(r"```[a-z]*\n?", "", raw).strip()
        data = json.loads(clean)
        problems: list[dict[str, Any]] = data.get("problems", [])
        if not problems:
            logger.warning("[adaptive_english] no_problems_array unit=%s", full_unit_id)
            return None
        p = problems[0]
    except Exception:
        logger.exception("[adaptive_english] json_parse_fail unit=%s", full_unit_id)
        return None

    question_text = str(p.get("question_text", "")).strip()
    choices_raw = p.get("choices", [])
    if not isinstance(choices_raw, list):
        logger.warning("[adaptive_english] choices_not_list")
        return None
    choices = [str(c).strip() for c in choices_raw if str(c).strip()]
    if len(choices) != 4:
        logger.warning("[adaptive_english] choices_len=%s (need 4)", len(choices))
        return None
    if len(set(c.lower() for c in choices)) != 4:
        logger.warning("[adaptive_english] duplicate_choices")
        return None

    correct_answer = str(p.get("correct_answer", "")).strip()
    canon: str | None = None
    for c in choices:
        if c.lower() == correct_answer.lower():
            canon = c
            break
    if canon is None:
        logger.warning("[adaptive_english] correct_not_in_choices")
        return None
    correct_answer = canon

    hint_1 = str(p.get("hint_1", "")).strip()
    hint_2 = str(p.get("hint_2", "")).strip()
    explanation_base = str(p.get("explanation_base", "")).strip()
    if not all([question_text, hint_1, hint_2, explanation_base]):
        logger.warning("[adaptive_english] missing_text_fields")
        return None

    epc = p.get("error_pattern_candidates", [error_pattern])
    if not isinstance(epc, list):
        epc = [error_pattern]
    epc = [e for e in epc if e in KNOWN_ERROR_PATTERNS] or [error_pattern]

    ic = p.get("intervention_candidates", ["retry_with_hint"])
    if not isinstance(ic, list):
        ic = ["retry_with_hint"]
    ic = [i for i in ic if i in KNOWN_INTERVENTION_CANDIDATES] or ["retry_with_hint"]

    new_id = _get_next_problem_id(db)
    problem = Problem(
        problem_id=new_id,
        subject="english",
        grade=int(grade),
        unit=unit_id,
        full_unit_id=full_unit_id,
        sub_unit=sub_unit,
        problem_type="practice",
        difficulty=1,
        question_text=question_text,
        correct_answer=correct_answer,
        choices=json.dumps(choices, ensure_ascii=False),
        hint_1=hint_1,
        hint_text=hint_1,
        hint_2=hint_2,
        explanation_base=explanation_base,
        error_pattern_candidates=json.dumps(epc, ensure_ascii=False),
        intervention_candidates=json.dumps(ic, ensure_ascii=False),
        status="approved",
        answer_type="choice",
    )
    try:
        db.add(problem)
        db.commit()
        db.refresh(problem)
        logger.info("[adaptive_english] saved problem_id=%s unit=%s", new_id, full_unit_id)
        return problem
    except Exception:
        logger.exception("[adaptive_english] db_fail unit=%s", full_unit_id)
        db.rollback()
        return None


def get_adaptive_next_math_problem(
    db: Session,
    student_id: int,
    current_problem: Problem,
    dominant_error_pattern: str,
) -> Problem | None:
    if current_problem.subject != "math":
        logger.warning(
            "[adaptive_math] blocked_wrong_subject student=%s subject=%s",
            student_id,
            current_problem.subject,
        )
        return None
    if dominant_error_pattern not in KNOWN_ERROR_PATTERNS:
        return None
    adjusted = _adjusted_difficulty(db, student_id, current_problem, dominant_error_pattern)
    return generate_adaptive_math_problem(
        db=db,
        unit_id=current_problem.unit,
        full_unit_id=current_problem.full_unit_id or current_problem.unit,
        sub_unit=current_problem.sub_unit,
        difficulty=adjusted,
        error_pattern=dominant_error_pattern,
        student_id=student_id,
    )


def get_adaptive_next_english_problem(
    db: Session,
    student_id: int,
    current_problem: Problem,
    dominant_error_pattern: str,
) -> Problem | None:
    if current_problem.subject != "english":
        logger.warning(
            "[adaptive_english] blocked_wrong_subject student=%s subject=%s",
            student_id,
            current_problem.subject,
        )
        return None
    if dominant_error_pattern not in KNOWN_ERROR_PATTERNS:
        return None
    return generate_adaptive_english_problem(
        db=db,
        unit_id=current_problem.unit,
        full_unit_id=current_problem.full_unit_id or current_problem.unit,
        sub_unit=current_problem.sub_unit,
        grade=int(current_problem.grade or 7),
        error_pattern=dominant_error_pattern,
        student_id=student_id,
    )


def generate_adaptive_problem_for_subject(
    db: Session,
    student_id: int,
    current_problem: Problem,
    dominant_error_pattern: str,
    *,
    state: StudentState | None = None,
    adaptive_streak: int = 0,
) -> Problem | None:
    unit_key = current_problem.full_unit_id or current_problem.unit
    if _adaptive_generation_on_cooldown(state, unit_key, dominant_error_pattern, adaptive_streak=adaptive_streak):
        logger.info(
            "[adaptive] cooldown_skip student=%s unit=%s pattern=%s",
            student_id,
            unit_key,
            dominant_error_pattern,
        )
        return None
    subj = (current_problem.subject or "").strip().lower()
    if subj == "math":
        return get_adaptive_next_math_problem(db, student_id, current_problem, dominant_error_pattern)
    if subj == "english":
        return get_adaptive_next_english_problem(db, student_id, current_problem, dominant_error_pattern)
    logger.info(
        "[adaptive] skip_unknown_subject student=%s subject=%r (no AI adaptive)",
        student_id,
        current_problem.subject,
    )
    return None


def generate_adaptive_problem(
    db: Session,
    unit_id: str,
    full_unit_id: str,
    sub_unit: str | None,
    difficulty: int,
    error_pattern: str,
) -> Problem | None:
    return generate_adaptive_math_problem(db, unit_id, full_unit_id, sub_unit, difficulty, error_pattern)


def get_adaptive_next_problem(
    db: Session,
    student_id: int,
    current_problem: Problem,
    dominant_error_pattern: str,
) -> Problem | None:
    return get_adaptive_next_math_problem(db, student_id, current_problem, dominant_error_pattern)
