import json
import math
import re
from html import escape

from .geometry_builder import build_parallel_lines_angle_geometry
from .geometry_layout_service import resolve_parallel_lines_angle_layout
from .geometry_spec_service import parse_parallel_lines_angle_spec
from .geometry_svg_renderer import render_parallel_lines_angle_svg as render_parallel_lines_angle_geometry_svg


SVG_SIZE = 320
PADDING = 32


ANGLE_SNAP_TOLERANCE = 6.0


def _normalize_angle_deg(angle: float) -> float:
    return angle % 360.0


def _circular_distance_deg(a: float, b: float) -> float:
    diff = abs(_normalize_angle_deg(a) - _normalize_angle_deg(b))
    return min(diff, 360.0 - diff)


def _angle_from_points(origin: tuple[float, float], target: tuple[float, float]) -> float:
    dx = target[0] - origin[0]
    dy = origin[1] - target[1]
    return _normalize_angle_deg(math.degrees(math.atan2(dy, dx)))


def _normalize_small_arc_deg(start_deg: float, end_deg: float) -> tuple[float, float]:
    start = _normalize_angle_deg(start_deg)
    end = _normalize_angle_deg(end_deg)
    delta = (end - start) % 360.0
    if delta > 180.0:
        start, end = end, start
    return start, end


def _point_to_infinite_line_distance(point: tuple[float, float], p1: tuple[float, float], p2: tuple[float, float]) -> float:
    px, py = point
    x1, y1 = p1
    x2, y2 = p2
    denom = math.hypot(x2 - x1, y2 - y1) or 1.0
    return abs((y2 - y1) * px - (x2 - x1) * py + x2 * y1 - y2 * x1) / denom


def _line_intersection(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
) -> tuple[float, float] | None:
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if math.isclose(denom, 0.0):
        return None
    det1 = x1 * y2 - y1 * x2
    det2 = x3 * y4 - y3 * x4
    px = (det1 * (x3 - x4) - (x1 - x2) * det2) / denom
    py = (det1 * (y3 - y4) - (y1 - y2) * det2) / denom
    return round(px, 2), round(py, 2)


def _build_parallel_line_defs(parallel_lines: list[dict], transversals: list[dict]) -> list[dict]:
    line_defs: list[dict] = []
    for index, line in enumerate(parallel_lines[:2]):
        y = line.get("y")
        if y is None:
            continue
        y_value = float(y)
        line_defs.append(
            {
                "id": f"parallel-{index}",
                "p1": (36.0, y_value),
                "p2": (284.0, y_value),
            }
        )
    for index, line in enumerate(transversals):
        x1 = line.get("x1")
        y1 = line.get("y1")
        x2 = line.get("x2")
        y2 = line.get("y2")
        if None in (x1, y1, x2, y2):
            continue
        line_defs.append(
            {
                "id": f"transversal-{index}",
                "p1": (float(x1), float(y1)),
                "p2": (float(x2), float(y2)),
            }
        )
    return line_defs


def _ray_angles_for_line(line_def: dict, vertex: tuple[float, float]) -> tuple[float, float]:
    base_angle = _angle_from_points(line_def["p1"], line_def["p2"])
    opposite_angle = _normalize_angle_deg(base_angle + 180.0)
    return base_angle, opposite_angle


def _resolve_parallel_angle_mark(mark: dict, parallel_lines: list[dict], transversals: list[dict]) -> dict | None:
    vertex = mark.get("vertex")
    if not isinstance(vertex, dict):
        return None
    approx_vertex = (float(vertex["x"]), float(vertex["y"]))
    line_defs = _build_parallel_line_defs(parallel_lines, transversals)
    incident = [
        line_def
        for line_def in line_defs
        if _point_to_infinite_line_distance(approx_vertex, line_def["p1"], line_def["p2"]) <= ANGLE_SNAP_TOLERANCE
    ]
    if len(incident) < 2:
        return None

    from_hint = mark.get("from_deg")
    to_hint = mark.get("to_deg")
    best: dict | None = None

    for index, first in enumerate(incident):
        for second in incident[index + 1 :]:
            intersection = _line_intersection(first["p1"], first["p2"], second["p1"], second["p2"])
            if intersection is None:
                continue
            distance = math.hypot(intersection[0] - approx_vertex[0], intersection[1] - approx_vertex[1])
            if distance > 18:
                continue
            first_angles = _ray_angles_for_line(first, intersection)
            second_angles = _ray_angles_for_line(second, intersection)
            for first_angle in first_angles:
                for second_angle in second_angles:
                    start_angle, end_angle = _normalize_small_arc_deg(first_angle, second_angle)
                    score = distance
                    if from_hint is not None and to_hint is not None:
                        ordered = _circular_distance_deg(start_angle, float(from_hint)) + _circular_distance_deg(end_angle, float(to_hint))
                        swapped = _circular_distance_deg(start_angle, float(to_hint)) + _circular_distance_deg(end_angle, float(from_hint))
                        score += min(ordered, swapped)
                    if best is None or score < best["score"]:
                        best = {
                            "score": score,
                            "vertex": intersection,
                            "from_deg": start_angle,
                            "to_deg": end_angle,
                        }

    if best is None:
        return None

    return {
        **mark,
        "vertex": {"x": best["vertex"][0], "y": best["vertex"][1]},
        "from_deg": best["from_deg"],
        "to_deg": best["to_deg"],
    }


def get_problem_diagram_status(problem: dict | object) -> dict:
    try:
        diagram_required = bool(_get_problem_attr(problem, "diagram_required", False))
        if not diagram_required:
            return {
                "required": False,
                "renderable": False,
                "diagram_badge": None,
                "status_label": None,
            }

        svg = build_problem_diagram_svg(problem)
        return {
            "required": True,
            "renderable": bool(svg),
            "diagram_badge": "図あり",
            "status_label": "描画OK" if svg else "未対応",
        }
    except Exception:
        return {
            "required": bool(_get_problem_attr(problem, "diagram_required", False)),
            "renderable": False,
            "diagram_badge": "図あり" if _get_problem_attr(problem, "diagram_required", False) else None,
            "status_label": "未対応" if _get_problem_attr(problem, "diagram_required", False) else None,
        }


def build_problem_diagram_svg(problem: dict | object) -> str | None:
    try:
        diagram_required = _get_problem_attr(problem, "diagram_required", False)
        if not diagram_required:
            return None

        raw_params = _get_problem_attr(problem, "diagram_params")
        diagram_params = _normalize_diagram_params(raw_params)
        if not isinstance(diagram_params, dict):
            return None

        diagram_type = diagram_params.get("diagram_type") or diagram_params.get("type")
        full_unit_id = _get_problem_attr(problem, "full_unit_id")
        unit_id = _get_problem_attr(problem, "unit")
        sub_unit = _get_problem_attr(problem, "sub_unit")

        if diagram_type == "parallel_lines_angle":
            return render_parallel_lines_angle_svg(diagram_params)
        if diagram_type == "triangle_correspondence":
            return render_triangle_correspondence_svg(diagram_params)
        if diagram_type == "similar_triangles_basic":
            return render_similar_triangles_basic_svg(diagram_params)

        is_linear_graph = (
            diagram_type == "linear_function_graph"
            or full_unit_id == "linear_function_graph"
            or (unit_id == "linear_function" and sub_unit == "graph")
        )
        if not is_linear_graph:
            if diagram_type == "circle_inscribed_angle":
                return render_circle_inscribed_angle_svg(diagram_params)
            return None

        if diagram_type == "line_axes_triangle":
            return render_line_axes_triangle_svg(diagram_params)
        if diagram_type == "two_lines_and_y_axis":
            return render_two_lines_and_y_axis_svg(diagram_params)
        return render_linear_function_graph_svg(diagram_params)
    except Exception:
        return None


def render_linear_function_graph_svg(diagram_params: dict) -> str | None:
    try:
        normalized = _normalize_linear_function_params(diagram_params)
        if normalized is None:
            return None

        line = normalized["line"]
        points = normalized["points"][:2]
        x_min, x_max = normalized["x_range"]
        y_min, y_max = normalized["y_range"]

        def to_svg(x: float, y: float) -> tuple[float, float]:
            usable = SVG_SIZE - 2 * PADDING
            svg_x = PADDING + (x - x_min) / (x_max - x_min) * usable
            svg_y = SVG_SIZE - PADDING - (y - y_min) / (y_max - y_min) * usable
            return round(svg_x, 2), round(svg_y, 2)

        axis_parts: list[str] = []
        tick_parts: list[str] = []
        label_parts: list[str] = []

        if x_min <= 0 <= x_max:
            x1, y0 = to_svg(x_min, 0)
            x2, _ = to_svg(x_max, 0)
            axis_parts.append(
                f'<line x1="{x1}" y1="{y0}" x2="{x2}" y2="{y0}" stroke="#9ca3af" stroke-width="1.5" />'
            )
        if y_min <= 0 <= y_max:
            x0, y1 = to_svg(0, y_min)
            _, y2 = to_svg(0, y_max)
            axis_parts.append(
                f'<line x1="{x0}" y1="{y1}" x2="{x0}" y2="{y2}" stroke="#9ca3af" stroke-width="1.5" />'
            )

        for x in _build_ticks(x_min, x_max):
            svg_x, svg_y = to_svg(x, 0 if y_min <= 0 <= y_max else y_min)
            tick_parts.append(
                f'<line x1="{svg_x}" y1="{svg_y - 4}" x2="{svg_x}" y2="{svg_y + 4}" stroke="#cbd5e1" stroke-width="1" />'
            )
            label_parts.append(
                f'<text x="{svg_x}" y="{SVG_SIZE - 10}" text-anchor="middle" font-size="11" fill="#6b7280">{_format_number(x)}</text>'
            )

        for y in _build_ticks(y_min, y_max):
            svg_x, svg_y = to_svg(0 if x_min <= 0 <= x_max else x_min, y)
            tick_parts.append(
                f'<line x1="{svg_x - 4}" y1="{svg_y}" x2="{svg_x + 4}" y2="{svg_y}" stroke="#cbd5e1" stroke-width="1" />'
            )
            label_parts.append(
                f'<text x="12" y="{svg_y + 4}" text-anchor="start" font-size="11" fill="#6b7280">{_format_number(y)}</text>'
            )

        left_y = line["slope"] * x_min + line["intercept"]
        right_y = line["slope"] * x_max + line["intercept"]
        line_x1, line_y1 = to_svg(x_min, left_y)
        line_x2, line_y2 = to_svg(x_max, right_y)
        graph_line = (
            f'<line x1="{line_x1}" y1="{line_y1}" x2="{line_x2}" y2="{line_y2}" '
            'stroke="#2563eb" stroke-width="3" />'
        )

        point_parts: list[str] = []
        for point in points:
            svg_x, svg_y = to_svg(point["x"], point["y"])
            point_parts.append(
                f'<circle cx="{svg_x}" cy="{svg_y}" r="5" fill="#f97316" stroke="#ffffff" stroke-width="1.5" />'
            )
            label = escape(str(point.get("label") or ""))
            if label:
                label_dx = float(point.get("label_dx", 8))
                label_dy = float(point.get("label_dy", -8))
                point_parts.append(
                    f'<text x="{svg_x + label_dx}" y="{svg_y + label_dy}" font-size="12" font-weight="700" fill="#9a3412">{label}</text>'
                )

        equation_label = escape(
            f'y = {_format_number(line["slope"])}x {"+ " if line["intercept"] >= 0 else "- "}{_format_number(abs(line["intercept"]))}'
        )

        return (
            f'<svg class="problem-diagram-svg" viewBox="0 0 {SVG_SIZE} {SVG_SIZE}" '
            f'width="{SVG_SIZE}" height="{SVG_SIZE}" role="img" aria-label="一次関数のグラフ">'
            '<rect x="0" y="0" width="320" height="320" rx="18" fill="#ffffff" />'
            '<rect x="1" y="1" width="318" height="318" rx="17" fill="none" stroke="#e5e7eb" />'
            '<text x="20" y="24" font-size="13" font-weight="700" fill="#1f2937">グラフ</text>'
            f'<text x="300" y="24" text-anchor="end" font-size="12" fill="#2563eb">{equation_label}</text>'
            f'{"".join(axis_parts)}'
            f'{"".join(tick_parts)}'
            f'{graph_line}'
            f'{"".join(point_parts)}'
            f'{"".join(label_parts)}'
            "</svg>"
        )
    except Exception:
        return None


def render_line_axes_triangle_svg(diagram_params: dict) -> str | None:
    try:
        equation = diagram_params.get("equation")
        if not isinstance(equation, str):
            return None
        line = _parse_linear_equation(equation)
        if line is None or math.isclose(line["slope"], 0.0):
            return None

        x_intercept = -line["intercept"] / line["slope"]
        y_intercept = line["intercept"]
        normalized = {
            "line": line,
            "points": [
                {"x": 0.0, "y": y_intercept, "label": "A"},
                {"x": x_intercept, "y": 0.0, "label": "B"},
            ],
            "x_range": _normalize_range(diagram_params.get("x_range"), default_min=min(0.0, x_intercept) - 1, default_max=max(4.0, x_intercept) + 1),
            "y_range": _normalize_range(diagram_params.get("y_range"), default_min=-1.0, default_max=max(4.0, y_intercept) + 1),
        }
        canvas = _build_graph_canvas(normalized["x_range"], normalized["y_range"], f'直線 {equation}')
        p_origin = canvas["to_svg"](0.0, 0.0)
        p_y = canvas["to_svg"](0.0, y_intercept)
        p_x = canvas["to_svg"](x_intercept, 0.0)
        polygon = (
            f'<polygon points="{p_origin[0]},{p_origin[1]} {p_y[0]},{p_y[1]} {p_x[0]},{p_x[1]}" '
            'fill="rgba(37,99,235,0.12)" stroke="#93c5fd" stroke-width="1.5" />'
        )
        graph_line = _build_line_segment(canvas["to_svg"], normalized["line"], normalized["x_range"], "#2563eb")
        point_parts = _build_point_parts(canvas["to_svg"], normalized["points"])
        return _assemble_svg(canvas, polygon + graph_line + point_parts)
    except Exception:
        return None


def render_two_lines_and_y_axis_svg(diagram_params: dict) -> str | None:
    try:
        equations = diagram_params.get("equations")
        if not isinstance(equations, list) or len(equations) != 2:
            return None
        first = _parse_linear_equation(equations[0]) if isinstance(equations[0], str) else None
        second = _parse_linear_equation(equations[1]) if isinstance(equations[1], str) else None
        if first is None or second is None or math.isclose(first["slope"], second["slope"]):
            return None

        x_cross = (second["intercept"] - first["intercept"]) / (first["slope"] - second["slope"])
        y_cross = first["slope"] * x_cross + first["intercept"]
        x_range = _normalize_range(diagram_params.get("x_range"), default_min=min(0.0, x_cross) - 1, default_max=max(4.0, x_cross) + 1)
        y_values = [first["intercept"], second["intercept"], y_cross]
        y_range = _normalize_range(diagram_params.get("y_range"), default_min=min(0.0, min(y_values)) - 1, default_max=max(y_values) + 1)
        canvas = _build_graph_canvas(x_range, y_range, "2直線とy軸")

        p_top = canvas["to_svg"](0.0, first["intercept"])
        p_bottom = canvas["to_svg"](0.0, second["intercept"])
        p_cross = canvas["to_svg"](x_cross, y_cross)
        triangle = (
            f'<polygon points="{p_top[0]},{p_top[1]} {p_bottom[0]},{p_bottom[1]} {p_cross[0]},{p_cross[1]}" '
            'fill="rgba(14,165,233,0.10)" stroke="#7dd3fc" stroke-width="1.5" />'
        )
        lines = [
            _build_line_segment(canvas["to_svg"], first, x_range, "#2563eb"),
            _build_line_segment(canvas["to_svg"], second, x_range, "#7c3aed"),
        ]
        points = _build_point_parts(
            canvas["to_svg"],
            [
                {"x": 0.0, "y": first["intercept"], "label": "A"},
                {"x": 0.0, "y": second["intercept"], "label": "B"},
                {"x": x_cross, "y": y_cross, "label": "P"},
            ],
        )
        return _assemble_svg(canvas, triangle + "".join(lines) + points)
    except Exception:
        return None


def render_circle_inscribed_angle_svg(diagram_params: dict) -> str | None:
    try:
        points_data = diagram_params.get("points")
        if not isinstance(points_data, list) or len(points_data) < 3:
            return None

        points_by_name: dict[str, tuple[float, float]] = {}
        center_x = SVG_SIZE / 2
        center_y = SVG_SIZE / 2
        radius = 108

        for item in points_data:
            name = str(item.get("name", "")).strip()
            angle_deg = item.get("angle_deg")
            if not name or angle_deg is None:
                continue
            theta = math.radians(float(angle_deg))
            x = center_x + radius * math.cos(theta)
            y = center_y - radius * math.sin(theta)
            points_by_name[name] = (round(x, 2), round(y, 2))

        if len(points_by_name) < 3:
            return None

        center_label_value = str(diagram_params.get("circle", {}).get("center_label", "O")).strip() or "O"
        points_by_name[center_label_value] = (center_x, center_y)
        if center_label_value != "O":
            points_by_name["O"] = (center_x, center_y)

        parts: list[str] = [
            '<rect x="0" y="0" width="320" height="320" rx="18" fill="#ffffff" />',
            '<rect x="1" y="1" width="318" height="318" rx="17" fill="none" stroke="#e5e7eb" />',
            '<text x="20" y="24" font-size="13" font-weight="700" fill="#1f2937">円周角</text>',
            f'<circle cx="{center_x}" cy="{center_y}" r="{radius}" fill="none" stroke="#94a3b8" stroke-width="2" />',
        ]

        if diagram_params.get("show_center"):
            center_label = escape(center_label_value)
            center_label_dx = float(diagram_params.get("circle", {}).get("center_label_dx", 8))
            center_label_dy = float(diagram_params.get("circle", {}).get("center_label_dy", -8))
            parts.append(f'<circle cx="{center_x}" cy="{center_y}" r="3.5" fill="#475569" />')
            parts.append(f'<text x="{center_x + center_label_dx}" y="{center_y + center_label_dy}" font-size="12" font-weight="700" fill="#334155">{center_label}</text>')

        for segment in diagram_params.get("segments", []):
            if not isinstance(segment, list) or len(segment) != 2:
                continue
            p1 = points_by_name.get(str(segment[0]))
            p2 = points_by_name.get(str(segment[1]))
            if p1 and p2:
                parts.append(
                    f'<line x1="{p1[0]}" y1="{p1[1]}" x2="{p2[0]}" y2="{p2[1]}" stroke="#2563eb" stroke-width="2.5" />'
                )

        for mark in diagram_params.get("angle_marks", []):
            arc = _build_angle_mark(points_by_name, mark)
            if arc:
                parts.append(arc)

        point_label_offsets = {
            str(item.get("name")): (
                float(item.get("label_dx", 8)),
                float(item.get("label_dy", -8)),
            )
            for item in points_data
            if isinstance(item, dict) and item.get("name")
        }

        for name, (x, y) in points_by_name.items():
            parts.append(f'<circle cx="{x}" cy="{y}" r="4.8" fill="#f97316" stroke="#ffffff" stroke-width="1.5" />')
            label_dx, label_dy = point_label_offsets.get(name, (8.0, -8.0))
            parts.append(f'<text x="{x + label_dx}" y="{y + label_dy}" font-size="12" font-weight="700" fill="#9a3412">{escape(name)}</text>')

        return (
            f'<svg class="problem-diagram-svg" viewBox="0 0 {SVG_SIZE} {SVG_SIZE}" '
            f'width="{SVG_SIZE}" height="{SVG_SIZE}" role="img" aria-label="円周角の図">'
            f'{"".join(parts)}'
            "</svg>"
        )
    except Exception:
        return None


def render_parallel_lines_angle_svg(diagram_params: dict) -> str | None:
    try:
        spec = parse_parallel_lines_angle_spec(diagram_params, svg_size=SVG_SIZE)
        if spec is None:
            return None
        geometry = build_parallel_lines_angle_geometry(spec, width=SVG_SIZE, height=SVG_SIZE)
        if geometry is None:
            return None
        layout = resolve_parallel_lines_angle_layout(geometry)
        return render_parallel_lines_angle_geometry_svg(geometry, layout)
    except Exception:
        return None


def render_triangle_correspondence_svg(diagram_params: dict) -> str | None:
    try:
        triangles = diagram_params.get("triangles")
        if not isinstance(triangles, list) or len(triangles) < 2:
            return None

        triangle_defs = []
        points_by_name: dict[str, tuple[float, float]] = {}
        point_label_defs: dict[str, dict] = {}
        for triangle in triangles[:2]:
            points = triangle.get("points")
            if not isinstance(points, list) or len(points) < 3:
                return None
            tri_points = []
            for point in points[:3]:
                name = str(point.get("name") or "").strip()
                x = point.get("x")
                y = point.get("y")
                if not name or x is None or y is None:
                    return None
                coord = (float(x), float(y))
                tri_points.append((name, coord))
                points_by_name[name] = coord
                point_label_defs[name] = point
            triangle_defs.append(tri_points)

        if len(points_by_name) < 6:
            return None

        parts: list[str] = [
            '<rect x="0" y="0" width="520" height="320" rx="18" fill="#ffffff" />',
            '<rect x="1" y="1" width="518" height="318" rx="17" fill="none" stroke="#e5e7eb" />',
            '<text x="20" y="24" font-size="13" font-weight="700" fill="#1f2937">三角形の対応</text>',
        ]

        for tri_points in triangle_defs:
            polygon = " ".join(f"{x:.2f},{y:.2f}" for _, (x, y) in tri_points)
            parts.append(
                f'<polygon points="{polygon}" fill="rgba(37,99,235,0.06)" stroke="#2563eb" stroke-width="2.5" />'
            )

        for tri_points in triangle_defs:
            for name, (x, y) in tri_points:
                parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.4" fill="#f97316" stroke="#ffffff" stroke-width="1.5" />')
                point_def = point_label_defs.get(name, {})
                label_dx = float(point_def.get("label_dx", 8))
                label_dy = float(point_def.get("label_dy", -8))
                parts.append(
                    f'<text x="{x + label_dx:.2f}" y="{y + label_dy:.2f}" font-size="12" font-weight="700" fill="#9a3412">{escape(name)}</text>'
                )

        for index, side_group in enumerate(diagram_params.get("equal_sides", []), start=1):
            side_svg = _build_equal_side_marks(points_by_name, side_group, index)
            if side_svg:
                parts.append(side_svg)

        for index, angle_group in enumerate(diagram_params.get("equal_angles", []), start=1):
            angle_svg = _build_equal_angle_marks(points_by_name, angle_group, index)
            if angle_svg:
                parts.append(angle_svg)

        for pair in diagram_params.get("highlight_pairs", []):
            if not isinstance(pair, list) or len(pair) != 2:
                continue
            p1 = points_by_name.get(str(pair[0]))
            p2 = points_by_name.get(str(pair[1]))
            if p1 and p2:
                parts.append(
                    f'<line x1="{p1[0]:.2f}" y1="{p1[1]:.2f}" x2="{p2[0]:.2f}" y2="{p2[1]:.2f}" '
                    'stroke="#94a3b8" stroke-width="1.2" stroke-dasharray="4 4" />'
                )

        return (
            '<svg class="problem-diagram-svg" viewBox="0 0 520 320" width="520" height="320" '
            'role="img" aria-label="三角形の対応関係の図">'
            f'{"".join(parts)}'
            '</svg>'
        )
    except Exception:
        return None


def render_similar_triangles_basic_svg(diagram_params: dict) -> str | None:
    try:
        triangles = diagram_params.get("triangles")
        if not isinstance(triangles, list) or len(triangles) < 2:
            return None

        triangle_defs = []
        points_by_name: dict[str, tuple[float, float]] = {}
        point_label_defs: dict[str, dict] = {}
        for triangle in triangles[:2]:
            points = triangle.get("points")
            if not isinstance(points, list) or len(points) < 3:
                return None
            tri_points = []
            for point in points[:3]:
                name = str(point.get("name") or "").strip()
                x = point.get("x")
                y = point.get("y")
                if not name or x is None or y is None:
                    return None
                coord = (float(x), float(y))
                tri_points.append((name, coord))
                points_by_name[name] = coord
                point_label_defs[name] = point
            triangle_defs.append(tri_points)

        if len(points_by_name) < 6:
            return None

        parts: list[str] = [
            '<rect x="0" y="0" width="520" height="320" rx="18" fill="#ffffff" />',
            '<rect x="1" y="1" width="518" height="318" rx="17" fill="none" stroke="#e5e7eb" />',
            '<text x="20" y="24" font-size="13" font-weight="700" fill="#1f2937">相似な三角形</text>',
        ]

        for tri_points in triangle_defs:
            polygon = " ".join(f"{x:.2f},{y:.2f}" for _, (x, y) in tri_points)
            parts.append(
                f'<polygon points="{polygon}" fill="rgba(14,165,233,0.06)" stroke="#0284c7" stroke-width="2.5" />'
            )

        for tri_points in triangle_defs:
            for name, (x, y) in tri_points:
                parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.4" fill="#f97316" stroke="#ffffff" stroke-width="1.5" />')
                point_def = point_label_defs.get(name, {})
                label_dx = float(point_def.get("label_dx", 8))
                label_dy = float(point_def.get("label_dy", -8))
                parts.append(
                    f'<text x="{x + label_dx:.2f}" y="{y + label_dy:.2f}" font-size="12" font-weight="700" fill="#9a3412">{escape(name)}</text>'
                )

        for index, angle_group in enumerate(diagram_params.get("equal_angles", []), start=1):
            angle_svg = _build_equal_angle_marks(points_by_name, angle_group, index)
            if angle_svg:
                parts.append(angle_svg)

        for pair in diagram_params.get("highlight_pairs", []):
            if not isinstance(pair, list) or len(pair) != 2:
                continue
            p1 = points_by_name.get(str(pair[0]))
            p2 = points_by_name.get(str(pair[1]))
            if p1 and p2:
                parts.append(
                    f'<line x1="{p1[0]:.2f}" y1="{p1[1]:.2f}" x2="{p2[0]:.2f}" y2="{p2[1]:.2f}" '
                    'stroke="#94a3b8" stroke-width="1.2" stroke-dasharray="4 4" />'
                )

        for index, mark_group in enumerate(diagram_params.get("parallel_marks", []), start=1):
            mark_svg = _build_parallel_marks(points_by_name, mark_group, index)
            if mark_svg:
                parts.append(mark_svg)

        for label in diagram_params.get("side_labels", []):
            label_svg = _build_side_label(points_by_name, label)
            if label_svg:
                parts.append(label_svg)

        return (
            '<svg class="problem-diagram-svg" viewBox="0 0 520 320" width="520" height="320" '
            'role="img" aria-label="相似な三角形の図">'
            f'{"".join(parts)}'
            '</svg>'
        )
    except Exception:
        return None


def _normalize_linear_function_params(diagram_params: dict) -> dict | None:
    line = diagram_params.get("line")
    points = diagram_params.get("points")
    x_range = diagram_params.get("x_range")
    y_range = diagram_params.get("y_range")

    if isinstance(line, dict) and points and x_range and y_range:
        try:
            return {
                "line": {
                    "slope": float(line["slope"]),
                    "intercept": float(line["intercept"]),
                },
                "points": [_normalize_point(point) for point in points if _normalize_point(point) is not None],
                "x_range": _normalize_range(x_range),
                "y_range": _normalize_range(y_range),
            }
        except Exception:
            return None

    equation = diagram_params.get("equation")
    if isinstance(equation, str):
        line_data = _parse_linear_equation(equation)
        if line_data is None:
            return None

        normalized_points: list[dict] = []
        point_x = diagram_params.get("point_x")
        if point_x is not None:
            x_value = float(point_x)
            normalized_points.append(
                {"x": x_value, "y": line_data["slope"] * x_value + line_data["intercept"], "label": "P"}
            )
            normalized_points.append({"x": x_value, "y": 0.0, "label": "Q"})
        else:
            normalized_points.extend(_default_points_for_line(line_data["slope"], line_data["intercept"]))

        x_values = [point["x"] for point in normalized_points] or [0.0, 1.0]
        y_values = [point["y"] for point in normalized_points] or [line_data["intercept"], line_data["slope"] + line_data["intercept"]]

        return {
            "line": line_data,
            "points": normalized_points[:2],
            "x_range": _normalize_range(diagram_params.get("x_range"), default_min=min(-2.0, min(x_values) - 1), default_max=max(4.0, max(x_values) + 1)),
            "y_range": _normalize_range(diagram_params.get("y_range"), default_min=min(-2.0, min(y_values) - 1), default_max=max(6.0, max(y_values) + 1)),
        }

    return None


def _default_points_for_line(slope: float, intercept: float) -> list[dict]:
    points = [{"x": 0.0, "y": intercept, "label": "A"}]
    second_x = 1.0
    points.append({"x": second_x, "y": slope * second_x + intercept, "label": "B"})
    return points


def _build_angle_mark(points_by_name: dict[str, tuple[float, float]], mark: dict) -> str | None:
    try:
        vertex_name = str(mark.get("vertex"))
        from_name = str(mark.get("from"))
        to_name = str(mark.get("to"))
        label = mark.get("label")
        vertex = points_by_name.get(vertex_name)
        point_from = points_by_name.get(from_name)
        point_to = points_by_name.get(to_name)
        if not (vertex and point_from and point_to):
            return None

        vx, vy = vertex
        ux1, uy1 = _unit_vector(vertex, point_from)
        ux2, uy2 = _unit_vector(vertex, point_to)
        radius = float(mark.get("radius", 22))
        start = (vx + ux1 * radius, vy + uy1 * radius)
        end = (vx + ux2 * radius, vy + uy2 * radius)
        cross = ux1 * uy2 - uy1 * ux2
        sweep = 0 if cross < 0 else 1
        arc = (
            f'<path class="angle-arc" d="M {start[0]:.2f} {start[1]:.2f} A {radius:.2f} {radius:.2f} 0 0 {sweep} {end[0]:.2f} {end[1]:.2f}" '
            'fill="none" stroke="#16a34a" stroke-width="2" />'
        )
        if not label:
            return arc
        label_x, label_y = _compute_angle_label_position(
            (vx, vy),
            (ux1, uy1),
            (ux2, uy2),
            radius,
            float(mark.get("label_dx", 0)),
            float(mark.get("label_dy", 0)),
            float(mark.get("label_distance", max(radius * 0.72, 14))),
        )
        return arc + (
            f'<text class="angle-label" x="{label_x:.2f}" y="{label_y:.2f}" text-anchor="middle" '
            'dominant-baseline="middle" font-size="12" font-weight="700" fill="#166534" '
            'stroke="#ffffff" stroke-width="3" paint-order="stroke fill">'
            f'{escape(str(label))}</text>'
        )
    except Exception:
        return None


def _build_polar_angle_mark(mark: dict) -> str | None:
    try:
        vertex = mark.get("vertex")
        if not isinstance(vertex, dict):
            return None
        vx = float(vertex["x"])
        vy = float(vertex["y"])
        from_deg, to_deg = _normalize_small_arc_deg(float(mark["from_deg"]), float(mark["to_deg"]))
        label = mark.get("label")
        radius = float(mark.get("radius", 24))

        start_x = vx + radius * math.cos(math.radians(from_deg))
        start_y = vy - radius * math.sin(math.radians(from_deg))
        end_x = vx + radius * math.cos(math.radians(to_deg))
        end_y = vy - radius * math.sin(math.radians(to_deg))
        delta = (to_deg - from_deg) % 360
        large_arc = 1 if delta > 180 else 0
        sweep = 1
        arc = (
            f'<path class="angle-arc" d="M {start_x:.2f} {start_y:.2f} A {radius:.2f} {radius:.2f} 0 {large_arc} {sweep} {end_x:.2f} {end_y:.2f}" '
            'fill="none" stroke="#16a34a" stroke-width="2" />'
        )
        if not label:
            return arc

        mid_deg = _normalize_angle_deg(from_deg + delta / 2)
        label_distance = float(mark.get("label_distance", radius + 10))
        lx = vx + label_distance * math.cos(math.radians(mid_deg)) + float(mark.get("label_dx", 0))
        ly = vy - label_distance * math.sin(math.radians(mid_deg)) + float(mark.get("label_dy", 0))
        return arc + (
            f'<text class="angle-label" x="{lx:.2f}" y="{ly:.2f}" text-anchor="middle" '
            'dominant-baseline="middle" font-size="12" font-weight="700" fill="#166534" '
            'stroke="#ffffff" stroke-width="3" paint-order="stroke fill">'
            f'{escape(str(label))}</text>'
        )
    except Exception:
        return None


def _build_equal_side_marks(points_by_name: dict[str, tuple[float, float]], side_group: list, group_index: int) -> str | None:
    try:
        if not isinstance(side_group, list) or len(side_group) != 4:
            return None
        pairs = [
            (points_by_name.get(str(side_group[0])), points_by_name.get(str(side_group[1]))),
            (points_by_name.get(str(side_group[2])), points_by_name.get(str(side_group[3]))),
        ]
        tick_count = min(group_index, 3)
        parts: list[str] = []
        for p1, p2 in pairs:
            if not (p1 and p2):
                continue
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            length = math.hypot(dx, dy) or 1.0
            nx = -dy / length
            ny = dx / length
            mx = (p1[0] + p2[0]) / 2
            my = (p1[1] + p2[1]) / 2
            for offset_index in range(tick_count):
                shift = (offset_index - (tick_count - 1) / 2) * 8
                cx = mx + (dx / length) * shift
                cy = my + (dy / length) * shift
                x1 = cx - nx * 8
                y1 = cy - ny * 8
                x2 = cx + nx * 8
                y2 = cy + ny * 8
                parts.append(
                    f'<line class="equal-side-mark" x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="#0f766e" stroke-width="2" />'
                )
        return "".join(parts) or None
    except Exception:
        return None


def _build_equal_angle_marks(points_by_name: dict[str, tuple[float, float]], angle_group: list, group_index: int) -> str | None:
    try:
        if not isinstance(angle_group, list) or len(angle_group) != 2:
            return None
        mark_count = min(group_index, 2)
        parts: list[str] = []
        for vertex_name in angle_group:
            vertex = points_by_name.get(str(vertex_name))
            if not vertex:
                continue
            connected = _sorted_neighbor_points(points_by_name, str(vertex_name))
            if len(connected) < 2:
                continue
            point_from, point_to = connected[0], connected[-1]
            for offset_index in range(mark_count):
                mark = _build_angle_mark(
                    points_by_name,
                    {
                        "vertex": str(vertex_name),
                        "from": point_from,
                        "to": point_to,
                        "radius": 18 + offset_index * 6,
                    },
                )
                if mark:
                    parts.append(mark.replace('stroke="#16a34a"', 'stroke="#7c3aed"'))
        return "".join(parts) or None
    except Exception:
        return None


def _build_parallel_marks(points_by_name: dict[str, tuple[float, float]], mark_group: list, group_index: int) -> str | None:
    try:
        if not isinstance(mark_group, list) or len(mark_group) != 4:
            return None
        pairs = [
            (points_by_name.get(str(mark_group[0])), points_by_name.get(str(mark_group[1]))),
            (points_by_name.get(str(mark_group[2])), points_by_name.get(str(mark_group[3]))),
        ]
        mark_count = max(2, min(group_index + 1, 3))
        parts = [_build_parallel_symbol(p1, p2, mark_count=mark_count) for p1, p2 in pairs]
        return "".join(part for part in parts if part) or None
    except Exception:
        return None


def _build_side_label(points_by_name: dict[str, tuple[float, float]], label_def: dict) -> str | None:
    try:
        if not isinstance(label_def, dict):
            return None
        p1 = points_by_name.get(str(label_def.get("from")))
        p2 = points_by_name.get(str(label_def.get("to")))
        label = label_def.get("label")
        if not (p1 and p2 and label is not None):
            return None
        mx = (p1[0] + p2[0]) / 2
        my = (p1[1] + p2[1]) / 2
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length = math.hypot(dx, dy) or 1.0
        nx = -dy / length
        ny = dx / length
        offset = float(label_def.get("offset", 16))
        lx = mx + nx * offset + float(label_def.get("dx", 0))
        ly = my + ny * offset + float(label_def.get("dy", 0))
        return (
            f'<text class="side-label" x="{lx:.2f}" y="{ly:.2f}" text-anchor="middle" dominant-baseline="middle" '
            'font-size="12" font-weight="700" fill="#0369a1" stroke="#ffffff" stroke-width="3" paint-order="stroke fill">'
            f'{escape(str(label))}</text>'
        )
    except Exception:
        return None


def _compute_angle_label_position(
    vertex: tuple[float, float],
    direction_a: tuple[float, float],
    direction_b: tuple[float, float],
    radius: float,
    dx: float,
    dy: float,
    label_distance: float,
) -> tuple[float, float]:
    vx, vy = vertex
    ax, ay = direction_a
    bx, by = direction_b
    bisector_x = ax + bx
    bisector_y = ay + by
    if math.isclose(bisector_x, 0.0) and math.isclose(bisector_y, 0.0):
        bisector_x = -ay
        bisector_y = ax
    length = math.hypot(bisector_x, bisector_y) or 1.0
    distance = max(min(label_distance, radius + 12), 10)
    return (
        vx + bisector_x / length * distance + dx,
        vy + bisector_y / length * distance + dy,
    )


def _build_parallel_symbol(
    p1: tuple[float, float] | None,
    p2: tuple[float, float] | None,
    *,
    mark_count: int = 2,
    slash_half: float = 7.0,
    lean: float = 3.0,
    separation: float = 9.0,
) -> str | None:
    if not (p1 and p2):
        return None
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    length = math.hypot(dx, dy) or 1.0
    ux = dx / length
    uy = dy / length
    nx = -uy
    ny = ux
    mx = (p1[0] + p2[0]) / 2
    my = (p1[1] + p2[1]) / 2
    parts: list[str] = []
    for offset_index in range(mark_count):
        shift = (offset_index - (mark_count - 1) / 2) * separation
        cx = mx + ux * shift
        cy = my + uy * shift
        x1 = cx - nx * slash_half - ux * lean
        y1 = cy - ny * slash_half - uy * lean
        x2 = cx + nx * slash_half + ux * lean
        y2 = cy + ny * slash_half + uy * lean
        parts.append(
            f'<line class="parallel-symbol" x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="#0f766e" stroke-width="2" />'
        )
    return "".join(parts) or None


def _sorted_neighbor_points(points_by_name: dict[str, tuple[float, float]], vertex_name: str) -> list[str]:
    vertex = points_by_name.get(vertex_name)
    if not vertex:
        return []
    vx, vy = vertex
    neighbors = []
    for name, (x, y) in points_by_name.items():
        if name == vertex_name:
            continue
        distance = math.hypot(x - vx, y - vy)
        neighbors.append((distance, name))
    neighbors.sort()
    return [name for _, name in neighbors[:2]]


def _build_graph_canvas(x_range: tuple[float, float], y_range: tuple[float, float], title: str) -> dict:
    x_min, x_max = x_range
    y_min, y_max = y_range

    def to_svg(x: float, y: float) -> tuple[float, float]:
        usable = SVG_SIZE - 2 * PADDING
        svg_x = PADDING + (x - x_min) / (x_max - x_min) * usable
        svg_y = SVG_SIZE - PADDING - (y - y_min) / (y_max - y_min) * usable
        return round(svg_x, 2), round(svg_y, 2)

    axis_parts: list[str] = []
    tick_parts: list[str] = []
    label_parts: list[str] = []

    if x_min <= 0 <= x_max:
        x1, y0 = to_svg(x_min, 0)
        x2, _ = to_svg(x_max, 0)
        axis_parts.append(
            f'<line x1="{x1}" y1="{y0}" x2="{x2}" y2="{y0}" stroke="#9ca3af" stroke-width="1.5" />'
        )
    if y_min <= 0 <= y_max:
        x0, y1 = to_svg(0, y_min)
        _, y2 = to_svg(0, y_max)
        axis_parts.append(
            f'<line x1="{x0}" y1="{y1}" x2="{x0}" y2="{y2}" stroke="#9ca3af" stroke-width="1.5" />'
        )

    for x in _build_ticks(x_min, x_max):
        svg_x, svg_y = to_svg(x, 0 if y_min <= 0 <= y_max else y_min)
        tick_parts.append(
            f'<line x1="{svg_x}" y1="{svg_y - 4}" x2="{svg_x}" y2="{svg_y + 4}" stroke="#cbd5e1" stroke-width="1" />'
        )
        label_parts.append(
            f'<text x="{svg_x}" y="{SVG_SIZE - 10}" text-anchor="middle" font-size="11" fill="#6b7280">{_format_number(x)}</text>'
        )

    for y in _build_ticks(y_min, y_max):
        svg_x, svg_y = to_svg(0 if x_min <= 0 <= x_max else x_min, y)
        tick_parts.append(
            f'<line x1="{svg_x - 4}" y1="{svg_y}" x2="{svg_x + 4}" y2="{svg_y}" stroke="#cbd5e1" stroke-width="1" />'
        )
        label_parts.append(
            f'<text x="12" y="{svg_y + 4}" text-anchor="start" font-size="11" fill="#6b7280">{_format_number(y)}</text>'
        )

    return {
        "x_range": x_range,
        "y_range": y_range,
        "to_svg": to_svg,
        "axis_parts": axis_parts,
        "tick_parts": tick_parts,
        "label_parts": label_parts,
        "title": escape(title),
    }


def _assemble_svg(canvas: dict, content: str) -> str:
    return (
        f'<svg class="problem-diagram-svg" viewBox="0 0 {SVG_SIZE} {SVG_SIZE}" '
        f'width="{SVG_SIZE}" height="{SVG_SIZE}" role="img" aria-label="一次関数のグラフ">'
        '<rect x="0" y="0" width="320" height="320" rx="18" fill="#ffffff" />'
        '<rect x="1" y="1" width="318" height="318" rx="17" fill="none" stroke="#e5e7eb" />'
        '<text x="20" y="24" font-size="13" font-weight="700" fill="#1f2937">グラフ</text>'
        f'<text x="300" y="24" text-anchor="end" font-size="12" fill="#2563eb">{canvas["title"]}</text>'
        f'{"".join(canvas["axis_parts"])}'
        f'{"".join(canvas["tick_parts"])}'
        f'{content}'
        f'{"".join(canvas["label_parts"])}'
        "</svg>"
    )


def _build_line_segment(to_svg, line: dict, x_range: tuple[float, float], color: str) -> str:
    x_min, x_max = x_range
    y_left = line["slope"] * x_min + line["intercept"]
    y_right = line["slope"] * x_max + line["intercept"]
    left = to_svg(x_min, y_left)
    right = to_svg(x_max, y_right)
    return f'<line x1="{left[0]}" y1="{left[1]}" x2="{right[0]}" y2="{right[1]}" stroke="{color}" stroke-width="3" />'


def _build_point_parts(to_svg, points: list[dict]) -> str:
    parts: list[str] = []
    for point in points[:3]:
        svg_x, svg_y = to_svg(point["x"], point["y"])
        parts.append(
            f'<circle cx="{svg_x}" cy="{svg_y}" r="5" fill="#f97316" stroke="#ffffff" stroke-width="1.5" />'
        )
        label = escape(str(point.get("label") or ""))
        if label:
            parts.append(
                f'<text x="{svg_x + 8}" y="{svg_y - 8}" font-size="12" font-weight="700" fill="#9a3412">{label}</text>'
            )
    return "".join(parts)


def _parse_linear_equation(equation: str) -> dict | None:
    compact = equation.replace(" ", "")

    y_form = re.fullmatch(r"y=([+-]?\d*(?:\.\d+)?)x([+-]\d+(?:\.\d+)?)?", compact)
    if y_form:
        slope_str, intercept_str = y_form.groups()
        slope = _parse_coeff(slope_str)
        intercept = float(intercept_str) if intercept_str else 0.0
        return {"slope": slope, "intercept": intercept}

    standard = re.fullmatch(r"([+-]?\d*(?:\.\d+)?)x([+-]\d*(?:\.\d+)?)y=([+-]?\d+(?:\.\d+)?)", compact)
    if standard:
        a_str, b_str, c_str = standard.groups()
        a = _parse_coeff(a_str)
        b = _parse_coeff(b_str)
        c = float(c_str)
        if math.isclose(b, 0.0):
            return None
        return {"slope": -a / b, "intercept": c / b}

    return None


def _parse_coeff(value: str | None) -> float:
    if value in (None, "", "+"):
        return 1.0
    if value == "-":
        return -1.0
    return float(value)


def _normalize_point(point: dict) -> dict | None:
    try:
        return {
            "x": float(point["x"]),
            "y": float(point["y"]),
            "label": str(point.get("label", "")),
        }
    except Exception:
        return None


def _normalize_range(value, default_min: float | None = None, default_max: float | None = None) -> tuple[float, float]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        minimum = float(value[0])
        maximum = float(value[1])
    elif default_min is not None and default_max is not None:
        minimum = default_min
        maximum = default_max
    else:
        raise ValueError("invalid range")

    if math.isclose(minimum, maximum):
        maximum = minimum + 1.0
    if minimum > maximum:
        minimum, maximum = maximum, minimum
    return minimum, maximum


def _build_ticks(minimum: float, maximum: float) -> list[int]:
    start = math.ceil(minimum)
    end = math.floor(maximum)
    if end < start:
        return []
    span = end - start
    if span <= 8:
        step = 1
    elif span <= 16:
        step = 2
    else:
        step = max(1, math.ceil(span / 8))
    ticks = []
    value = start
    while value <= end:
        ticks.append(value)
        value += step
    return ticks


def _unit_vector(origin: tuple[float, float], target: tuple[float, float]) -> tuple[float, float]:
    dx = target[0] - origin[0]
    dy = target[1] - origin[1]
    length = math.hypot(dx, dy) or 1.0
    return dx / length, dy / length


def _format_number(value: float) -> str:
    if math.isclose(value, round(value)):
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _normalize_diagram_params(raw_params):
    if isinstance(raw_params, dict):
        return raw_params
    if isinstance(raw_params, str) and raw_params.strip():
        try:
            return json.loads(raw_params)
        except json.JSONDecodeError:
            return None
    return None


def _get_problem_attr(problem: dict | object, key: str, default=None):
    if isinstance(problem, dict):
        return problem.get(key, default)
    return getattr(problem, key, default)

from . import diagram_semantic_overrides as _diagram_semantic_overrides
build_problem_diagram_svg = _diagram_semantic_overrides.build_problem_diagram_svg
render_linear_function_graph_svg = _diagram_semantic_overrides.render_linear_function_graph_svg
render_line_axes_triangle_svg = _diagram_semantic_overrides.render_line_axes_triangle_svg
render_two_lines_and_y_axis_svg = _diagram_semantic_overrides.render_two_lines_and_y_axis_svg
render_circle_inscribed_angle_svg = _diagram_semantic_overrides.render_circle_inscribed_angle_svg
render_triangle_correspondence_svg = _diagram_semantic_overrides.render_triangle_correspondence_svg
render_similar_triangles_basic_svg = _diagram_semantic_overrides.render_similar_triangles_basic_svg



def _normalize_render_signature(svg: str | None) -> str:
    if not svg:
        return "none"
    if 'data-diagram-semantic="incomplete"' in svg:
        return "fallback_notice"
    if 'data-diagram-subtype="triangle_projection_to_x_axis"' in svg:
        return "triangle_projection_to_x_axis"
    if 'data-similarity-subtype="crossing_segments"' in svg:
        return "similarity_crossing_segments"
    if 'data-diagram-family="circles_angles"' in svg:
        return "circles_angles"
    if 'data-diagram-family="linear_function"' in svg:
        return "linear_function"
    if 'data-diagram-family="geometry_similarity"' in svg:
        return "geometry_similarity"
    return "generic_svg"


def render_problem_diagram_for_route(problem: dict | object, route_name: str) -> str | None:
    raw_params = _get_problem_attr(problem, "diagram_params")
    diagram_params = _normalize_diagram_params(raw_params)
    diagram_type = None
    if isinstance(diagram_params, dict):
        diagram_type = diagram_params.get("diagram_type") or diagram_params.get("type")

    svg = build_problem_diagram_svg(problem)
    problem_id = _get_problem_attr(problem, "problem_id")
    full_unit_id = _get_problem_attr(problem, "full_unit_id")
    unit_id = _get_problem_attr(problem, "unit")

    detected_subtype = ""
    semantic_override_applied = False
    fallback_used = False
    if svg:
        if 'data-diagram-subtype="' in svg:
            detected_subtype = svg.split('data-diagram-subtype="', 1)[1].split('"', 1)[0]
        elif 'data-similarity-subtype="' in svg:
            detected_subtype = svg.split('data-similarity-subtype="', 1)[1].split('"', 1)[0]
        semantic_override_applied = any(
            marker in svg
            for marker in (
                'data-diagram-subtype="triangle_projection_to_x_axis"',
                'data-similarity-subtype="crossing_segments"',
                'data-diagram-family="circles_angles"',
                'class="projection-line"',
                'class="radius-ob"',
                'class="cross-line"',
                'data-diagram-family="geometry_parallel_congruence"',
                'data-congruence-subtype="',
            )
        )
        fallback_used = 'data-diagram-semantic="incomplete"' in svg

    print(
        "[DIAGRAM_RENDER_PATH] "
        f"problem_id={problem_id} route_name={route_name} diagram_type={diagram_type or ''} "
        f"renderer_entry=diagram_service.render_problem_diagram_for_route "
        f"semantic_override_applied={str(semantic_override_applied).lower()} "
        f"detected_subtype={detected_subtype} fallback_used={str(fallback_used).lower()} "
        f"unit_id={unit_id or full_unit_id or ''}"
    )
    contains_p = '>P<' in (svg or '')
    contains_q = '>Q<' in (svg or '')
    contains_o = '>O<' in (svg or '') or '>0<' in (svg or '')
    contains_projection_line = 'class="projection-line"' in (svg or '')
    contains_triangle_poq = 'class="triangle-poq"' in (svg or '')
    print(
        "[DIAGRAM_RENDER_RESULT] "
        f"problem_id={problem_id} final_svg_signature={_normalize_render_signature(svg)} "
        f"contains_P={str(contains_p).lower()} "
        f"contains_Q={str(contains_q).lower()} "
        f"contains_O={str(contains_o).lower()} "
        f"contains_projection_line={str(contains_projection_line).lower()} "
        f"contains_triangle_POQ={str(contains_triangle_poq).lower()}"
    )
    return svg
