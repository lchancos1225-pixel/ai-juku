from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..models import ConversationLog
from .ai_service import ai_conversation_enabled, generate_claude_text
from .prompt_builder import build_teacher_summary_prompt


def _label_map(context: dict) -> dict[str, str]:
    return {
        unit["unit_id"]: unit.get("display_name", unit["unit_id"])
        for unit in context.get("unit_mastery_summary", [])
    }


_ERROR_PATTERN_FALLBACK_JA: dict[str, str] = {
    "sign_error": "符号（プラス・マイナス）の間違い",
    "arithmetic_error": "四則計算のミス",
    "absolute_value_error": "絶対値の扱いの間違い",
    "operation_confusion": "演算の種類の混同",
    "careless_error": "ケアレスミス",
    "variable_handling_error": "文字（x など）の扱いの混乱",
    "formula_setup_error": "式の立て方の誤り",
    "comprehension_gap": "問題文の読み取り不足",
    "prerequisite_gap": "前提単元の知識の穴",
    "unknown_error": "原因不明のミス",
}

_ROUTE_FALLBACK_JA: dict[str, str] = {
    "advance_next_unit": "次の単元へ進む段階",
    "fallback_prerequisite_unit": "前の単元に戻って補強が必要な状態",
    "reinforce_current_unit": "現在の単元で継続練習が必要な状態",
}


def _fallback_teacher_summary(context: dict) -> str:
    labels = _label_map(context)
    current_unit = context.get("current_unit")
    current_unit_label = (
        context.get("current_unit_display_name")
        or labels.get(current_unit)
        or current_unit
        or "未設定"
    )
    recent_results = context.get("recent_results", [])
    weak_points = context.get("weak_points", [])
    route = context.get("recommended_route", "reinforce_current_unit")
    recent_wrong = sum(1 for item in recent_results[:3] if not item.get("is_correct"))
    route_label = _ROUTE_FALLBACK_JA.get(route, "現在の単元で継続練習が必要な状態")

    sentences = [
        f"現在は「{current_unit_label}」を学習中で、直近3問では{recent_wrong}問の誤答があります。",
        f"学習状況は「{route_label}」と判断されています。",
    ]

    dominant_error = context.get("dominant_error_pattern")
    if dominant_error:
        error_label = _ERROR_PATTERN_FALLBACK_JA.get(dominant_error, dominant_error)
        sentences.append(f"繰り返し見られる誤りの傾向は「{error_label}」です。")

    if context.get("diagnostic_label") == "prerequisite_gap":
        sentences.append(
            "前提単元の知識の穴が原因候補として挙げられます。"
            "「計算はできる？」と一問口頭で確認すると原因が絞れる可能性があります。"
        )
    elif context.get("diagnostic_label") == "slow_but_correct":
        sentences.append(
            "正解には届いていますが、解くのに時間がかかっています。"
            "手順の確認というより、処理の自動化が課題かもしれません。"
        )
    elif context.get("diagnostic_label") == "hint_dependent":
        sentences.append(
            "ヒントがあれば解けますが、自力での最初の一手が出にくい状態です。"
            "「まず何が分かっているか書いてみて」と声をかけると効果的です。"
        )
    elif context.get("diagnostic_label") == "unstable_understanding":
        sentences.append(
            "正解と誤答が交互に出て、理解が安定していません。"
            "同じ型の問題を繰り返して定着を確認することを推奨します。"
        )

    if context.get("hint_dependency_level") in {"medium", "high"} and context.get("diagnostic_label") != "hint_dependent":
        sentences.append("ヒントへの依存も見られるため、自力で最初の一歩を出せるか確認してみてください。")

    if weak_points:
        weak = weak_points[0]
        wp_label = labels.get(weak.get("unit_id")) or weak.get("unit_id") or ""
        diff_label = {1: "易しい問題", 2: "標準問題", 3: "難しい問題"}.get(weak.get("difficulty"), "")
        if wp_label:
            sentences.append(f"「{wp_label}」の{diff_label}で不安定さが見られる可能性があります。")

    if context.get("teacher_intervention_needed"):
        sentences.append("AIの補助だけでは限界がある可能性があり、先生による直接的な声かけが推奨されます。")
    else:
        sentences.append("計算手順と問題文の読み取りのどちらで止まっているか、短く口頭確認してみてください。")

    return " ".join(sentences[:3])


def _generate_or_fallback(system_prompt: str, user_prompt: str, fallback_text: str, max_output_tokens: int) -> tuple[str, str]:
    generated = generate_claude_text(system_prompt, user_prompt, max_output_tokens=max_output_tokens, model="claude-haiku-4-5")
    if generated:
        return generated, "AI: Claude"
    if ai_conversation_enabled():
        return fallback_text, "ローカルフォールバック"
    return fallback_text, "AI未接続"


def get_recent_turns(db: Session, student_id: int, n: int = 6) -> list[dict]:
    limit = min(max(0, n), 8)
    stmt = (
        select(ConversationLog)
        .where(ConversationLog.student_id == student_id)
        .order_by(desc(ConversationLog.created_at))
        .limit(limit)
    )
    rows = list(reversed(db.scalars(stmt).all()))
    return [{"role": row.role, "content": row.content, "entry_type": row.entry_type} for row in rows]


def generate_teacher_summary(context: dict) -> tuple[str, str]:
    system_prompt, user_prompt = build_teacher_summary_prompt(context)
    fallback = _fallback_teacher_summary(context)
    return _generate_or_fallback(system_prompt, user_prompt, fallback, max_output_tokens=260)
