from __future__ import annotations

import json
import math
import re
import sqlite3
from pathlib import Path
from typing import Any

from .diagram_display_name_service import get_diagram_display_info
from .diagram_service import build_problem_diagram_svg, render_problem_diagram_for_route

_SUSPECT_CHARS = {chr(0xFFFD), "Ã", "Â", "ã", "ç", "Б", "Ð", "Ñ"}


def _contains_mojibake(text: str) -> bool:
    return any(char in text for char in _SUSPECT_CHARS)


def _has_placeholder_question_block(text: str) -> bool:
    return re.search(r"\?{2,}", text) is not None


def _iter_text_nodes(svg: str):
    for match in re.finditer(r'<text([^>]*)x="([^"]+)" y="([^"]+)"([^>]*)>([^<]*)</text>', svg):
        attrs = (match.group(1) or '') + (match.group(4) or '')
        try:
            x = float(match.group(2))
            y = float(match.group(3))
        except ValueError:
            continue
        yield {'attrs': attrs, 'x': x, 'y': y, 'text': match.group(5)}


def _iter_lines(svg: str):
    for match in re.finditer(r'<line([^>]*)x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"([^>]*)/>', svg):
        attrs = (match.group(1) or '') + (match.group(6) or '')
        if 'parallel-symbol' in attrs:
            continue
        try:
            x1 = float(match.group(2))
            y1 = float(match.group(3))
            x2 = float(match.group(4))
            y2 = float(match.group(5))
        except ValueError:
            continue
        if math.hypot(x2 - x1, y2 - y1) < 18.0:
            continue
        yield (x1, y1, x2, y2)


def _distance_to_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx = x2 - x1
    dy = y2 - y1
    denom = dx * dx + dy * dy
    if math.isclose(denom, 0.0):
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / denom))
    cx = x1 + t * dx
    cy = y1 + t * dy
    return math.hypot(px - cx, py - cy)


def analyze_diagram_svg(problem: dict | object, route_name: str, svg: str | None) -> dict[str, Any]:
    display = get_diagram_display_info(problem, route=route_name)
    diagram_type = display.get('diagram_type')
    subtype = display.get('subtype')
    if not svg:
        result = {
            'problem_id': getattr(problem, 'problem_id', None) if not isinstance(problem, dict) else problem.get('problem_id'),
            'route_name': route_name,
            'diagram_type': diagram_type,
            'subtype': subtype,
            'has_mojibake': False,
            'has_question_marks': False,
            'text_collision_count': 0,
            'line_collision_count': 0,
            'fallback_used': False,
            'svg_present': False,
        }
        print('[DIAGRAM_QA] ' + ' '.join(f'{k}={result[k]}' for k in ['problem_id','route_name','diagram_type','subtype','has_mojibake','has_question_marks','text_collision_count','line_collision_count','fallback_used']))
        return result

    text_nodes = list(_iter_text_nodes(svg))
    line_segments = list(_iter_lines(svg))
    angle_labels = [node for node in text_nodes if 'class="angle-label"' in node['attrs']]
    other_labels = [node for node in text_nodes if 'class="angle-label"' not in node['attrs']]

    line_collision_count = 0
    for node in angle_labels:
        if min((_distance_to_segment(node['x'], node['y'], *segment) for segment in line_segments), default=999.0) < 12.0:
            line_collision_count += 1

    text_collision_count = 0
    for index, node in enumerate(angle_labels):
        for other in other_labels:
            if math.hypot(node['x'] - other['x'], node['y'] - other['y']) < 16.0:
                text_collision_count += 1
        for other in angle_labels[index + 1:]:
            if math.hypot(node['x'] - other['x'], node['y'] - other['y']) < 14.0:
                text_collision_count += 1

    combined_text = ' '.join(node['text'] for node in text_nodes)
    has_mojibake = _contains_mojibake(svg) or _contains_mojibake(combined_text)
    has_question_marks = _has_placeholder_question_block(svg) or _has_placeholder_question_block(combined_text)
    fallback_used = 'data-diagram-semantic="incomplete"' in svg
    problem_id = getattr(problem, 'problem_id', None) if not isinstance(problem, dict) else problem.get('problem_id')
    result = {
        'problem_id': problem_id,
        'route_name': route_name,
        'diagram_type': diagram_type,
        'subtype': subtype,
        'has_mojibake': has_mojibake,
        'has_question_marks': has_question_marks,
        'text_collision_count': text_collision_count,
        'line_collision_count': line_collision_count,
        'fallback_used': fallback_used,
        'svg_present': True,
    }
    print('[DIAGRAM_QA] ' + ' '.join(f'{k}={result[k]}' for k in ['problem_id','route_name','diagram_type','subtype','has_mojibake','has_question_marks','text_collision_count','line_collision_count','fallback_used']))
    return result


def _row_to_problem(row: sqlite3.Row) -> dict[str, Any]:
    diagram_params = row['diagram_params']
    if isinstance(diagram_params, str):
        try:
            diagram_params = json.loads(diagram_params)
        except json.JSONDecodeError:
            diagram_params = None
    return {
        'problem_id': row['problem_id'],
        'unit': row['unit'],
        'full_unit_id': row['full_unit_id'],
        'question_text': row['question_text'],
        'diagram_required': bool(row['diagram_required']),
        'diagram_params': diagram_params,
    }


def scan_all_diagrams(db_path: str | Path) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute('SELECT problem_id, unit, full_unit_id, question_text, diagram_required, diagram_params FROM problems WHERE diagram_required = 1 ORDER BY problem_id').fetchall()
    reports = []
    for row in rows:
        problem = _row_to_problem(row)
        student_svg = render_problem_diagram_for_route(problem, 'student')
        teacher_svg = render_problem_diagram_for_route(problem, 'teacher_preview')
        student_report = analyze_diagram_svg(problem, 'student', student_svg)
        teacher_report = analyze_diagram_svg(problem, 'teacher_preview', teacher_svg)
        reports.extend([student_report, teacher_report])
    conn.close()
    severe = [item for item in reports if item['has_mojibake'] or item['has_question_marks']]
    return {
        'problem_count': len(rows),
        'report_count': len(reports),
        'severe_count': len(severe),
        'reports': reports,
    }
