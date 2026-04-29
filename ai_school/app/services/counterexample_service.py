"""
反例爆弾システム（Counterexample Bomb）

誤概念タグをもとに、「生徒の誤ったルールが通用しない反例問題」と
「ソクラテス式誘導質問」を生成する。

生徒は自分の思考ルールが崩れる体験をすることで、正しい概念を自ら発見する。
"""

from __future__ import annotations

import json
import logging

from ..services.ai_service import generate_text

logger = logging.getLogger(__name__)

_SOCRATIC_CACHE: dict[str, list[dict]] = {}


def generate_socratic_questions(
    question_text: str,
    correct_answer: str,
    student_answer: str,
    misconception_tag: str | None,
    misconception_detail: str | None,
    subject: str = "math",
) -> list[dict]:
    """
    ソクラテス式誘導質問を3問生成する。

    生徒が自分で間違いに気づけるよう設計された問いかけ。
    答えを直接教えない。

    Returns:
        [{"q": "質問文", "type": "open|choice", "choices": [...] or None}, ...]
    """
    cache_key = f"{misconception_tag}|{question_text[:60]}|{student_answer}"
    if cache_key in _SOCRATIC_CACHE:
        return _SOCRATIC_CACHE[cache_key]

    subject_label = "数学" if subject == "math" else "英語"
    misconception_context = ""
    if misconception_detail:
        misconception_context = f"\n推定誤概念: {misconception_detail}"

    system_prompt = f"""あなたは{subject_label}の優れた塾講師です。
生徒が問題を間違えました。答えを直接教えずに、
ソクラテス式の問いかけで生徒が自分で間違いに気づけるよう誘導してください。

以下のJSON配列のみで返答してください（3問）:
[
  {{"q": "最初の質問（問題を分解する）", "type": "open"}},
  {{"q": "2番目の質問（矛盾を突く）", "type": "choice", "choices": ["選択肢A", "選択肢B", "選択肢C"]}},
  {{"q": "3番目の質問（自己修正を促す）", "type": "open"}}
]

制約:
- 答えを直接言わない
- 生徒の答えを否定せず「なぜそう考えたか」を掘り下げる
- 最後の質問で生徒が「あ、わかった」と言えるような設計
- 各質問は30文字以内"""

    user_prompt = f"""問題: {question_text}
正解: {correct_answer}
生徒の回答: {student_answer}{misconception_context}

この生徒が自分で間違いに気づくための3つの問いかけを作ってください。"""

    raw = generate_text(system_prompt, user_prompt, max_output_tokens=300)
    if not raw:
        return _fallback_questions(subject)

    try:
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start == -1 or end == 0:
            return _fallback_questions(subject)

        questions = json.loads(raw[start:end])
        if not isinstance(questions, list) or len(questions) == 0:
            return _fallback_questions(subject)

        validated = []
        for item in questions[:3]:
            if not isinstance(item, dict) or "q" not in item:
                continue
            validated.append({
                "q": str(item["q"])[:80],
                "type": item.get("type", "open"),
                "choices": item.get("choices") if item.get("type") == "choice" else None,
            })

        if not validated:
            return _fallback_questions(subject)

        _SOCRATIC_CACHE[cache_key] = validated
        return validated

    except (json.JSONDecodeError, ValueError) as e:
        logger.debug("socratic questions parse error: %s", e)
        return _fallback_questions(subject)


def _fallback_questions(subject: str) -> list[dict]:
    """AI生成失敗時のフォールバック質問"""
    if subject == "english":
        return [
            {"q": "どの部分で迷いましたか？", "type": "open", "choices": None},
            {"q": "この単語の意味を確認してみましょう。どんな意味だと思いますか？", "type": "open", "choices": None},
            {"q": "もう一度考えてみると、どう答えますか？", "type": "open", "choices": None},
        ]
    return [
        {"q": "最初にどんな計算をしましたか？", "type": "open", "choices": None},
        {"q": "その計算が正しいか、別の数で確認してみましょう。", "type": "open", "choices": None},
        {"q": "今の考え方で、この問題をもう一度解くとどうなりますか？", "type": "open", "choices": None},
    ]


def generate_counterexample_problem(
    misconception_tag: str,
    misconception_detail: str,
    original_question: str,
    subject: str = "math",
) -> dict | None:
    """
    誤概念タグから「そのルールが通用しない反例問題」を生成する。

    Returns:
        {"question": str, "correct_answer": str, "explanation": str} or None
    """
    subject_label = "数学" if subject == "math" else "英語"

    system_prompt = f"""あなたは{subject_label}教育の専門家です。
生徒の誤概念を「反例」で崩す問題を1問作ってください。

以下のJSON形式のみで返答してください：
{{
  "question": "問題文（元の問題と似ているが誤ったルールが通用しない）",
  "correct_answer": "正解",
  "why_counterexample": "なぜこれが反例になるかの説明（日本語40文字以内）"
}}"""

    user_prompt = f"""誤概念: {misconception_detail}（タグ: {misconception_tag}）
元の問題: {original_question}

この誤概念を持つ生徒が「あれ？自分のやり方では解けない！」と気づける反例問題を作ってください。"""

    raw = generate_text(system_prompt, user_prompt, max_output_tokens=200)
    if not raw:
        return None

    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            return None
        data = json.loads(raw[start:end])
        return {
            "question": str(data.get("question", ""))[:300],
            "correct_answer": str(data.get("correct_answer", ""))[:100],
            "why_counterexample": str(data.get("why_counterexample", ""))[:100],
        }
    except (json.JSONDecodeError, ValueError):
        return None
