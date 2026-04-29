import json

_ERROR_PATTERN_JA: dict[str, str] = {
    "sign_error": "符号（プラス・マイナス）の間違い",
    "arithmetic_error": "四則計算のミス",
    "absolute_value_error": "絶対値の扱いの間違い",
    "operation_confusion": "演算の種類の混同（たし算・かけ算など）",
    "careless_error": "ケアレスミス",
    "variable_handling_error": "文字（x など）の扱いの混乱",
    "formula_setup_error": "式の立て方の誤り",
    "comprehension_gap": "問題文の読み取り不足",
    "prerequisite_gap": "前提単元の知識の穴",
    "unknown_error": "原因不明のミス",
}

_ROUTE_JA: dict[str, str] = {
    "advance_next_unit": "次の単元へ進む段階",
    "fallback_prerequisite_unit": "前の単元に戻って補強が必要",
    "reinforce_current_unit": "現在の単元で継続練習",
}

_DIAGNOSTIC_JA: dict[str, str] = {
    "stable_mastery": "安定して習熟している",
    "hint_dependent": "ヒントへの依存が見られる",
    "slow_but_correct": "時間はかかるが正解できている",
    "unstable_understanding": "正誤が安定していない（波がある）",
    "fallback_risk": "連続ミスによる後退リスクあり",
    "prerequisite_gap": "前提単元の理解不足の可能性",
    "in_progress": "学習進行中",
    "not_enough_data": "データ不足でまだ判断できない",
}

_INTERVENTION_JA: dict[str, str] = {
    "advance_with_confidence": "自信を持って次の単元へ進む",
    "fallback_prerequisite": "前の単元に戻って基礎固め",
    "retry_with_hint": "ヒントを使いながら再挑戦",
    "slow_down_and_confirm": "ゆっくり確認しながら進む",
    "explain_differently": "別の説明ルートで理解を促す",
    "reinforce_same_pattern": "同じ種類の問題を繰り返し練習",
    "teacher_intervention_needed": "教師の直接介入が望ましい",
    "monitor_only": "様子見で継続",
}

_HINT_LEVEL_JA: dict[str, str] = {
    "low": "ほとんど使わない",
    "medium": "時々頼っている",
    "high": "頻繁に頼っている",
}


def _translate_context_for_teacher(context: dict) -> str:
    """コンテキストの英語ラベルを日本語に変換し、先生が読みやすい形式の文字列を返す。

    教師要約向け dict は slim_teacher_summary_context で整形すること。生徒名は含めない。
    """
    recent_results = context.get("recent_results", [])
    recent_wrong = sum(1 for r in recent_results[:5] if not r.get("is_correct"))
    recent_correct = sum(1 for r in recent_results[:5] if r.get("is_correct"))

    dominant_error = context.get("dominant_error_pattern")
    recent_errors = context.get("recent_error_patterns", [])

    unit_name_map = {
        um.get("unit_id"): um.get("display_name")
        for um in context.get("unit_mastery_summary", [])
        if um.get("unit_id")
    }

    current_unit_label = (
        context.get("current_unit_display_name")
        or unit_name_map.get(context.get("current_unit"))
        or context.get("current_unit")
        or "未設定"
    )

    lines = [
        f"現在の学習単元: {current_unit_label}",
        f"習熟スコア: {context.get('mastery_score', 0):.2f}（0〜1）",
        f"状態診断: {_DIAGNOSTIC_JA.get(context.get('diagnostic_label', ''), '不明')}",
        f"直近5問の正誤: 正解{recent_correct}問 / 誤答{recent_wrong}問",
        f"ヒント使用傾向: {_HINT_LEVEL_JA.get(context.get('hint_dependency_level', ''), '不明')}",
    ]

    if dominant_error:
        lines.append(f"最も繰り返している誤りの傾向: {_ERROR_PATTERN_JA.get(dominant_error, dominant_error)}")

    if recent_errors:
        error_labels = [_ERROR_PATTERN_JA.get(e, e) for e in recent_errors[:3] if e]
        if error_labels:
            lines.append(f"直近の誤りパターン（上位）: {' / '.join(error_labels)}")

    lines.append(f"推奨ルート: {_ROUTE_JA.get(context.get('recommended_route', ''), '不明')}")
    lines.append(f"推奨介入: {_INTERVENTION_JA.get(context.get('recommended_intervention', ''), '不明')}")

    if context.get("teacher_intervention_needed"):
        lines.append("※ 教師による直接介入が推奨される状態です")

    weak_points = context.get("weak_points", [])
    if weak_points:
        wp = weak_points[0]
        wp_unit = unit_name_map.get(wp.get("unit_id")) or wp.get("unit_id") or ""
        diff_label = {1: "（易しい問題）", 2: "（標準問題）", 3: "（難しい問題）"}.get(wp.get("difficulty"), "")
        lines.append(f"弱点候補単元: {wp_unit}{diff_label}")

    if context.get("intervention_reason"):
        lines.append(f"介入理由: {context['intervention_reason']}")

    return "\n".join(lines)


def build_teacher_summary_prompt(context: dict) -> tuple[str, str]:
    system_prompt = (
        "あなたは学校の先生を支援する学習アシスタントです。\n"
        "以下の生徒情報をもとに、この生徒への「個別指導のための要約」を作成してください。\n\n"
        "【出力ルール】\n"
        "1. 3〜5文でまとめる。英語の技術用語は絶対に使わない。\n"
        "2. 「現状」→「つまずきの候補原因」→「先生への具体的アドバイス」の順で構成する。\n"
        "3. 誤りの傾向が繰り返されている場合は、中学以前（小学校の分数・整数の計算・数直線の読み方など）"
        "の前提知識の欠落も原因候補として挙げてよい。\n"
        "4. 推測は必ず「〜の可能性があります」「〜が候補として考えられます」と表現し、断定しない。\n"
        "5. アドバイスは「先生が1〜2分でできる口頭確認や行動」として具体的に書く。\n"
        "6. 教師介入が推奨されている場合は最後に明記する。\n"
        "7. 出力は日本語の本文のみ。箇条書き・見出し・記号は使わない。\n"
        "8. 出力は150〜250文字程度に収める。"
    )
    translated = _translate_context_for_teacher(context)
    user_prompt = (
        "以下の生徒情報をもとに、先生向け個別指導要約を作成してください。\n"
        "出力は日本語の本文だけにしてください。\n\n"
        f"{translated}"
    )
    return system_prompt, user_prompt


def build_adaptive_english_problem_prompts(
    full_unit_id: str,
    unit_id: str,
    sub_unit: str | None,
    diff_label: str,
    error_pattern: str,
    pattern_desc_ja: str,
    grade: int,
    valid_errors: list[str],
    valid_interventions: list[str],
) -> tuple[str, str]:
    """Build English adaptive remedial MCQ prompts for Claude."""
    err_json = json.dumps(valid_errors, ensure_ascii=False)
    int_json = json.dumps(valid_interventions, ensure_ascii=False)
    sub_s = json.dumps(sub_unit, ensure_ascii=False)
    system_prompt = (
        "You create remedial English questions for Japanese junior high school students (grades 7–9).\n"
        "Output ONLY valid JSON. No markdown fences, no commentary.\n"
        'Shape: {"problems":[{one object}]}\n'
        "The problem object fields:\n"
        "- question_text: short (Japanese or simple English), under ~200 characters.\n"
        "- choices: array of exactly 4 distinct short English strings (word or short phrase each).\n"
        "- correct_answer: MUST be exactly equal to one of the four strings in choices (same spelling and spacing).\n"
        "- hint_1, hint_2: Japanese; do not reveal the correct_answer string verbatim.\n"
        "- explanation_base: Japanese, 2–3 short sentences.\n"
        f"- error_pattern_candidates: JSON array; MUST include \"{error_pattern}\"; "
        f"each value must be one of: {err_json}\n"
        f"- intervention_candidates: JSON array; each value must be one of: {int_json}\n"
        "Rules: ONE focus only (vocabulary, grammar, word order, or basic sentence meaning). "
        "No listening, no long reading, no free composition. "
        f"Keep difficulty easy / remedial; appropriate for school grade {grade}.\n"
    )
    user_prompt = (
        "Generate exactly one remedial multiple-choice English practice question.\n\n"
        f"Context:\n"
        f"- full_unit_id: {full_unit_id}\n"
        f"- unit_id: {unit_id}\n"
        f"- sub_unit: {sub_s}\n"
        f"- difficulty label: {diff_label}\n"
        f"- error_pattern (machine): {error_pattern}\n"
        f"- weakness hint (Japanese): {pattern_desc_ja}\n\n"
        "Match the question to this unit's typical topics (tense, be verb, modals, vocabulary, etc.) when possible.\n"
        'Return JSON only: {"problems":[{...}]}.\n'
    )
    return system_prompt, user_prompt



