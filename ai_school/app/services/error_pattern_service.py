import json

from .answer_input_spec_service import MULTI_ANSWER_DELIMITER
from .math_text_service import normalize_answer_for_grading
from .signal_service import classify_time_signal


KNOWN_ERROR_PATTERNS = {
    "sign_error",
    "arithmetic_error",
    "absolute_value_error",
    "operation_confusion",
    "careless_error",
    "variable_handling_error",
    "formula_setup_error",
    "comprehension_gap",
    "prerequisite_gap",
    "unknown_error",
}

# full_unit_id → 単元グループのマッピング
_UNIT_GROUP: dict[str, str] = {
    "positive_negative_numbers_addition": "positive_negative",
    "positive_negative_numbers_subtraction": "positive_negative",
    "positive_negative_numbers_multiplication": "positive_negative",
    "positive_negative_numbers_division": "positive_negative",
    "algebraic_expressions_basic": "algebraic_expressions",
    "algebraic_expressions_terms": "algebraic_expressions",
    "algebraic_expressions_substitution": "algebraic_expressions",
    "linear_equations_basic": "linear_equations",
    "linear_equations_transposition": "linear_equations",
    "linear_equations_word_problem": "word_problem",
    "simultaneous_equations_basic": "simultaneous_equations",
    "simultaneous_equations_application": "word_problem",
    "linear_function_basic": "linear_function",
    "linear_function_graph": "linear_function",
    "geometry_parallel_congruence": "geometry",
    "probability_basic": "probability",
    "quadratic_expressions_expansion": "quadratic",
    "factorization_basic": "quadratic",
    "quadratic_equations_basic": "quadratic",
    "quadratic_equations_application": "word_problem",
    "functions_y_equals_ax2": "functions_quadratic",
    "geometry_similarity": "geometry",
    "circles_angles": "geometry",
    "sample_survey_basic": "probability",
}


def _parse_numeric(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(normalize_answer_for_grading(value))
    except (TypeError, ValueError):
        return None


def _has_keyword(text: str, *keywords: str) -> bool:
    return any(kw in text for kw in keywords)


def _parse_error_pattern_candidates_json(raw: str | None) -> list[str]:
    if not raw or not str(raw).strip():
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [str(x) for x in data if x is not None and str(x).strip()]


def _first_known_candidate(candidates: list[str]) -> str | None:
    for c in candidates:
        if c in KNOWN_ERROR_PATTERNS:
            return c
    return None


def _fallback_from_error_pattern_candidates(problem) -> str | None:
    raw = getattr(problem, "error_pattern_candidates", None)
    return _first_known_candidate(_parse_error_pattern_candidates_json(raw))


def _classify_when_numeric_incomplete(
    group: str, hint_used: int, time_signal: str, answer_type: str
) -> str:
    """正解・解答の少なくとも一方が数値化できない場合のフォールバック。"""
    if hint_used >= 2 and time_signal == "long":
        return "comprehension_gap"
    at = (answer_type or "numeric").strip().lower()
    if at in ("choice", "sort"):
        if hint_used >= 1 or time_signal == "long":
            return "comprehension_gap"
        return "formula_setup_error"
    if at == "text":
        if group in (
            "algebraic_expressions",
            "quadratic",
            "linear_equations",
            "simultaneous_equations",
        ):
            return "variable_handling_error"
        return "comprehension_gap"
    if group == "word_problem":
        return "formula_setup_error"
    if group == "geometry" and at == "numeric":
        return "formula_setup_error"
    return "comprehension_gap"


def _apply_careless_override(
    result: str,
    correct_numeric: float | None,
    answer_numeric: float | None,
    hint_used: int,
    time_signal: str,
) -> str:
    if result != "arithmetic_error":
        return result
    if hint_used != 0:
        return result
    if time_signal != "short":
        return result
    if correct_numeric is None or answer_numeric is None:
        return result
    if abs(answer_numeric - correct_numeric) <= 1:
        return "careless_error"
    return result


def _classify_positive_negative(correct_numeric, answer_numeric, hint_used, time_signal, question_text):
    """正��の数グループの詳細分類"""
    if correct_numeric is None or answer_numeric is None:
        return "unknown_error"
    # ��対値は合っている�う
    if abs(answer_numeric) == abs(correct_numeric) and answer_numeric != correct_numeric:
        return "sign_error"
    # 絶対値そのものを答えている（符号なし）
    if answer_numeric == abs(correct_numeric) and correct_numeric < 0:
        return "absolute_value_error"
    # ±1〜2�差
    if abs(answer_numeric - correct_numeric) <= 2:
        return "arithmetic_error"
    # 大きくずれていて時間もかかっている → 演算の種類を混同
    if time_signal == "long" and abs(answer_numeric - correct_numeric) > 5:
        return "operation_confusion"
    return "arithmetic_error"


def _classify_algebraic_expressions(correct_numeric, answer_numeric, hint_used, time_signal, question_text):
    """文字式グループの詳細分類"""
    if hint_used >= 2 and time_signal == "long":
        return "comprehension_gap"
    # 代入問題：数値答えが出るが大きくずれている → 代入手順の��り
    if _has_keyword(question_text, "代入", "x=", "y=", "のとき"):
        if correct_numeric is not None and answer_numeric is not None:
            if abs(answer_numeric - correct_numeric) <= 3:
                return "arithmetic_error"
            return "variable_handling_error"
        return "variable_handling_error"
    # 式の��略化・整理の問題
    if _has_keyword(question_text, "整理", "まとめ", "計算", "項"):
        return "variable_handling_error"
    if correct_numeric is not None and answer_numeric is not None and abs(answer_numeric - correct_numeric) <= 2:
        return "arithmetic_error"
    return "variable_handling_error"


def _classify_linear_equations(correct_numeric, answer_numeric, hint_used, time_signal, question_text):
    """一次方程式グループの詳細分類"""
    if hint_used >= 2 and time_signal == "long":
        return "comprehension_gap"
    # 移項のある問題：符号が反転した値は sign_error
    if _has_keyword(question_text, "移項", "方程式"):
        if correct_numeric is not None and answer_numeric is not None:
            if abs(answer_numeric) == abs(correct_numeric) and answer_numeric != correct_numeric:
                return "sign_error"
            if abs(answer_numeric - correct_numeric) <= 2:
                return "arithmetic_error"
        return "formula_setup_error"
    # 数値がずれている → 式の立て方か計算か
    if correct_numeric is not None and answer_numeric is not None:
        if abs(answer_numeric - correct_numeric) <= 2:
            return "arithmetic_error"
        return "formula_setup_error"
    return "formula_setup_error"


def _classify_simultaneous_equations(correct_numeric, answer_numeric, hint_used, time_signal, question_text):
    """連立方程式グループの詳細分類"""
    if hint_used >= 2 and time_signal == "long":
        return "comprehension_gap"
    if correct_numeric is not None and answer_numeric is not None:
        if abs(answer_numeric) == abs(correct_numeric) and answer_numeric != correct_numeric:
            return "sign_error"
        if abs(answer_numeric - correct_numeric) <= 2:
            return "arithmetic_error"
    # 2変数を��っている問題は変数の混乱が多い
    if _has_keyword(question_text, "x", "y"):
        return "variable_handling_error"
    return "formula_setup_error"


def _classify_word_problem(
    correct_numeric, answer_numeric, hint_used, time_signal, question_text, full_unit_id: str = ""
):
    """文章題グループの詳細分類（方程式系の単元では符号・計算を優先）。"""
    # 時間とヒントが多い → 問題文の読み取り不足
    if hint_used >= 2 or time_signal == "long":
        return "comprehension_gap"
    uid = (full_unit_id or "").lower()
    if "linear_equation" in uid or "simultaneous" in uid or "quadratic_equation" in uid:
        if correct_numeric is not None and answer_numeric is not None:
            if abs(answer_numeric) == abs(correct_numeric) and answer_numeric != correct_numeric:
                return "sign_error"
            if abs(answer_numeric - correct_numeric) <= 2:
                return "arithmetic_error"
        return "formula_setup_error"
    if correct_numeric is not None and answer_numeric is not None:
        if abs(answer_numeric - correct_numeric) <= 2:
            return "arithmetic_error"
    # 式が立てられていない → 式の立て方の��り
    return "formula_setup_error"


def _classify_linear_function(correct_numeric, answer_numeric, hint_used, time_signal, question_text):
    """一次関数グループの詳細分類"""
    if hint_used >= 2 and time_signal == "long":
        return "comprehension_gap"
    # 傾き・切片の読み取り問題
    if _has_keyword(question_text, "�傾き", "切片", "a=", "b="):
        if correct_numeric is not None and answer_numeric is not None:
            if abs(answer_numeric) == abs(correct_numeric) and answer_numeric != correct_numeric:
                return "sign_error"
            if abs(answer_numeric - correct_numeric) <= 2:
                return "arithmetic_error"
        return "formula_setup_error"
    # グラフのx/y座標の読み取り
    if _has_keyword(question_text, "交点", "座標", "グラフ"):
        if correct_numeric is not None and answer_numeric is not None and abs(answer_numeric - correct_numeric) <= 2:
            return "arithmetic_error"
        return "formula_setup_error"
    if correct_numeric is not None and answer_numeric is not None and abs(answer_numeric - correct_numeric) <= 2:
        return "arithmetic_error"
    return "formula_setup_error"


def _classify_quadratic(correct_numeric, answer_numeric, hint_used, time_signal, question_text):
    """二次式・因数分解グループの詳細分類"""
    if hint_used >= 2 and time_signal == "long":
        return "comprehension_gap"
    # 展開・因数分解は符号ミスが多い
    if _has_keyword(question_text, "展開", "因数分解", "(x+", "(x-", "x²", "x^2"):
        if correct_numeric is not None and answer_numeric is not None:
            if abs(answer_numeric) == abs(correct_numeric) and answer_numeric != correct_numeric:
                return "sign_error"
            if abs(answer_numeric - correct_numeric) <= 2:
                return "arithmetic_error"
        return "formula_setup_error"
    # 方程式の解
    if correct_numeric is not None and answer_numeric is not None:
        if abs(answer_numeric) == abs(correct_numeric) and answer_numeric != correct_numeric:
            return "sign_error"
        if abs(answer_numeric - correct_numeric) <= 3:
            return "arithmetic_error"
    return "formula_setup_error"


def _classify_functions_quadratic(correct_numeric, answer_numeric, hint_used, time_signal, question_text):
    """関数 y=ax² グループの詳細分類"""
    if hint_used >= 2 and time_signal == "long":
        return "comprehension_gap"
    # aの値の問題
    if _has_keyword(question_text, "a=", "比例定数", "グラフ"):
        if correct_numeric is not None and answer_numeric is not None:
            if abs(answer_numeric) == abs(correct_numeric) and answer_numeric != correct_numeric:
                return "sign_error"
            return "arithmetic_error"
        return "formula_setup_error"
    # x²の計算ミス（��の数を代入して符号を間��えるなど）
    if _has_keyword(question_text, "代入", "x=", "y="):
        if correct_numeric is not None and answer_numeric is not None:
            if answer_numeric > 0 and correct_numeric < 0:
                return "sign_error"
            if abs(answer_numeric - correct_numeric) <= 3:
                return "arithmetic_error"
        return "variable_handling_error"
    if correct_numeric is not None and answer_numeric is not None and abs(answer_numeric - correct_numeric) <= 3:
        return "arithmetic_error"
    return "formula_setup_error"


def _classify_geometry(correct_numeric, answer_numeric, hint_used, time_signal, question_text):
    """��形グループの詳細分類（平行線・合同�）"""
    if hint_used >= 2 and time_signal == "long":
        return "comprehension_gap"
    # 角度問題：符号はないが計算��りは arithmetic
    if _has_keyword(question_text, "角", "度", "��", "角度"):
        if correct_numeric is not None and answer_numeric is not None:
            if abs(answer_numeric - correct_numeric) <= 5:
                return "arithmetic_error"
            # ��角・対��角の混同（180°- や 360°- のずれ）
            if abs(abs(answer_numeric - correct_numeric) - 180) <= 5:
                return "operation_confusion"
            if abs(abs(answer_numeric - correct_numeric) - 90) <= 5:
                return "operation_confusion"
        return "formula_setup_error"
    # ��の長さ・比
    if _has_keyword(question_text, "長�", "比", "倍", "相似比"):
        if correct_numeric is not None and answer_numeric is not None and abs(answer_numeric - correct_numeric) <= 3:
            return "arithmetic_error"
        return "formula_setup_error"
    # 証明・理由の問題は読み取り不足
    if _has_keyword(question_text, "証明", "理由", "な��", "説明"):
        return "comprehension_gap"
    if correct_numeric is not None and answer_numeric is not None and abs(answer_numeric - correct_numeric) <= 3:
        return "arithmetic_error"
    return "formula_setup_error"


def _classify_probability(correct_numeric, answer_numeric, hint_used, time_signal, question_text):
    """確率・標本調査グループの詳細分類"""
    if hint_used >= 2 and time_signal == "long":
        return "comprehension_gap"
    # 分数答えの問題（確率は 0〜1 の値）
    if correct_numeric is not None and answer_numeric is not None:
        if abs(answer_numeric - correct_numeric) < 0.1:
            return "arithmetic_error"
        # 分母を間��える（例：6通りを8通�える）
        if correct_numeric > 0 and 0 < answer_numeric <= 1:
            return "formula_setup_error"
    # 「何通り」「何種類」→ 場合の数の立て方
    if _has_keyword(question_text, "何通り", "何種�形��", "組み合わせ", "順列"):
        return "formula_setup_error"
    return "comprehension_gap"


def classify_error_pattern(problem, answer: str, route_decision: str, hint_used: int, elapsed_sec: int) -> str | None:
    if answer is None:
        return "unknown_error"

    primary = answer.split(MULTI_ANSWER_DELIMITER, 1)[0] if answer else ""
    normalized_answer = normalize_answer_for_grading(primary)
    if not normalized_answer:
        return "comprehension_gap"

    if route_decision == "fallback_prerequisite_unit":
        return "prerequisite_gap"

    time_signal = classify_time_signal(elapsed_sec)
    correct_numeric = _parse_numeric(getattr(problem, "correct_answer", None))
    answer_numeric = _parse_numeric(normalized_answer)
    question_text = getattr(problem, "question_text", "") or ""
    full_unit_id = getattr(problem, "full_unit_id", None) or ""
    answer_type = getattr(problem, "answer_type", None) or "numeric"

    group = _UNIT_GROUP.get(full_unit_id)
    # full_unit_id がない場合は unit からグループを推定
    if not group:
        unit = getattr(problem, "unit", "") or ""
        if "positive_negative" in unit:
            group = "positive_negative"
        elif "algebraic" in unit:
            group = "algebraic_expressions"
        elif "linear_equation" in unit:
            group = "linear_equations"
        elif "simultaneous" in unit:
            group = "simultaneous_equations"
        elif "linear_function" in unit:
            group = "linear_function"
        elif "quadratic" in unit or "factori" in unit:
            group = "quadratic"
        elif "geometry" in unit or "circle" in unit:
            group = "geometry"
        elif "probability" in unit or "sample" in unit:
            group = "probability"
        else:
            group = "generic"

    numeric_pair_ok = correct_numeric is not None and answer_numeric is not None
    if not numeric_pair_ok:
        result = _classify_when_numeric_incomplete(group, hint_used, time_signal, answer_type)
    elif group == "positive_negative":
        result = _classify_positive_negative(correct_numeric, answer_numeric, hint_used, time_signal, question_text)
    elif group == "algebraic_expressions":
        result = _classify_algebraic_expressions(correct_numeric, answer_numeric, hint_used, time_signal, question_text)
    elif group == "linear_equations":
        result = _classify_linear_equations(correct_numeric, answer_numeric, hint_used, time_signal, question_text)
    elif group == "simultaneous_equations":
        result = _classify_simultaneous_equations(correct_numeric, answer_numeric, hint_used, time_signal, question_text)
    elif group == "word_problem":
        result = _classify_word_problem(
            correct_numeric, answer_numeric, hint_used, time_signal, question_text, full_unit_id
        )
    elif group == "linear_function":
        result = _classify_linear_function(correct_numeric, answer_numeric, hint_used, time_signal, question_text)
    elif group == "quadratic":
        result = _classify_quadratic(correct_numeric, answer_numeric, hint_used, time_signal, question_text)
    elif group == "functions_quadratic":
        result = _classify_functions_quadratic(correct_numeric, answer_numeric, hint_used, time_signal, question_text)
    elif group == "geometry":
        result = _classify_geometry(correct_numeric, answer_numeric, hint_used, time_signal, question_text)
    elif group == "probability":
        result = _classify_probability(correct_numeric, answer_numeric, hint_used, time_signal, question_text)
    else:
        # ��用フォールバック
        if hint_used >= 2 and time_signal == "long":
            result = "comprehension_gap"
        elif correct_numeric is not None and answer_numeric is not None and abs(answer_numeric - correct_numeric) <= 3:
            result = "arithmetic_error"
        else:
            result = "unknown_error"

    if numeric_pair_ok:
        result = _apply_careless_override(result, correct_numeric, answer_numeric, hint_used, time_signal)

    if result == "unknown_error":
        fb = _fallback_from_error_pattern_candidates(problem)
        if fb:
            result = fb

    return result if result in KNOWN_ERROR_PATTERNS else "unknown_error"


def normalize_error_pattern(error_pattern: str | None) -> str | None:
    if error_pattern in KNOWN_ERROR_PATTERNS:
        return error_pattern
    return "unknown_error" if error_pattern else None
