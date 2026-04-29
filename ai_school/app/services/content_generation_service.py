import ast
import json
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Problem, UnitDependency
from .error_pattern_service import KNOWN_ERROR_PATTERNS
from .intervention_service import KNOWN_INTERVENTION_CANDIDATES
from .unit_map_service import get_unit_map_entry, known_parent_units, resolve_full_unit_id


DIFFICULTY_LABEL_TO_LEVEL = {
    'easy': 1,
    'normal': 2,
    'hard': 3,
}

PROBLEM_TYPES = {'practice', 'mini_test', 'unit_test'}

ALLOWED_IMPORT_KEYS = {
    'full_unit_id',
    'unit_id',
    'sub_unit',
    'problem_type',
    'test_scope',
    'difficulty',
    'question_text',
    'diagram',
    'diagram_required',
    'diagram_params',
    'correct_answer',
    'hint_1',
    'hint_2',
    'explanation_base',
    'error_pattern_candidates',
    'intervention_candidates',
    'problem_id',
    'subject',
    'grade',
    'answer_type',
    'prerequisite_unit',
    'next_if_correct',
    'next_if_wrong',
}


@dataclass
class ValidationResult:
    normalized: dict[str, Any] | None
    errors: list[str]


def load_problem_generation_json(path: str) -> list[dict[str, Any]]:
    with open(path, 'r', encoding='utf-8') as file:
        payload = json.load(file)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get('problems'), list):
        return payload['problems']
    raise ValueError("JSON must be a list or an object with a 'problems' list")


def get_valid_unit_ids(db: Session) -> set[str]:
    db_units = {row[0] for row in db.execute(select(UnitDependency.unit_id)).all()}
    return db_units | known_parent_units()


def get_next_problem_id(db: Session) -> int:
    current_max = db.scalar(select(func.max(Problem.problem_id)))
    return (current_max or 0) + 1


def validate_generated_problem(item: dict[str, Any], valid_unit_ids: set[str]) -> ValidationResult:
    errors: list[str] = []
    unknown_keys = sorted(set(item.keys()) - ALLOWED_IMPORT_KEYS)
    if unknown_keys:
        errors.append(f"unknown keys: {', '.join(unknown_keys)}")

    full_unit_id = str(item.get('full_unit_id', '')).strip() or None
    map_entry = get_unit_map_entry(full_unit_id) if full_unit_id else None
    unit_id = str(item.get('unit_id', '')).strip()
    if map_entry:
        unit_id = map_entry['parent_unit']
    if unit_id not in valid_unit_ids:
        errors.append('unit_id is not registered')

    sub_unit = str(item.get('sub_unit', '')).strip() or None
    if map_entry:
        sub_unit = map_entry['sub_unit']
    resolved_full_unit_id = full_unit_id or resolve_full_unit_id(unit_id, sub_unit)
    if not resolved_full_unit_id:
        errors.append('full_unit_id could not be resolved from unit_id and sub_unit')

    problem_type = str(item.get('problem_type', 'practice')).strip().lower() or 'practice'
    if problem_type not in PROBLEM_TYPES:
        errors.append('problem_type must be practice/mini_test/unit_test')

    test_scope = str(item.get('test_scope', '')).strip() or None
    if problem_type in {'mini_test', 'unit_test'} and not test_scope:
        errors.append('test_scope is required for mini_test/unit_test')

    difficulty_label = str(item.get('difficulty', '')).strip().lower()
    if difficulty_label not in DIFFICULTY_LABEL_TO_LEVEL:
        errors.append('difficulty must be easy/normal/hard')

    question_text = str(item.get('question_text', '')).strip()
    if not question_text:
        errors.append('question_text is required')

    # 英語問題の文脈必須バリデーション
    subject = str(item.get('subject', 'math')).strip() or 'math'
    if subject == 'english':
        # 曖昧な単語表現をチェック
        ambiguous_words = [
            '見る', '作る', '使う', '行く', '来る', '食べる', '飲む', '話す', '聞く', '読む',
            '書く', '買う', '売る', '走る', '飛ぶ', '泳ぐ', '乗る', '降りる', '開く', '閉じる',
            '立つ', '座る', '寝る', '起きる', '着る', '脱ぐ', '洗う', '掃除する', '勉強する', '働く'
        ]
        
        # 問題文に曖昧な単語が単独で含まれているかチェック
        for word in ambiguous_words:
            # 「___」のような穴埋め形式でない場合、または文脈が不十分な場合
            if word in question_text and '___' not in question_text:
                # より詳細な文脈があるかチェック（例: 「空に虹が ___」はOK）
                context_indicators = ['に', 'を', 'で', 'から', 'まで', 'へ', 'と', 'が', 'は']
                has_context = any(indicator in question_text for indicator in context_indicators)
                if not has_context or len(question_text) < 10:
                    errors.append(f'英語問題のquestion_textに曖昧な表現「{word}」が含まれています。文脈を追加してください（例: 「空に虹が ___ 。」）')
                    break

    diagram = item.get('diagram')
    if diagram is not None:
        diagram = str(diagram).strip() or None
    diagram_required = bool(item.get('diagram_required', False))
    diagram_params = item.get('diagram_params')
    if diagram_required:
        if not isinstance(diagram_params, dict) or not diagram_params:
            errors.append('diagram_params is required as non-empty object when diagram_required=true')
    elif diagram_params is not None and not isinstance(diagram_params, dict):
        errors.append('diagram_params must be an object or null')

    correct_answer = str(item.get('correct_answer', '')).strip()
    if not correct_answer:
        errors.append('correct_answer is required')

    # 英語テキスト問題の曖昧な単語チェック
    answer_type = str(item.get('answer_type', 'numeric')).strip() or 'numeric'
    if subject == 'english' and answer_type == 'text':
        ambiguous_english_words = [
            'see', 'look', 'watch', 'make', 'create', 'build', 'do', 'go', 'come', 'eat',
            'drink', 'speak', 'hear', 'read', 'write', 'buy', 'sell', 'run', 'fly', 'swim'
        ]
        # 正解が曖昧な単語の場合、文脈が十分かチェック
        if correct_answer.lower() in ambiguous_english_words:
            # 「___」が含まれていて、問題文が十分な長さがある場合はOK
            if '___' not in question_text or len(question_text) < 10:
                errors.append(f'英語テキスト問題の正解「{correct_answer}」が曖昧な単語です。問題文に十分な文脈を追加してください（例: 「空に虹が ___ 。」）')

    hint_1 = str(item.get('hint_1', '')).strip()
    hint_2 = str(item.get('hint_2', '')).strip()
    if problem_type == 'practice':
        if not hint_1:
            errors.append('hint_1 is required for practice problems')
        if not hint_2:
            errors.append('hint_2 is required for practice problems')

    explanation_base = str(item.get('explanation_base', '')).strip()
    if not explanation_base:
        errors.append('explanation_base is required')

    error_pattern_candidates = item.get('error_pattern_candidates')
    if not isinstance(error_pattern_candidates, list) or not error_pattern_candidates:
        errors.append('error_pattern_candidates must be a non-empty list')
    else:
        invalid_patterns = [pattern for pattern in error_pattern_candidates if pattern not in KNOWN_ERROR_PATTERNS]
        if invalid_patterns:
            errors.append(f"unknown error_pattern_candidates: {', '.join(invalid_patterns)}")

    intervention_candidates = item.get('intervention_candidates')
    if not isinstance(intervention_candidates, list) or not intervention_candidates:
        errors.append('intervention_candidates must be a non-empty list')
    else:
        invalid_interventions = [name for name in intervention_candidates if name not in KNOWN_INTERVENTION_CANDIDATES]
        if invalid_interventions:
            errors.append(f"unknown intervention_candidates: {', '.join(invalid_interventions)}")

    expected_value = compute_expected_value(question_text)
    provided_value = parse_numeric_value(correct_answer)
    if expected_value is not None:
        if provided_value is None:
            errors.append('correct_answer could not be parsed as numeric value')
        elif provided_value != expected_value:
            errors.append(f"correct_answer mismatch: expected {format_fraction(expected_value)}")
    elif unit_id == 'positive_negative_numbers' and '計算をしなさい' in question_text:
        errors.append('question_text could not be evaluated safely')

    if errors:
        return ValidationResult(normalized=None, errors=errors)

    normalized = {
        'problem_id': item.get('problem_id'),
        'subject': str(item.get('subject', 'math')).strip() or 'math',
        'grade': int(item.get('grade', map_entry['grade'] if map_entry else 7)),
        'unit': unit_id,
        'full_unit_id': resolved_full_unit_id,
        'sub_unit': sub_unit,
        'problem_type': problem_type,
        'test_scope': test_scope,
        'difficulty': DIFFICULTY_LABEL_TO_LEVEL[difficulty_label],
        'question_text': question_text,
        'diagram': diagram,
        'diagram_required': diagram_required,
        'diagram_params': json.dumps(diagram_params, ensure_ascii=False) if isinstance(diagram_params, dict) else None,
        'answer_type': str(item.get('answer_type', 'numeric')).strip() or 'numeric',
        'choices': json.dumps(item['choices'], ensure_ascii=False) if isinstance(item.get('choices'), list) else None,
        'correct_answer': correct_answer,
        'hint_text': hint_1 or None,
        'hint_1': hint_1 or None,
        'hint_2': hint_2 or None,
        'explanation_base': explanation_base,
        'error_pattern_candidates': json.dumps(error_pattern_candidates, ensure_ascii=False),
        'intervention_candidates': json.dumps(intervention_candidates, ensure_ascii=False),
        'prerequisite_unit': item.get('prerequisite_unit'),
        'next_if_correct': item.get('next_if_correct'),
        'next_if_wrong': item.get('next_if_wrong'),
    }
    return ValidationResult(normalized=normalized, errors=[])


def import_generated_problems(db: Session, items: list[dict[str, Any]]) -> dict[str, Any]:
    valid_unit_ids = get_valid_unit_ids(db)
    next_problem_id = get_next_problem_id(db)
    inserted = 0
    skipped: list[dict[str, Any]] = []
    inserted_test_counts: dict[tuple[str, str], int] = {}

    for index, item in enumerate(items, start=1):
        result = validate_generated_problem(item, valid_unit_ids)
        if result.normalized is None:
            skipped.append({'index': index, 'question_text': item.get('question_text'), 'errors': result.errors})
            continue
        payload = result.normalized
        if payload['problem_id'] is None:
            payload['problem_id'] = next_problem_id
            next_problem_id += 1
        existing = db.get(Problem, payload['problem_id'])
        if existing is not None:
            skipped.append(
                {
                    'index': index,
                    'question_text': payload['question_text'],
                    'errors': [f"problem_id {payload['problem_id']} already exists"],
                }
            )
            continue
        payload['status'] = 'pending'
        db.add(Problem(**payload))
        inserted += 1
        if payload['problem_type'] in {'mini_test', 'unit_test'} and payload['full_unit_id'] and payload['test_scope']:
            key = (payload['full_unit_id'], payload['test_scope'])
            inserted_test_counts[key] = inserted_test_counts.get(key, 0) + 1

    db.commit()
    warnings: list[str] = []
    for (full_unit_id, test_scope), count in sorted(inserted_test_counts.items()):
        recommended = 5 if test_scope == 'mini_test' else 10 if test_scope == 'unit_test' else None
        if recommended is not None and count != recommended:
            warnings.append(
                f"{full_unit_id} {test_scope}: inserted {count} problems (recommended {recommended})"
            )
    return {'inserted': inserted, 'skipped': skipped, 'warnings': warnings}


def compute_expected_value(question_text: str) -> Fraction | None:
    if '計算をしなさい' not in question_text:
        return None
    expression = question_text.split('計算をしなさい', 1)[1]
    expression = expression.strip()
    if expression.startswith('。'):
        expression = expression[1:].strip()
    expression = expression.replace(' ', '').replace('　', '')
    expression = expression.replace('−', '-').replace('－', '-').replace('×', '*').replace('÷', '/')
    expression = expression.replace('^', '**')
    expression = re.sub(r'\(\+', '(', expression)
    expression = re.sub(r'(?<![0-9)])\+', '', expression)
    if not re.fullmatch(r'[0-9+\-*/().]+', expression):
        return None
    try:
        node = ast.parse(expression, mode='eval')
        return _eval_fraction_node(node.body)
    except Exception:
        return None


def parse_numeric_value(value: str) -> Fraction | None:
    normalized = value.strip().replace('−', '-').replace('－', '-')
    if not normalized:
        return None
    try:
        return Fraction(normalized)
    except (ValueError, ZeroDivisionError):
        return None


def format_fraction(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f'{value.numerator}/{value.denominator}'


def _eval_fraction_node(node: ast.AST) -> Fraction:
    if isinstance(node, ast.BinOp):
        left = _eval_fraction_node(node.left)
        right = _eval_fraction_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            if right.denominator != 1 or right < 0:
                raise ValueError('unsupported exponent')
            return left ** right.numerator
        raise ValueError('unsupported operator')
    if isinstance(node, ast.UnaryOp):
        operand = _eval_fraction_node(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
        raise ValueError('unsupported unary operator')
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return Fraction(str(node.value))
    if isinstance(node, ast.Num):
        return Fraction(str(node.n))
    raise ValueError('unsupported expression')


def normalize_numeric_string(value: str) -> str:
    try:
        numeric = float(value)
    except ValueError:
        return value.strip()
    if numeric.is_integer():
        return str(int(numeric))
    return str(numeric)
