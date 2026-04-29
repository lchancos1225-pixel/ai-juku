"""Answer input panel: blanks with input_mode and [[blank:id]] placeholders."""

from __future__ import annotations

import json
import re
from typing import Any

from markupsafe import Markup, escape

from ..models import Problem
from .math_text_service import format_math_for_display

BLANK_PLACEHOLDER_RE = re.compile(r"\[\[blank:([a-zA-Z0-9_]+)\]\]")
MULTI_ANSWER_DELIMITER = "@@@"

_SIMPLE_FRACTION_RE = re.compile(r"^-?\d+/\d+$")
_VALID_INPUT_MODES = frozenset({"numeric", "expression", "fraction"})


def normalize_answer_input_spec_for_storage(raw: str) -> tuple[str | None, str | None]:
    """Validate optional teacher/API JSON and return a string for DB storage.

    Returns (json_for_db, error_message). Whitespace-only raw -> (None, None).
    """
    text = (raw or "").strip()
    if not text:
        return None, None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"解答入力仕様(JSON)が不正です: {e.msg}"
    if not isinstance(data, dict):
        return None, "解答入力仕様はJSONオブジェクトで入力してください"
    blanks = data.get("blanks")
    if blanks is not None:
        if not isinstance(blanks, list):
            return None, "answer_input_spec の blanks は配列である必要があります"
        for i, item in enumerate(blanks):
            if not isinstance(item, dict):
                return None, f"blanks[{i}] はオブジェクトである必要があります"
            mode = str(item.get("input_mode") or item.get("inputMode") or "").strip().lower()
            if mode and mode not in _VALID_INPUT_MODES:
                return None, (
                    f"blanks[{i}].input_mode は numeric / expression / fraction のいずれかにしてください"
                )
    return json.dumps(data, ensure_ascii=False), None


def use_structured_answer_panel(problem: Problem) -> bool:
    if getattr(problem, "subject", None) == "english":
        return False
    return problem.answer_type in ("numeric", "text")


def _parse_spec_json(problem: Problem) -> dict[str, Any] | None:
    raw = getattr(problem, "answer_input_spec", None)
    if not raw or not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def infer_default_input_mode(problem: Problem) -> str:
    """If spec is absent: use fraction when correct_answer is one integer fraction (e.g. 1/2)."""
    if problem.answer_type == "text":
        return "expression"
    if problem.answer_type != "numeric":
        return "numeric"
    ca = (problem.correct_answer or "").strip()
    if not ca:
        return "numeric"
    t = ca.replace("／", "/").replace("（", "(").replace("）", ")")
    t = re.sub(r"[\s\u3000]+", "", t)
    if len(t) >= 2 and t[0] == "(" and t[-1] == ")":
        t = t[1:-1]
    return "fraction" if _SIMPLE_FRACTION_RE.match(t) else "numeric"


_KUHAKU_PREFIX = "\u7a7a\u6b04"


def blank_suffix_after_kuhaku(label: str) -> str | None:
    """Suffix after the default ku-haku prefix on auto labels; None for custom labels."""
    if label.startswith(_KUHAKU_PREFIX) and len(label) > len(_KUHAKU_PREFIX):
        return label[len(_KUHAKU_PREFIX) :]
    return None


def student_empty_slot_paren(question_text: str, label: str, num_blanks: int) -> str:
    qt = question_text or ""
    tok = blank_suffix_after_kuhaku(label)
    if tok and tok in qt:
        return f"\uff08{tok}\uff09"
    if num_blanks == 1:
        return "\uff08\u7b54\u3048\uff09"
    return "\uff08\u5165\u529b\uff09"


def student_slot_aria_label(question_text: str, label: str, num_blanks: int, input_mode: str) -> str:
    qt = question_text or ""
    tok = blank_suffix_after_kuhaku(label)
    if tok and tok in qt:
        return f"{tok}\u3092\u5165\u529b"
    if num_blanks > 1:
        return "\u3053\u306e\u7a7a\u6b04\u3092\u5165\u529b"
    if input_mode == "fraction":
        return "\u5206\u6570\u3067\u5165\u529b"
    if input_mode == "expression":
        return "\u5f0f\u3092\u5165\u529b"
    return "\u6574\u6570\u3067\u5165\u529b"


def _enrich_student_tokens(blanks: list[dict[str, Any]], problem: Problem) -> None:
    qt = problem.question_text or ""
    for b in blanks:
        lb = str(b.get("label") or "")
        tok = blank_suffix_after_kuhaku(lb)
        b["student_token"] = tok
        b["student_token_in_question"] = bool(tok and tok in qt)


def effective_blanks(problem: Problem) -> list[dict[str, Any]]:
    parsed = _parse_spec_json(problem)
    blanks_raw = parsed.get("blanks") if parsed else None
    out: list[dict[str, Any]] = []
    if isinstance(blanks_raw, list):
        for i, item in enumerate(blanks_raw):
            if not isinstance(item, dict):
                continue
            bid = str(item.get("id") or "").strip() or f"b{i + 1}"
            mode = str(item.get("input_mode") or item.get("inputMode") or "").strip().lower()
            if mode not in ("numeric", "expression", "fraction"):
                mode = infer_default_input_mode(problem)
            katakana = chr(0x30A2 + i) if i < 84 else str(i + 1)
            label = str(item.get("label") or "").strip() or ("\u7a7a\u6b04" + katakana)
            hint = str(item.get("input_hint") or "").strip()
            example = str(item.get("input_example") or "").strip()
            out.append(
                {
                    "id": bid,
                    "label": label,
                    "input_mode": mode,
                    "input_hint": hint,
                    "input_example": example,
                }
            )
    if out:
        _enrich_student_tokens(out, problem)
        return out
    default_mode = infer_default_input_mode(problem)
    if default_mode == "numeric":
        hint = (
            "\u6570\u5b57\u306f\u4e0b\u306e\u30dc\u30bf\u30f3\u304b\u3089\u5165\u529b\u3067\u304d\u307e\u3059\u3002"
            "\u30de\u30a4\u30ca\u30b9\u30fb\u5c0f\u6570\u3082\u5bfe\u5fdc\u3057\u3066\u3044\u307e\u3059\u3002"
        )
        example = "\u4f8b: -3.5"
    elif default_mode == "fraction":
        hint = (
            "\u7e26\u5206\u6570\u3067\u5165\u529b\u3057\u307e\u3059\u3002"
            "\u300c\u4e0a\u6bb5\u300d\u300c\u4e0b\u6bb5\u300d\u3067\u5165\u529b\u3059\u308b\u6841\u3092\u5207\u308a\u66ff\u3048\u3089\u308c\u307e\u3059\u3002"
            "\u300c\u5206\u6570\u300d\u3067\u5165\u529b\u3092\u3084\u308a\u76f4\u305b\u307e\u3059\u3002"
        )
        example = "\u4f8b: 1/2 \u2192 \u5206\u5b50 1 \u30fb\u5206\u6bcd 2"
    else:
        hint = (
            "\u6587\u5b57\u5f0f\u30fb\u7d2f\u4e57\u306f\u4e0b\u306e\u30dc\u30bf\u30f3\u304b\u3089\u5165\u529b\u3067\u304d\u307e\u3059\u3002"
            "\u7d2f\u4e57\u306f x^2 \u306e\u5f62\u3067\u8868\u3057\u307e\u3059\u3002"
        )
        example = "\u4f8b: x^2-1"
    single = [
        {
            "id": "a",
            "label": "\u7a7a\u6b04\u30a2",
            "input_mode": default_mode,
            "input_hint": hint,
            "input_example": example,
        }
    ]
    _enrich_student_tokens(single, problem)
    return single


def render_question_with_input_slots(problem: Problem, blanks: list[dict[str, Any]] | None = None) -> Markup:
    blanks = blanks or effective_blanks(problem)
    id_set = {b["id"] for b in blanks}
    qt = problem.question_text or ""

    matches = list(BLANK_PLACEHOLDER_RE.finditer(qt))
    if not matches:
        n = len(blanks)
        row_slots = "".join(
            (
                f'<button type="button" class="answer-blank-slot" data-blank-id="{escape(b["id"])}" '
                f'aria-label="{escape(student_slot_aria_label(qt, str(b.get("label") or b["id"]), n, str(b.get("input_mode") or "numeric")))}">'
                f'<span class="answer-blank-slot__body answer-blank-slot__body--empty">'
                f"{escape(student_empty_slot_paren(qt, str(b.get('label') or b['id']), n))}"
                f"</span></button>"
            )
            for b in blanks
        )
        aria = "\u89e3\u7b54\u7a7a\u6b04"
        return format_math_for_display(qt) + Markup(
            f'<div class="answer-blank-slots-row" role="group" aria-label="{aria}">{row_slots}</div>'
        )

    pieces: list[str] = []
    pos = 0
    for m in matches:
        if m.start() > pos:
            pieces.append(str(format_math_for_display(qt[pos : m.start()])))
        bid = m.group(1)
        if bid not in id_set:
            pieces.append(str(format_math_for_display(m.group(0))))
        else:
            meta = next((b for b in blanks if b["id"] == bid), blanks[0])
            cap = escape(
                student_empty_slot_paren(qt, str(meta.get("label") or bid), len(blanks))
            )
            aria = escape(
                student_slot_aria_label(
                    qt,
                    str(meta.get("label") or bid),
                    len(blanks),
                    str(meta.get("input_mode") or "numeric"),
                )
            )
            pieces.append(
                f'<button type="button" class="answer-blank-slot" data-blank-id="{escape(bid)}" '
                f'aria-label="{aria}">'
                f'<span class="answer-blank-slot__body answer-blank-slot__body--empty">{cap}</span>'
                f"</button>"
            )
        pos = m.end()
    if pos < len(qt):
        pieces.append(str(format_math_for_display(qt[pos:])))
    return Markup("".join(pieces))


def build_answer_panel_template_context(problem: Problem) -> dict[str, Any]:
    if not use_structured_answer_panel(problem):
        return {
            "use_math_answer_panel": False,
            "answer_blanks_json": "[]",
            "question_slots_html": None,
        }
    blanks = effective_blanks(problem)
    return {
        "use_math_answer_panel": True,
        "answer_blanks_json": json.dumps(blanks, ensure_ascii=False),
        "question_slots_html": render_question_with_input_slots(problem, blanks),
    }
