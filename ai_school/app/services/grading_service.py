from ..models import Problem
from .answer_input_spec_service import MULTI_ANSWER_DELIMITER
from .math_text_service import normalize_answer_for_grading


# 英語動詞などの類義語グループ定義
# near_misses: 「惜しい」と判定する代替答え
# hint_key: 使い分けマップを生成する際のキー
SYNONYM_GROUPS = {
    "see": {
        "near_misses": ["look", "watch"],
        "hint_key": "see_look_watch",
        "context": "自然と目に入る、見える"
    },
    "look": {
        "near_misses": ["see", "watch"],
        "hint_key": "see_look_watch",
        "context": "意識して目を向ける"
    },
    "watch": {
        "near_misses": ["see", "look"],
        "hint_key": "see_look_watch",
        "context": "動きをじっと追う"
    },
    "make": {
        "near_misses": ["create", "build"],
        "hint_key": "make_create",
        "context": "作る、製造する"
    },
    "create": {
        "near_misses": ["make", "build"],
        "hint_key": "make_create",
        "context": "創造する"
    },
    "build": {
        "near_misses": ["make", "create"],
        "hint_key": "make_create",
        "context": "建設する"
    },
}


# 発見バッジの定義
DISCOVERY_BADGES = {
    "see_look_watch_discovery": {
        "name": "🔍 観察マスター",
        "description": "see/look/watchの違いを学びました",
        "emoji": "🔍",
        "condition": "first_discovery"  # 初めてのnear_miss
    },
    "make_create_discovery": {
        "name": "⚒️ 創造マスター", 
        "description": "make/create/buildの違いを学びました",
        "emoji": "⚒️",
        "condition": "first_discovery"
    },
    "overcome_mistake": {
        "name": "⭐ 克服！",
        "description": "同じミスを2回しなくなりました",
        "emoji": "⭐",
        "condition": "no_repeat_mistake"  # 同じミスを繰り返さなくなった
    }
}


def normalize_answer(answer: str) -> str:
    return normalize_answer_for_grading(answer)


def _normalize_sort(s: str) -> str:
    """語順並び替え用: 小文字化・余分スペース除去・句読点前後のスペース正規化"""
    return " ".join(s.lower().split())


def _grade_math_normalized(problem: Problem, submitted_answer: str) -> bool:
    correct = problem.correct_answer or ""
    d = MULTI_ANSWER_DELIMITER
    if d in submitted_answer or d in correct:
        s_parts = submitted_answer.split(d)
        c_parts = correct.split(d)
        if len(s_parts) != len(c_parts):
            return False
        return all(
            normalize_answer_for_grading(a) == normalize_answer_for_grading(b)
            for a, b in zip(s_parts, c_parts)
        )
    return normalize_answer_for_grading(submitted_answer) == normalize_answer_for_grading(correct)


def _normalize_english_text(s: str) -> str:
    """英語テキスト解答用: 小文字化・前後トリム・連続スペースを1つに正規化（スペース自体は保持）"""
    import unicodedata
    s = unicodedata.normalize("NFKC", s)
    # 全角スペース → 半角スペース、前後トリム、連続スペースを1つに
    s = s.replace("\u3000", " ").strip()
    s = " ".join(s.split())
    return s.lower()


def grade_answer(problem: Problem, submitted_answer: str) -> bool:
    if problem.answer_type == "sort":
        return _normalize_sort(submitted_answer) == _normalize_sort(problem.correct_answer)
    if problem.answer_type == "choice":
        # 選択式は大文字小文字を無視して比較
        return submitted_answer.strip().lower() == (problem.correct_answer or "").strip().lower()
    if problem.answer_type == "text":
        if problem.subject == "english":
            # 英語テキストはスペースを保持して小文字比較
            return _normalize_english_text(submitted_answer) == _normalize_english_text(problem.correct_answer or "")
        return _grade_math_normalized(problem, submitted_answer)
    if problem.answer_type == "numeric":
        return _grade_math_normalized(problem, submitted_answer)
    return False


def grade_answer_detailed(problem: Problem, submitted_answer: str, full_score: float = 1.0) -> dict:
    """
    詳細な判定を返す関数
    
    Args:
        problem: Problem オブジェクト
        submitted_answer: 提出された解答
        full_score: 満点（デフォルト: 1.0）
    
    Returns:
        {
            "judgment": "correct" | "near_miss" | "wrong",
            "score": float,  # 満点に対する比率
            "correct_answer": str,
            "near_miss_info": Optional[dict]  # near_miss時のみ情報を含む
        }
    """
    correct = (problem.correct_answer or "").strip()
    submitted = submitted_answer.strip()
    
    # 正解判定
    if problem.answer_type == "sort":
        if _normalize_sort(submitted) == _normalize_sort(correct):
            return {
                "judgment": "correct",
                "score": full_score,
                "correct_answer": correct,
                "near_miss_info": None
            }
    elif problem.answer_type == "choice":
        if submitted.lower() == correct.lower():
            return {
                "judgment": "correct",
                "score": full_score,
                "correct_answer": correct,
                "near_miss_info": None
            }
    elif problem.answer_type == "text":
        if problem.subject == "english":
            normalized_submitted = _normalize_english_text(submitted)
            normalized_correct = _normalize_english_text(correct)
            
            if normalized_submitted == normalized_correct:
                return {
                    "judgment": "correct",
                    "score": full_score,
                    "correct_answer": correct,
                    "near_miss_info": None
                }
            
            # 英語テキスト: near_miss判定
            near_miss_result = _check_english_near_miss(normalized_submitted, normalized_correct)
            if near_miss_result:
                return {
                    "judgment": "near_miss",
                    "score": full_score * 0.5,  # ゴールド半分
                    "correct_answer": correct,
                    "near_miss_info": near_miss_result
                }
        else:
            if _grade_math_normalized(problem, submitted):
                return {
                    "judgment": "correct",
                    "score": full_score,
                    "correct_answer": correct,
                    "near_miss_info": None
                }
    elif problem.answer_type == "numeric":
        if _grade_math_normalized(problem, submitted):
            return {
                "judgment": "correct",
                "score": full_score,
                "correct_answer": correct,
                "near_miss_info": None
            }
    
    # 不正解
    return {
        "judgment": "wrong",
        "score": 0.0,
        "correct_answer": correct,
        "near_miss_info": None
    }


def _check_english_near_miss(submitted_normalized: str, correct_normalized: str) -> dict | None:
    """
    英語解答の near_miss をチェック
    
    SYNONYM_GROUPS に定義された類義語群から near_miss を判定する
    
    Returns:
        {
            "submitted_word": str,
            "correct_word": str,
            "hint_key": str
        }
        または None（near_miss ではない場合）
    """
    # 提出された単語が SYNONYM_GROUPS のいずれかの near_misses に含まれるかチェック
    for correct_word, group_info in SYNONYM_GROUPS.items():
        if correct_normalized == correct_word and submitted_normalized in group_info.get("near_misses", []):
            return {
                "submitted_word": submitted_normalized,
                "correct_word": correct_normalized,
                "hint_key": group_info.get("hint_key"),
                "group_info": group_info
            }
    
    return None


def generate_synonym_comparison_map(
    submitted_word: str,
    correct_word: str,
    hint_key: str | None = None
) -> dict | None:
    """
    near_miss 判定時に、使い分けマップを Claude Haiku 4.5 で生成する
    
    Args:
        submitted_word: ユーザーが回答した単語（例: "look"）
        correct_word: 正解の単語（例: "see"）
        hint_key: グループのヒントキー（例: "see_look_watch"）
    
    Returns:
        {
            "message": "...",  # 惜しい！から始まる説明
            "comparison": [
                {
                    "word": "see",
                    "nuance": "...",
                    "emoji": "✨",
                    "example": "..."
                },
                ...
            ]
        }
        または None（生成失敗時）
    """
    from .ai_service import generate_claude_text
    import json
    
    system_prompt = """You are a supportive English teacher for junior high school students.
Your task is to explain the nuance differences between similar English words in a way that encourages learning.

Rules:
- Be encouraging and positive, starting with "惜しい！(Close!)" in Japanese
- Explain why the student's answer was not wrong, but the context requires a different word
- Use emoji and short example sentences to make it fun and memorable
- Always respond in Japanese for explanations, examples are in English
- Output ONLY valid JSON, nothing else
- Include 2-3 words in the comparison array

Response format (valid JSON only):
{
  "message": "惜しい！...",
  "comparison": [
    {"word": "word1", "nuance": "説明", "emoji": "emoji", "example": "English example sentence"},
    ...
  ]
}"""

    user_prompt = f"""中学生向けに、「{submitted_word}」と「{correct_word}」の使い分けを説明してください。
ヒントキー: {hint_key or 'なし'}

「{submitted_word}」を答えた生徒を責めず、「惜しい！」から始めて、
なぜ「{correct_word}」が正解なのかを、絵文字と短い例文で楽しく説明してください。

2つ以上の類義語を含めて、使い分けマップを作ってください。

日本語での説明を含むJSONのみを出力してください。他の説明は不要です。"""

    result_text = generate_claude_text(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_output_tokens=500
    )
    
    if not result_text:
        return None
    
    try:
        # JSON パースを試みる
        return json.loads(result_text)
    except json.JSONDecodeError:
        # JSON が不正な場合は None を返す
        return None


def get_student_discovered_nuances(student_state) -> dict:
    """
    学生のdiscovered_nuancesを取得（JSONパース）
    
    Returns:
        {
            "badges": ["badge_key1", "badge_key2"],
            "near_miss_history": {
                "hint_key": {
                    "count": int,
                    "last_mistake": "YYYY-MM-DD",
                    "first_discovery": "YYYY-MM-DD"
                }
            }
        }
    """
    if not student_state.discovered_nuances:
        return {"badges": [], "near_miss_history": {}}
    
    try:
        import json
        return json.loads(student_state.discovered_nuances)
    except json.JSONDecodeError:
        return {"badges": [], "near_miss_history": {}}


def update_student_discovered_nuances(student_state, hint_key: str, is_correct: bool) -> tuple[dict, list[str]]:
    """
    near_miss発生時に学生のnuance発見履歴を更新
    
    Args:
        student_state: StudentStateオブジェクト
        hint_key: near_missのhint_key（例: "see_look_watch"）
        is_correct: 今回の判定結果（near_missの場合はFalse）
    
    Returns:
        (updated_data, new_badges) - 更新されたデータと新しく獲得したバッジのリスト
    """
    import json
    from datetime import datetime
    
    current_data = get_student_discovered_nuances(student_state)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    
    new_badges = []
    
    # near_miss_historyの更新
    if hint_key not in current_data["near_miss_history"]:
        current_data["near_miss_history"][hint_key] = {
            "count": 0,
            "last_mistake": None,
            "first_discovery": today
        }
    
    history = current_data["near_miss_history"][hint_key]
    
    if not is_correct:  # near_missの場合
        history["count"] += 1
        history["last_mistake"] = today
        
        # 初めてのnear_missの場合、バッジ獲得
        if history["count"] == 1 and f"{hint_key}_discovery" in DISCOVERY_BADGES:
            badge_key = f"{hint_key}_discovery"
            if badge_key not in current_data["badges"]:
                current_data["badges"].append(badge_key)
                new_badges.append(badge_key)
    
    # 克服バッジのチェック（同じミスを2回以上繰り返さなくなった場合）
    if history["count"] >= 1 and is_correct:
        # 同じhint_keyで以前ミスしたことがあり、正解した場合
        overcome_badge = "overcome_mistake"
        if overcome_badge not in current_data["badges"]:
            current_data["badges"].append(overcome_badge)
            new_badges.append(overcome_badge)
    
    # JSONに保存
    student_state.discovered_nuances = json.dumps(current_data, ensure_ascii=False)
    
    return current_data, new_badges


def get_student_badges_display(student_state) -> list[dict]:
    """
    学生の獲得バッジを表示用にフォーマット
    
    Returns:
        [
            {
                "key": "badge_key",
                "name": "バッジ名",
                "description": "説明",
                "emoji": "絵文字"
            }
        ]
    """
    current_data = get_student_discovered_nuances(student_state)
    badges = []
    
    for badge_key in current_data["badges"]:
        if badge_key in DISCOVERY_BADGES:
            badge_info = DISCOVERY_BADGES[badge_key]
            badges.append({
                "key": badge_key,
                "name": badge_info["name"],
                "description": badge_info["description"],
                "emoji": badge_info["emoji"]
            })
    
    return badges
