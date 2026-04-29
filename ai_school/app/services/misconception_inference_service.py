"""
誤概念フィンガープリントエンジン

生徒の不正解から「どんな思考ルールを使っているか」をDeepSeekで推論し、
misconception_tag として記録する。

タグ例:
  neg_product_sign      — 負の数の掛け算で符号を誤って適用
  fraction_add_denom    — 分数の足し算で分母もそのまま足してしまう
  equality_direction    — 等式変形で移項の符号を維持してしまう
  verb_tense_simple     — 英語で単純過去と現在完了を混同
"""

from __future__ import annotations

import json
import logging

from ..services.ai_service import generate_text

logger = logging.getLogger(__name__)

# インメモリキャッシュ: (question_text_hash, answer) → (tag, detail)
_INFERENCE_CACHE: dict[str, tuple[str, str]] = {}


def _cache_key(question_text: str, answer: str, correct_answer: str) -> str:
    import hashlib
    raw = f"{question_text[:80]}|{answer}|{correct_answer}"
    return hashlib.md5(raw.encode()).hexdigest()


def infer_misconception(
    question_text: str,
    answer: str,
    correct_answer: str,
    subject: str = "math",
    hint_text: str | None = None,
    explanation_base: str | None = None,
) -> tuple[str | None, str | None]:
    """
    不正解回答から誤概念タグと詳細説明を推論する。

    Returns:
        (misconception_tag, misconception_detail)
        推論不能な場合は (None, None)
    """
    key = _cache_key(question_text, answer, correct_answer)
    if key in _INFERENCE_CACHE:
        return _INFERENCE_CACHE[key]

    subject_label = "数学" if subject == "math" else "英語"

    system_prompt = f"""あなたは{subject_label}教育の認知科学専門家です。
生徒の回答ミスから「どんな誤った思考ルール（誤概念）を持っているか」を分析してください。

以下のJSON形式のみで返答してください：
{{
  "tag": "snake_case_tag_max_30chars",
  "detail": "生徒がどのような誤った思考ルールを持っているかの説明（日本語50文字以内）",
  "confidence": 0.0〜1.0
}}

タグ命名規則: 概念名_誤り種別（例: neg_multiply_sign, fraction_add_denom, past_tense_base）
confidence が 0.4 未満なら tag と detail を null にしてください。"""

    hint_section = f"\nヒント（問題の正解アプローチ）: {hint_text}" if hint_text else ""
    explanation_section = f"\n解説: {explanation_base}" if explanation_base else ""

    user_prompt = f"""問題: {question_text}
正解: {correct_answer}
生徒の回答: {answer}{hint_section}{explanation_section}

この生徒はどんな誤概念を持っていると推論できますか？"""

    raw = generate_text(system_prompt, user_prompt, max_output_tokens=120)
    if not raw:
        return None, None

    try:
        # JSONブロックを抽出
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            return None, None
        data = json.loads(raw[start:end])
        tag = data.get("tag")
        detail = data.get("detail")
        confidence = float(data.get("confidence", 0.0))

        if confidence < 0.4 or not tag:
            return None, None

        tag = str(tag)[:120]
        detail = str(detail)[:500] if detail else None

        _INFERENCE_CACHE[key] = (tag, detail)
        return tag, detail

    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.debug("misconception inference parse error: %s | raw=%s", e, raw[:200])
        return None, None


def get_confirmed_misconceptions(logs: list) -> list[dict]:
    """
    学習ログリストから「確定誤概念（3回以上同じタグ）」を抽出する。

    Args:
        logs: LearningLog オブジェクトのリスト

    Returns:
        [{"tag": str, "count": int, "detail": str}, ...] 降順
    """
    from collections import Counter
    tag_counter: Counter[str] = Counter()
    tag_details: dict[str, str] = {}

    for log in logs:
        tag = getattr(log, "misconception_tag", None)
        if tag:
            tag_counter[tag] += 1
            if tag not in tag_details:
                detail = getattr(log, "misconception_detail", None)
                if detail:
                    tag_details[tag] = detail

    return [
        {"tag": tag, "count": count, "detail": tag_details.get(tag, "")}
        for tag, count in tag_counter.most_common()
        if count >= 2
    ]
