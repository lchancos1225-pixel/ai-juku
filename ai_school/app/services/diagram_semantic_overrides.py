from html import escape
import math
import re

from . import diagram_service as legacy
from .geometry_spec_service import (
    parse_circle_inscribed_angle_spec,
    parse_triangle_correspondence_spec,
    parse_similar_triangles_spec,
)

SVG_SIZE = legacy.SVG_SIZE
PADDING = legacy.PADDING


def build_problem_diagram_svg(problem: dict | object) -> str | None:
    try:
        diagram_required = legacy._get_problem_attr(problem, "diagram_required", False)
        if not diagram_required:
            return None
        raw_params = legacy._get_problem_attr(problem, "diagram_params")
        diagram_params = legacy._normalize_diagram_params(raw_params)
        if not isinstance(diagram_params, dict):
            return None

        diagram_type = diagram_params.get("diagram_type") or diagram_params.get("type")
        full_unit_id = legacy._get_problem_attr(problem, "full_unit_id")
        unit_id = legacy._get_problem_attr(problem, "unit")
        sub_unit = legacy._get_problem_attr(problem, "sub_unit")

        svg = None
        family = diagram_type or full_unit_id or "unknown"
        subtype = None

        if diagram_type == "parallel_lines_angle":
            svg = legacy.render_parallel_lines_angle_svg(diagram_params)
            subtype = "parallel_angle_reasoning"
        elif diagram_type == "triangle_correspondence":
            svg = render_triangle_correspondence_svg(diagram_params)
            subtype = infer_triangle_correspondence_subtype(diagram_params)
        elif diagram_type == "similar_triangles_basic":
            svg = render_similar_triangles_basic_svg(diagram_params)
            family = "geometry_similarity"
            subtype = infer_similarity_subtype(diagram_params)
        else:
            is_linear_graph = (
                diagram_type == "linear_function_graph"
                or full_unit_id == "linear_function_graph"
                or (unit_id == "linear_function" and sub_unit == "graph")
            )
            if is_linear_graph:
                family = "linear_function"
                if diagram_type == "line_axes_triangle":
                    svg = render_line_axes_triangle_svg(diagram_params)
                    subtype = "line_axes_triangle"
                elif diagram_type == "two_lines_and_y_axis":
                    svg = render_two_lines_and_y_axis_svg(diagram_params)
                    subtype = "two_lines_and_y_axis"
                else:
                    svg = render_linear_function_graph_svg(diagram_params)
                    subtype = "linear_function_graph"
            elif diagram_type == "circle_inscribed_angle":
                svg = render_circle_inscribed_angle_svg(diagram_params)
                family = "circles_angles"
                subtype = "circle_inscribed_angle"

        if not svg:
            return None

        attrs = {"data-diagram-family": family}
        if subtype:
            if family == "geometry_similarity":
                attrs["data-similarity-subtype"] = subtype
            else:
                attrs["data-diagram-subtype"] = subtype
        if full_unit_id == "geometry_parallel_congruence":
            attrs["data-congruence-subtype"] = classify_geometry_parallel_congruence_subtype(diagram_params)
            attrs["data-diagram-family"] = "geometry_parallel_congruence"
        return inject_svg_data_attributes(svg, attrs)
    except Exception:
        return None


def render_linear_function_graph_svg(diagram_params: dict) -> str | None:
    try:
        spec = resolve_linear_function_graph_spec(diagram_params)
        if spec is None:
            return None
        canvas = build_graph_canvas(spec["x_range"], spec["y_range"], title="?")
        line = spec["line"]
        graph_line = legacy._build_line_segment(canvas["to_svg"], line, spec["x_range"], "#2563eb")
        point_parts = build_graph_point_parts(canvas["to_svg"], spec["points"])
        eq = f'y = {legacy._format_number(line["slope"])}x ' + (f'+ {legacy._format_number(abs(line["intercept"]))}' if line["intercept"] >= 0 else f'- {legacy._format_number(abs(line["intercept"]))}')
        overlay = f'<text class="line-equation" x="{SVG_SIZE - 18}" y="24" text-anchor="end" font-size="12" fill="#2563eb">{escape(eq)}</text>'
        return assemble_graph_svg(canvas, graph_line + point_parts + overlay, "linear function graph")
    except Exception:
        return None


def render_line_axes_triangle_svg(diagram_params: dict) -> str | None:
    try:
        equation = diagram_params.get("equation")
        if not isinstance(equation, str):
            return None
        line = legacy._parse_linear_equation(equation)
        if line is None or math.isclose(line["slope"], 0.0):
            return None
        x_intercept = -line["intercept"] / line["slope"]
        y_intercept = line["intercept"]
        x_range = legacy._normalize_range(diagram_params.get("x_range"), default_min=min(0.0, x_intercept) - 1, default_max=max(4.0, x_intercept) + 1)
        y_range = legacy._normalize_range(diagram_params.get("y_range"), default_min=min(0.0, y_intercept) - 1, default_max=max(4.0, y_intercept) + 1)
        canvas = build_graph_canvas(x_range, y_range, title="Line and Axes")
        p_origin = canvas["to_svg"](0.0, 0.0)
        p_y = canvas["to_svg"](0.0, y_intercept)
        p_x = canvas["to_svg"](x_intercept, 0.0)
        polygon = f'<polygon points="{p_origin[0]},{p_origin[1]} {p_y[0]},{p_y[1]} {p_x[0]},{p_x[1]}" fill="rgba(37,99,235,0.10)" stroke="#93c5fd" stroke-width="1.5" />'
        graph_line = legacy._build_line_segment(canvas["to_svg"], line, x_range, "#2563eb")
        points = build_graph_point_parts(canvas["to_svg"], [{"x": 0.0, "y": y_intercept, "label": "A"}, {"x": x_intercept, "y": 0.0, "label": "B"}])
        return assemble_graph_svg(canvas, polygon + graph_line + points, "line axes triangle")
    except Exception:
        return None


def render_two_lines_and_y_axis_svg(diagram_params: dict) -> str | None:
    try:
        equations = diagram_params.get("equations")
        if not isinstance(equations, list) or len(equations) != 2:
            return None
        first = legacy._parse_linear_equation(equations[0]) if isinstance(equations[0], str) else None
        second = legacy._parse_linear_equation(equations[1]) if isinstance(equations[1], str) else None
        if first is None or second is None or math.isclose(first["slope"], second["slope"]):
            return None
        x_cross = (second["intercept"] - first["intercept"]) / (first["slope"] - second["slope"])
        y_cross = first["slope"] * x_cross + first["intercept"]
        x_range = legacy._normalize_range(diagram_params.get("x_range"), default_min=min(0.0, x_cross) - 1, default_max=max(4.0, x_cross) + 1)
        y_values = [first["intercept"], second["intercept"], y_cross]
        y_range = legacy._normalize_range(diagram_params.get("y_range"), default_min=min(0.0, min(y_values)) - 1, default_max=max(y_values) + 1)
        canvas = build_graph_canvas(x_range, y_range, title="Two Lines")
        p_top = canvas["to_svg"](0.0, first["intercept"])
        p_bottom = canvas["to_svg"](0.0, second["intercept"])
        p_cross = canvas["to_svg"](x_cross, y_cross)
        triangle = f'<polygon points="{p_top[0]},{p_top[1]} {p_bottom[0]},{p_bottom[1]} {p_cross[0]},{p_cross[1]}" fill="rgba(14,165,233,0.08)" stroke="#7dd3fc" stroke-width="1.5" />'
        lines = legacy._build_line_segment(canvas["to_svg"], first, x_range, "#2563eb") + legacy._build_line_segment(canvas["to_svg"], second, x_range, "#7c3aed")
        points = build_graph_point_parts(canvas["to_svg"], [{"x": 0.0, "y": first["intercept"], "label": "A"}, {"x": 0.0, "y": second["intercept"], "label": "B"}, {"x": x_cross, "y": y_cross, "label": "P"}])
        return assemble_graph_svg(canvas, triangle + lines + points, "two lines and y axis")
    except Exception:
        return None

def render_circle_inscribed_angle_svg(diagram_params: dict) -> str | None:
    """円と角の問題を spec ベースで描画する（新パイプライン）。"""
    try:
        spec = parse_circle_inscribed_angle_spec(diagram_params)
        if spec is None:
            return None
        center_x, center_y = spec.center
        all_points = dict(spec.points)
        all_points[spec.center_label] = (center_x, center_y)
        parts = [
            f'<rect x="0" y="0" width="{SVG_SIZE}" height="{SVG_SIZE}" rx="18" fill="#ffffff" />',
            f'<rect x="1" y="1" width="{SVG_SIZE - 2}" height="{SVG_SIZE - 2}" rx="17" fill="none" stroke="#e5e7eb" />',
            '<text x="20" y="24" font-size="13" font-weight="700" fill="#1f2937">?</text>',
            f'<circle cx="{center_x:.2f}" cy="{center_y:.2f}" r="{spec.radius:.1f}" fill="none" stroke="#94a3b8" stroke-width="2" />',
        ]
        # 線分
        for p1_name, p2_name in spec.segments:
            p1 = spec.points.get(p1_name) or all_points.get(p1_name)
            p2 = spec.points.get(p2_name) or all_points.get(p2_name)
            if p1 and p2:
                parts.append(
                    f'<line class="diagram-segment" x1="{p1[0]:.2f}" y1="{p1[1]:.2f}" '
                    f'x2="{p2[0]:.2f}" y2="{p2[1]:.2f}" stroke="#2563eb" stroke-width="2.4" />'
                )
        # 角度マーク（angle_role で色分け）
        for mark in spec.angle_marks:
            label = mark.value
            arc_stroke = "#16a34a" if mark.angle_role == "given" else "#0f172a"
            label_fill = "#166534" if mark.angle_role == "given" else "#0f172a"
            svg = legacy._build_angle_mark(
                all_points,
                {"vertex": mark.vertex, "from": mark.from_point, "to": mark.to_point,
                 "label": label, "radius": mark.radius, "label_distance": mark.radius + 10,
                 "arc_stroke": arc_stroke, "label_fill": label_fill},
            )
            if svg:
                parts.append(svg)
        # 中心点
        parts.append(
            f'<circle cx="{center_x:.2f}" cy="{center_y:.2f}" r="3.5" fill="#475569" />'
        )
        parts.append(
            f'<text class="center-label" x="{center_x + 12:.2f}" y="{center_y - 12:.2f}" '
            f'font-size="12" font-weight="700" fill="#334155">{escape(spec.center_label)}</text>'
        )
        # 円周上の点
        for name, coord in spec.points.items():
            parts.extend(render_named_point(name, coord, spec.point_defs.get(name, {}), all_names=all_points))
        return (
            f'<svg class="problem-diagram-svg" data-diagram-family="circles_angles" data-diagram-subtype="circle_inscribed_angle" '
            f'viewBox="0 0 {SVG_SIZE} {SVG_SIZE}" width="{SVG_SIZE}" height="{SVG_SIZE}" role="img" aria-label="円と角">'
            f'{"".join(parts)}</svg>'
        )
    except Exception:
        return None


def render_triangle_correspondence_svg(diagram_params: dict) -> str | None:
    """合同三角形問題を spec ベースで描画する（新パイプライン）。"""
    try:
        spec = parse_triangle_correspondence_spec(diagram_params)
        if spec is None:
            return None
        if spec.subtype == "crossing_segments":
            return render_crossing_correspondence_svg(diagram_params, title="?")
        parts = [
            '<rect x="0" y="0" width="520" height="320" rx="18" fill="#ffffff" />',
            '<rect x="1" y="1" width="518" height="318" rx="17" fill="none" stroke="#e5e7eb" />',
            '<text x="20" y="24" font-size="13" font-weight="700" fill="#1f2937">?</text>',
        ]
        # 三角形の塗り・輪郭
        for tri in spec.triangles:
            polygon = " ".join(f"{p.x:.2f},{p.y:.2f}" for p in tri.points)
            parts.append(
                f'<polygon points="{polygon}" fill="rgba(37,99,235,0.06)" stroke="#2563eb" stroke-width="2.5" />'
            )
        # 点ラベル
        for tri in spec.triangles:
            for pt in tri.points:
                parts.extend(render_named_point(
                    pt.name, (pt.x, pt.y), spec.point_defs.get(pt.name, {}), all_names=spec.points,
                ))
        # 等辺マーク
        for index, side_group in enumerate(spec.equal_sides, start=1):
            # legacy は [p1, p2, p3, p4] のフラットリスト (2ペア固定) を期待
            raw_group = []
            for m in side_group:
                raw_group.extend([m.p1, m.p2])
            svg = legacy._build_equal_side_marks(spec.points, raw_group, index)
            if svg:
                parts.append(svg)
        # 等角マーク
        for index, angle_group in enumerate(spec.equal_angles, start=1):
            # legacy は [vertex1, vertex2] の頂点名のみのリストを期待
            raw_group = [m.vertex for m in angle_group]
            svg = legacy._build_equal_angle_marks(spec.points, raw_group, index)
            if svg:
                parts.append(svg)
        # ハイライトライン
        for p1_name, p2_name in spec.highlight_pairs:
            p1 = spec.points.get(p1_name)
            p2 = spec.points.get(p2_name)
            if p1 and p2:
                parts.append(
                    f'<line x1="{p1[0]:.2f}" y1="{p1[1]:.2f}" x2="{p2[0]:.2f}" y2="{p2[1]:.2f}" '
                    'stroke="#94a3b8" stroke-width="1.2" stroke-dasharray="4 4" />'
                )
        return (
            '<svg class="problem-diagram-svg" data-diagram-family="geometry_parallel_congruence" '
            f'data-diagram-subtype="{spec.subtype}" '
            'viewBox="0 0 520 320" width="520" height="320" role="img" aria-label="合同三角形">'
            + ''.join(parts) + '</svg>'
        )
    except Exception:
        return None


def render_similar_triangles_basic_svg(diagram_params: dict) -> str | None:
    """相似三角形問題を spec ベースで描画する（新パイプライン）。"""
    try:
        spec = parse_similar_triangles_spec(diagram_params)
        if spec is None:
            return None
        if spec.subtype == "parallel_cut":
            return render_similarity_parallel_cut_svg(diagram_params)
        if spec.subtype == "crossing_segments":
            return render_crossing_correspondence_svg(diagram_params, title="?")
        return render_similarity_comparison_svg(diagram_params)
    except Exception:
        return None


def render_similarity_comparison_svg(diagram_params: dict) -> str | None:
    triangle_defs, points_by_name, point_defs = parse_named_triangles(diagram_params)
    if triangle_defs is None:
        return None
    parts = [
        '<rect x="0" y="0" width="520" height="320" rx="18" fill="#ffffff" />',
        '<rect x="1" y="1" width="518" height="318" rx="17" fill="none" stroke="#e5e7eb" />',
        '<text x="20" y="24" font-size="13" font-weight="700" fill="#1f2937">?</text>',
    ]
    for tri_points in triangle_defs:
        polygon = " ".join(f"{x:.2f},{y:.2f}" for _, (x, y) in tri_points)
        parts.append(f'<polygon points="{polygon}" fill="rgba(14,165,233,0.06)" stroke="#0284c7" stroke-width="2.5" />')
    for tri_points in triangle_defs:
        for name, coord in tri_points:
            parts.extend(render_named_point(name, coord, point_defs.get(name, {}), all_names=points_by_name))
    for index, angle_group in enumerate(diagram_params.get("equal_angles", []), start=1):
        svg = legacy._build_equal_angle_marks(points_by_name, angle_group, index)
        if svg:
            parts.append(svg)
    for index, mark_group in enumerate(diagram_params.get("parallel_marks", []), start=1):
        svg = legacy._build_parallel_marks(points_by_name, mark_group, index)
        if svg:
            parts.append(svg)
    for label in diagram_params.get("side_labels", []):
        svg = legacy._build_side_label(points_by_name, label)
        if svg:
            parts.append(svg)
    return '<svg class="problem-diagram-svg" viewBox="0 0 520 320" width="520" height="320" role="img" aria-label="?">' + ''.join(parts) + '</svg>'


def render_similarity_parallel_cut_svg(diagram_params: dict) -> str | None:
    triangle_defs, _, point_defs = parse_named_triangles(diagram_params)
    if triangle_defs is None:
        return None
    merged = merge_parallel_cut_points(triangle_defs)
    if merged is None:
        return render_similarity_comparison_svg(diagram_params)
    apex_name, apex_coord, inner_points, outer_points = merged
    canonical = {apex_name: apex_coord, inner_points[0][0]: inner_points[0][1], inner_points[1][0]: inner_points[1][1], outer_points[0][0]: outer_points[0][1], outer_points[1][0]: outer_points[1][1]}
    parts = [
        '<rect x="0" y="0" width="320" height="320" rx="18" fill="#ffffff" />',
        '<rect x="1" y="1" width="318" height="318" rx="17" fill="none" stroke="#e5e7eb" />',
        '<text x="20" y="24" font-size="13" font-weight="700" fill="#1f2937">?</text>',
    ]
    outer_polygon = ' '.join(f'{x:.2f},{y:.2f}' for x, y in [apex_coord, outer_points[0][1], outer_points[1][1]])
    inner_polygon = ' '.join(f'{x:.2f},{y:.2f}' for x, y in [apex_coord, inner_points[0][1], inner_points[1][1]])
    parts.append(f'<polygon points="{outer_polygon}" fill="rgba(2,132,199,0.05)" stroke="#0284c7" stroke-width="2.5" />')
    parts.append(f'<polygon points="{inner_polygon}" fill="rgba(14,165,233,0.10)" stroke="#0ea5e9" stroke-width="2.2" />')
    parts.append(f'<line x1="{inner_points[0][1][0]:.2f}" y1="{inner_points[0][1][1]:.2f}" x2="{inner_points[1][1][0]:.2f}" y2="{inner_points[1][1][1]:.2f}" stroke="#0ea5e9" stroke-width="2.2" />')
    for name, coord in canonical.items():
        parts.extend(render_named_point(name, coord, point_defs.get(name, {}), all_names=canonical))
    for index, angle_group in enumerate(diagram_params.get("equal_angles", []), start=1):
        svg = legacy._build_equal_angle_marks(canonical, canonicalize_name_group(angle_group, canonical), index)
        if svg:
            parts.append(svg)
    for label in canonicalize_side_labels(diagram_params.get("side_labels", []), canonical):
        svg = legacy._build_side_label(canonical, label)
        if svg:
            parts.append(svg)
    for index, mark_group in enumerate(diagram_params.get("parallel_marks", []), start=1):
        svg = legacy._build_parallel_marks(canonical, canonicalize_name_group(mark_group, canonical), index)
        if svg:
            parts.append(svg)
    return '<svg class="problem-diagram-svg" viewBox="0 0 320 320" width="320" height="320" role="img" aria-label="???">' + ''.join(parts) + '</svg>'

def resolve_linear_function_graph_spec(diagram_params: dict) -> dict | None:
    normalized = legacy._normalize_linear_function_params(diagram_params)
    if normalized is None:
        return None
    normalized["axis_labels"] = {"x": "x", "y": "y", "origin": "0"}
    return normalized


def resolve_circles_angles_spec(diagram_params: dict) -> dict | None:
    points_data = diagram_params.get("points")
    if not isinstance(points_data, list) or len(points_data) < 3:
        return None
    center = (SVG_SIZE / 2, SVG_SIZE / 2)
    radius = 108
    points_by_name = {}
    point_defs = {}
    for item in points_data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        angle_deg = item.get("angle_deg")
        if not name or angle_deg is None:
            continue
        theta = math.radians(float(angle_deg))
        points_by_name[name] = (round(center[0] + radius * math.cos(theta), 2), round(center[1] - radius * math.sin(theta), 2))
        point_defs[name] = item
    if len(points_by_name) < 3:
        return None
    segments = []
    for item in diagram_params.get("segments", []):
        if isinstance(item, list) and len(item) == 2 and all(str(name) in points_by_name for name in item):
            segments.append((str(item[0]), str(item[1])))
    return {"center": center, "radius": radius, "points": points_by_name, "point_defs": point_defs, "center_label": str(diagram_params.get("circle", {}).get("center_label", "O")).strip() or "O", "segments": segments, "angle_marks": [item for item in diagram_params.get("angle_marks", []) if isinstance(item, dict)]}


def infer_similarity_subtype(diagram_params: dict) -> str:
    explicit = str(diagram_params.get("subtype") or diagram_params.get("relation_type") or "").strip()
    if explicit in {"parallel_cut", "crossing_segments", "comparison_pair"}:
        return explicit
    triangles = diagram_params.get("triangles")
    if diagram_params.get("parallel_marks"):
        return "parallel_cut"
    if has_shared_coordinate_pair(triangles):
        return "parallel_cut"
    if has_suffix_labels(triangles):
        return "crossing_segments"
    return "comparison_pair"


def infer_triangle_correspondence_subtype(diagram_params: dict) -> str:
    explicit = str(diagram_params.get("subtype") or "").strip()
    if explicit:
        return explicit
    if has_suffix_labels(diagram_params.get("triangles")):
        return "crossing_segments"
    if diagram_params.get("equal_sides") or diagram_params.get("equal_angles"):
        return "congruent_triangle_with_marks"
    return "congruent_triangle_intro"


def classify_geometry_parallel_congruence_subtype(diagram_params: dict) -> str:
    diagram_type = str(diagram_params.get("diagram_type") or "")
    if diagram_type == "parallel_lines_angle":
        return "parallel_angle_reasoning"
    if diagram_type == "triangle_correspondence":
        return infer_triangle_correspondence_subtype(diagram_params)
    return "unclassified"


def parse_named_triangles(diagram_params: dict, triangle_limit: int = 2):
    triangles = diagram_params.get("triangles")
    if not isinstance(triangles, list) or len(triangles) < triangle_limit:
        return None, None, None
    triangle_defs = []
    points_by_name = {}
    point_defs = {}
    for triangle in triangles[:triangle_limit]:
        points = triangle.get("points") if isinstance(triangle, dict) else None
        if not isinstance(points, list) or len(points) < 3:
            return None, None, None
        tri_points = []
        for point in points[:3]:
            if not isinstance(point, dict):
                return None, None, None
            name = str(point.get("name") or "").strip()
            x = point.get("x")
            y = point.get("y")
            if not name or x is None or y is None:
                return None, None, None
            coord = (float(x), float(y))
            tri_points.append((name, coord))
            points_by_name[name] = coord
            point_defs[name] = point
        triangle_defs.append(tri_points)
    return triangle_defs, points_by_name, point_defs


def render_crossing_correspondence_svg(diagram_params: dict, title: str = "Crossing Triangles") -> str | None:
    triangle_defs, _, point_defs = parse_named_triangles(diagram_params)
    if triangle_defs is None:
        return None
    first, second = triangle_defs[0], triangle_defs[1]
    if len(first) < 3 or len(second) < 3:
        return None
    a_name, a_coord = first[0]
    _, o_left = first[1]
    c_name, c_coord = first[2]
    b_name, b_coord = second[0]
    _, o_right = second[1]
    d_name, d_coord = second[2]
    center = ((o_left[0] + o_right[0]) / 2, (o_left[1] + o_right[1]) / 2)
    canonical = {a_name: a_coord, b_name: b_coord, c_name: c_coord, d_name: d_coord, "O": center}
    parts = [
        '<rect x="0" y="0" width="420" height="320" rx="18" fill="#ffffff" />',
        '<rect x="1" y="1" width="418" height="318" rx="17" fill="none" stroke="#e5e7eb" />',
        f'<text x="20" y="24" font-size="13" font-weight="700" fill="#1f2937">{escape(title)}</text>',
        f'<line x1="{a_coord[0]:.2f}" y1="{a_coord[1]:.2f}" x2="{b_coord[0]:.2f}" y2="{b_coord[1]:.2f}" stroke="#2563eb" stroke-width="2.5" />',
        f'<line x1="{c_coord[0]:.2f}" y1="{c_coord[1]:.2f}" x2="{d_coord[0]:.2f}" y2="{d_coord[1]:.2f}" stroke="#2563eb" stroke-width="2.5" />',
    ]
    for index, side_group in enumerate(diagram_params.get("equal_sides", []), start=1):
        svg = legacy._build_equal_side_marks(canonical, canonicalize_name_group(side_group, canonical), index)
        if svg:
            parts.append(svg)
    if diagram_params.get("equal_angles"):
        arc_a = legacy._build_angle_mark(canonical, {"vertex": "O", "from": a_name, "to": c_name, "radius": 18})
        arc_b = legacy._build_angle_mark(canonical, {"vertex": "O", "from": b_name, "to": d_name, "radius": 24})
        if arc_a:
            parts.append(arc_a.replace('stroke="#16a34a"', 'stroke="#7c3aed"'))
        if arc_b:
            parts.append(arc_b.replace('stroke="#16a34a"', 'stroke="#7c3aed"'))
    for label in canonicalize_side_labels(diagram_params.get("side_labels", []), canonical):
        svg = legacy._build_side_label(canonical, label)
        if svg:
            parts.append(svg)
    for name, coord in canonical.items():
        parts.extend(render_named_point(name, coord, point_defs.get(name, {}), all_names=canonical))
    return '<svg class="problem-diagram-svg" viewBox="0 0 420 320" width="420" height="320" role="img" aria-label="?">' + ''.join(parts) + '</svg>'


def merge_parallel_cut_points(triangle_defs):
    first, second = triangle_defs[0], triangle_defs[1]
    for name_a, coord_a in first:
        for name_b, coord_b in second:
            if math.hypot(coord_a[0] - coord_b[0], coord_a[1] - coord_b[1]) < 1.0:
                apex_name = preferred_label(name_a, name_b)
                inner_points = [(name, coord) for name, coord in first if name != name_a]
                outer_points = [(strip_suffix_label(name), coord) for name, coord in second if name != name_b]
                if len(inner_points) == 2 and len(outer_points) == 2:
                    return apex_name, coord_a, inner_points, outer_points
    return None


def build_graph_canvas(x_range: tuple[float, float], y_range: tuple[float, float], title: str) -> dict:
    x_min, x_max = x_range
    y_min, y_max = y_range
    def to_svg(x: float, y: float) -> tuple[float, float]:
        usable = SVG_SIZE - 2 * PADDING
        svg_x = PADDING + (x - x_min) / (x_max - x_min) * usable
        svg_y = SVG_SIZE - PADDING - (y - y_min) / (y_max - y_min) * usable
        return round(svg_x, 2), round(svg_y, 2)
    axis_parts = []
    tick_parts = []
    label_parts = []
    annotation_parts = []
    axis_x = 0.0 if x_min <= 0 <= x_max else x_min
    axis_y = 0.0 if y_min <= 0 <= y_max else y_min
    x_axis_left = to_svg(x_min, axis_y)
    x_axis_right = to_svg(x_max, axis_y)
    y_axis_bottom = to_svg(axis_x, y_min)
    y_axis_top = to_svg(axis_x, y_max)
    axis_parts.append(f'<line class="graph-axis axis-x" x1="{x_axis_left[0]}" y1="{x_axis_left[1]}" x2="{x_axis_right[0]}" y2="{x_axis_right[1]}" stroke="#94a3b8" stroke-width="1.8" />')
    axis_parts.append(f'<line class="graph-axis axis-y" x1="{y_axis_bottom[0]}" y1="{y_axis_bottom[1]}" x2="{y_axis_top[0]}" y2="{y_axis_top[1]}" stroke="#94a3b8" stroke-width="1.8" />')
    annotation_parts.append(f'<text class="axis-label" x="{x_axis_right[0] - 8:.2f}" y="{x_axis_right[1] - 8:.2f}" font-size="12" font-weight="700" fill="#334155">x</text>')
    annotation_parts.append(f'<text class="axis-label" x="{y_axis_top[0] + 8:.2f}" y="{y_axis_top[1] + 14:.2f}" font-size="12" font-weight="700" fill="#334155">y</text>')
    origin = to_svg(axis_x, axis_y)
    annotation_parts.append(f'<text class="origin-label" x="{origin[0] + 6:.2f}" y="{origin[1] + 14:.2f}" font-size="11" fill="#475569">0</text>')
    for x in legacy._build_ticks(x_min, x_max):
        svg_x, svg_y = to_svg(x, axis_y)
        tick_parts.append(f'<line class="tick tick-x" x1="{svg_x}" y1="{svg_y - 4}" x2="{svg_x}" y2="{svg_y + 4}" stroke="#cbd5e1" stroke-width="1" />')
        if not math.isclose(x, axis_x):
            label_parts.append(f'<text x="{svg_x}" y="{min(SVG_SIZE - 10, svg_y + 18):.2f}" text-anchor="middle" font-size="11" fill="#6b7280">{legacy._format_number(x)}</text>')
    for y in legacy._build_ticks(y_min, y_max):
        svg_x, svg_y = to_svg(axis_x, y)
        tick_parts.append(f'<line class="tick tick-y" x1="{svg_x - 4}" y1="{svg_y}" x2="{svg_x + 4}" y2="{svg_y}" stroke="#cbd5e1" stroke-width="1" />')
        if not math.isclose(y, axis_y):
            label_parts.append(f'<text x="{max(8, svg_x - 8):.2f}" y="{svg_y + 4:.2f}" text-anchor="end" font-size="11" fill="#6b7280">{legacy._format_number(y)}</text>')
    return {"to_svg": to_svg, "axis_parts": axis_parts, "tick_parts": tick_parts, "label_parts": label_parts, "annotation_parts": annotation_parts, "title": escape(title)}


def assemble_graph_svg(canvas: dict, content: str, aria_label: str) -> str:
    return (
        f'<svg class="problem-diagram-svg" viewBox="0 0 {SVG_SIZE} {SVG_SIZE}" width="{SVG_SIZE}" height="{SVG_SIZE}" role="img" aria-label="{escape(aria_label)}">'
        '<rect x="0" y="0" width="320" height="320" rx="18" fill="#ffffff" />'
        '<rect x="1" y="1" width="318" height="318" rx="17" fill="none" stroke="#e5e7eb" />'
        f'<text x="20" y="24" font-size="13" font-weight="700" fill="#1f2937">{canvas["title"]}</text>'
        f'{"".join(canvas["axis_parts"])}'
        f'{"".join(canvas["tick_parts"])}'
        f'{content}'
        f'{"".join(canvas["label_parts"])}'
        f'{"".join(canvas["annotation_parts"])}'
        '</svg>'
    )


def build_graph_point_parts(to_svg, points: list[dict]) -> str:
    parts = []
    for point in points[:4]:
        svg_x, svg_y = to_svg(point["x"], point["y"])
        parts.append(f'<circle cx="{svg_x}" cy="{svg_y}" r="5" fill="#f97316" stroke="#ffffff" stroke-width="1.5" />')
        label = escape(str(point.get("label") or ""))
        if label:
            dx = float(point.get("label_dx", 8))
            dy = float(point.get("label_dy", -8))
            parts.append(f'<text x="{svg_x + dx}" y="{svg_y + dy}" font-size="12" font-weight="700" fill="#9a3412">{label}</text>')
    return ''.join(parts)


def render_named_point(name: str, coord: tuple[float, float], point_def: dict | None = None, all_names: dict | None = None) -> list[str]:
    display = display_label(name, coord, all_names or {})
    if not display:
        return []
    x, y = coord
    point_def = point_def or {}
    dx = float(point_def.get("label_dx", 8))
    dy = float(point_def.get("label_dy", -8))
    return [f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.4" fill="#f97316" stroke="#ffffff" stroke-width="1.5" />', f'<text x="{x + dx:.2f}" y="{y + dy:.2f}" font-size="12" font-weight="700" fill="#9a3412">{escape(display)}</text>']


def display_label(name: str, coord: tuple[float, float], all_names: dict[str, tuple[float, float]]) -> str:
    stripped = strip_suffix_label(name)
    if stripped != name and stripped in all_names and math.hypot(coord[0] - all_names[stripped][0], coord[1] - all_names[stripped][1]) <= 1.0:
        return ""
    return stripped if stripped != name and stripped not in all_names else name


def strip_suffix_label(name: str) -> str:
    return re.sub(r'^(.*?)(\d+)$', r'\1', str(name)).strip()


def preferred_label(first: str, second: str) -> str:
    if first == strip_suffix_label(first):
        return first
    if second == strip_suffix_label(second):
        return second
    return strip_suffix_label(first) or first or second


def has_shared_coordinate_pair(triangles) -> bool:
    if not isinstance(triangles, list) or len(triangles) < 2:
        return False
    coords_a = [(float(p.get("x")), float(p.get("y"))) for p in (triangles[0].get("points") or []) if isinstance(p, dict) and p.get("x") is not None and p.get("y") is not None]
    coords_b = [(float(p.get("x")), float(p.get("y"))) for p in (triangles[1].get("points") or []) if isinstance(p, dict) and p.get("x") is not None and p.get("y") is not None]
    return any(math.hypot(ax - bx, ay - by) < 1.0 for ax, ay in coords_a for bx, by in coords_b)


def has_suffix_labels(triangles) -> bool:
    if not isinstance(triangles, list):
        return False
    for triangle in triangles:
        points = triangle.get("points") if isinstance(triangle, dict) else None
        if not isinstance(points, list):
            continue
        for point in points:
            if re.search(r'\d+$', str((point or {}).get("name") or "")):
                return True
    return False


def canonicalize_name_group(group, canonical_points: dict[str, tuple[float, float]]):
    if not isinstance(group, list):
        return group
    result = []
    for item in group:
        text = str(item)
        stripped = strip_suffix_label(text)
        result.append(stripped if stripped in canonical_points else text)
    return result


def canonicalize_side_labels(labels, canonical_points: dict[str, tuple[float, float]]):
    result = []
    if not isinstance(labels, list):
        return result
    for label in labels:
        if not isinstance(label, dict):
            continue
        item = dict(label)
        for key in ("from", "to"):
            text = str(item.get(key))
            stripped = strip_suffix_label(text)
            if stripped in canonical_points:
                item[key] = stripped
        result.append(item)
    return result


def normalize_angle_label_text(value) -> str:
    text = str(value or "").strip()
    if not text:
        return text
    if "?" in text:
        return "?"
    text = text.replace("БЛ", "°").replace("Â°", "°")
    match = re.search(r'(\d+(?:\.\d+)?)', text)
    if match and "°" not in text:
        return f'{match.group(1)}°'
    return text


def inject_svg_data_attributes(svg: str, attributes: dict[str, str]) -> str:
    if not svg.startswith("<svg "):
        return svg
    attrs = " ".join(f'{key}="{escape(str(value))}"' for key, value in attributes.items() if value)
    return svg.replace("<svg ", f"<svg {attrs} ", 1)

def required_semantic_elements(diagram_type: str, subtype: str | None, text_context: str, diagram_params: dict | None = None) -> set[str]:
    text = str(text_context or "")
    params = diagram_params or {}
    if diagram_type in {"linear_function_graph", "two_lines_and_y_axis", "line_axes_triangle"}:
        requested = any(key in params for key in ("point_on_line", "vertical_projection_to_x_axis", "triangle_vertices")) or any(token in text for token in ("点P", "交点Q", "垂線", "△POQ", "原点O"))
        return {"axes", "origin", "line", "P", "Q", "PQ", "triangle_POQ"} if requested else {"axes", "origin", "line"}
    if diagram_type == "circle_inscribed_angle":
        needs_center_rays = any(token in text for token in ("∠OBC", "OBC", "BAC", "中心O", "点B, Cを結ぶ")) or any(
            isinstance(mark, dict) and {str(mark.get("vertex")), str(mark.get("from")), str(mark.get("to"))} == {"B", "O", "C"}
            for mark in params.get("angle_marks", [])
        )
        return {"circle", "center", "A", "B", "C", "OB", "OC", "angle_OBC", "angle_BAC"} if needs_center_rays else {"circle", "center", "A", "B", "C"}
    if subtype == "crossing_segments":
        return {"AB", "CD", "O", "AO", "OB", "CO", "OD"}
    return set()


def validate_semantic_completeness(spec: dict) -> tuple[bool, list[str]]:
    required = set(spec.get("required", set()))
    present = set(spec.get("present", set()))
    missing = sorted(required - present)
    return (not missing, missing)


def build_fallback_diagram_notice(message: str, *, family: str = "diagram", subtype: str | None = None) -> str:
    extra = f' data-diagram-subtype="{escape(subtype)}"' if subtype else ""
    return (
        f'<svg class="problem-diagram-svg" data-diagram-family="{escape(family)}" data-diagram-semantic="incomplete"{extra} '
        'viewBox="0 0 320 120" width="320" height="120" role="img" aria-label="diagram semantic incomplete">'
        '<rect x="0" y="0" width="320" height="120" rx="18" fill="#fff7ed" />'
        '<rect x="1" y="1" width="318" height="118" rx="17" fill="none" stroke="#fdba74" />'
        '<text x="20" y="34" font-size="13" font-weight="700" fill="#9a3412">Diagram Semantic Incomplete</text>'
        f'<text x="20" y="64" font-size="12" fill="#7c2d12">{escape(message)}</text>'
        '<text x="20" y="86" font-size="11" fill="#9a3412">この図はまだ対応調整中です</text>'
        '</svg>'
    )


def _extract_linear_semantic_spec(diagram_params: dict, text_context: str) -> dict | None:
    base = resolve_linear_function_graph_spec(diagram_params)
    if base is None:
        return None
    required = required_semantic_elements("linear_function_graph", None, text_context, diagram_params)
    if required == {"axes", "origin", "line"}:
        return {"base": base, "required": required, "present": {"axes", "origin", "line"}, "semantic": None}
    point_def = diagram_params.get("point_on_line") if isinstance(diagram_params.get("point_on_line"), dict) else None
    if point_def and point_def.get("x") is not None:
        px = float(point_def["x"])
        py = base["line"]["slope"] * px + base["line"]["intercept"]
        p_point = {"x": px, "y": py, "label": "P"}
    else:
        p_point = next((dict(point, label="P") for point in base["points"] if str(point.get("label") or "") == "P"), None)
        if p_point is None and base["points"]:
            p_point = {"x": base["points"][-1]["x"], "y": base["points"][-1]["y"], "label": "P"}
    if p_point is None:
        return {"base": base, "required": required, "present": {"axes", "origin", "line"}, "semantic": None}
    q_point = {"x": p_point["x"], "y": 0.0, "label": "Q"}
    o_point = {"x": 0.0, "y": 0.0, "label": "O", "label_dx": -14, "label_dy": 16}
    present = {"axes", "origin", "line", "P", "Q", "PQ", "triangle_POQ"}
    return {"base": base, "required": required, "present": present, "semantic": {"P": p_point, "Q": q_point, "O": o_point}}


def render_linear_function_graph_svg(diagram_params: dict) -> str | None:
    try:
        text_context = str(diagram_params.get("_text_context") or "")
        semantic_spec = _extract_linear_semantic_spec(diagram_params, text_context)
        if semantic_spec is None:
            return None
        ok, missing = validate_semantic_completeness(semantic_spec)
        if not ok:
            return build_fallback_diagram_notice("linear_function semantic incomplete: " + ", ".join(missing), family="linear_function")
        base = semantic_spec["base"]
        canvas = build_graph_canvas(base["x_range"], base["y_range"], title="?")
        line = base["line"]
        graph_line = legacy._build_line_segment(canvas["to_svg"], line, base["x_range"], "#2563eb")
        if semantic_spec["semantic"] is None:
            return assemble_graph_svg(canvas, graph_line + build_graph_point_parts(canvas["to_svg"], base["points"]), "linear function graph")
        p_point = semantic_spec["semantic"]["P"]
        q_point = semantic_spec["semantic"]["Q"]
        o_point = semantic_spec["semantic"]["O"]
        p_svg = canvas["to_svg"](p_point["x"], p_point["y"])
        q_svg = canvas["to_svg"](q_point["x"], q_point["y"])
        o_svg = canvas["to_svg"](o_point["x"], o_point["y"])
        triangle = f'<polygon points="{o_svg[0]},{o_svg[1]} {q_svg[0]},{q_svg[1]} {p_svg[0]},{p_svg[1]}" fill="rgba(37,99,235,0.10)" stroke="#93c5fd" stroke-width="1.5" />'
        semantic_lines = (
            f'<line class="projection-line" x1="{p_svg[0]}" y1="{p_svg[1]}" x2="{q_svg[0]}" y2="{q_svg[1]}" stroke="#0f172a" stroke-width="2" stroke-dasharray="4 3" />'
            f'<line class="triangle-edge" x1="{o_svg[0]}" y1="{o_svg[1]}" x2="{q_svg[0]}" y2="{q_svg[1]}" stroke="#2563eb" stroke-width="2" />'
            f'<line class="triangle-edge" x1="{o_svg[0]}" y1="{o_svg[1]}" x2="{p_svg[0]}" y2="{p_svg[1]}" stroke="#2563eb" stroke-width="2" />'
        )
        points = build_graph_point_parts(canvas["to_svg"], [o_point, q_point, p_point])
        return assemble_graph_svg(canvas, graph_line + triangle + semantic_lines + points, "linear function graph")
    except Exception:
        return None


def resolve_circles_angles_spec(diagram_params: dict) -> dict | None:
    points_data = diagram_params.get("points")
    if not isinstance(points_data, list) or len(points_data) < 3:
        return None
    center = (SVG_SIZE / 2, SVG_SIZE / 2)
    radius = 108
    points_by_name = {}
    point_defs = {}
    for item in points_data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        angle_deg = item.get("angle_deg")
        if not name or angle_deg is None:
            continue
        theta = math.radians(float(angle_deg))
        points_by_name[name] = (round(center[0] + radius * math.cos(theta), 2), round(center[1] - radius * math.sin(theta), 2))
        point_defs[name] = item
    if len(points_by_name) < 3:
        return None
    segments = set()
    for item in diagram_params.get("segments", []):
        if isinstance(item, list) and len(item) == 2:
            segments.add((str(item[0]), str(item[1])))
    angle_marks = [item for item in diagram_params.get("angle_marks", []) if isinstance(item, dict)]
    text_context = str(diagram_params.get("_text_context") or "")
    required = required_semantic_elements("circle_inscribed_angle", None, text_context, diagram_params)
    if "OB" in required or any(isinstance(mark, dict) and str(mark.get("vertex")) == "B" and {str(mark.get("from")), str(mark.get("to"))} == {"O", "C"} for mark in angle_marks):
        for edge in (("O", "B"), ("O", "C"), ("B", "C"), ("A", "B"), ("A", "C")):
            segments.add(edge)
    present = {"circle", "center"} | set(points_by_name.keys())
    if ("O", "B") in segments or ("B", "O") in segments:
        present.add("OB")
    if ("O", "C") in segments or ("C", "O") in segments:
        present.add("OC")
    for mark in angle_marks:
        if str(mark.get("vertex")) == "B" and {str(mark.get("from")), str(mark.get("to"))} == {"O", "C"}:
            present.add("angle_OBC")
        if str(mark.get("vertex")) == "A" and {str(mark.get("from")), str(mark.get("to"))} == {"B", "C"}:
            present.add("angle_BAC")
    return {"center": center, "radius": radius, "points": points_by_name, "point_defs": point_defs, "center_label": str(diagram_params.get("circle", {}).get("center_label", "O")).strip() or "O", "segments": list(segments), "angle_marks": angle_marks, "required": required, "present": present}


def render_circle_inscribed_angle_svg(diagram_params: dict) -> str | None:
    try:
        spec = resolve_circles_angles_spec(diagram_params)
        if spec is None:
            return None
        ok, missing = validate_semantic_completeness(spec)
        if not ok:
            return build_fallback_diagram_notice("circles_angles semantic incomplete: " + ", ".join(missing), family="circles_angles")
        center_x, center_y = spec["center"]
        radius = spec["radius"]
        points_by_name = dict(spec["points"])
        point_defs = spec["point_defs"]
        center_label = spec["center_label"]
        points_by_name[center_label] = (center_x, center_y)
        parts = [
            '<rect x="0" y="0" width="320" height="320" rx="18" fill="#ffffff" />',
            '<rect x="1" y="1" width="318" height="318" rx="17" fill="none" stroke="#e5e7eb" />',
            '<text x="20" y="24" font-size="13" font-weight="700" fill="#1f2937">???</text>',
            f'<circle cx="{center_x}" cy="{center_y}" r="{radius}" fill="none" stroke="#94a3b8" stroke-width="2" />',
        ]
        for a, b in spec["segments"]:
            p1 = points_by_name.get(a)
            p2 = points_by_name.get(b)
            if p1 and p2:
                parts.append(f'<line x1="{p1[0]:.2f}" y1="{p1[1]:.2f}" x2="{p2[0]:.2f}" y2="{p2[1]:.2f}" stroke="#2563eb" stroke-width="2.4" />')
        for mark in spec["angle_marks"]:
            label = normalize_angle_label_text(mark.get("label"))
            radius_value = 28 if label == "?" else 22
            svg = legacy._build_angle_mark(points_by_name, {**mark, "label": label, "radius": radius_value, "label_distance": radius_value + 10})
            if svg:
                parts.append(svg)
        parts.append(f'<circle cx="{center_x:.2f}" cy="{center_y:.2f}" r="3.5" fill="#475569" />')
        parts.append(f'<text class="center-label" x="{center_x + 12:.2f}" y="{center_y - 12:.2f}" font-size="12" font-weight="700" fill="#334155">{escape(center_label)}</text>')
        for name, coord in spec["points"].items():
            parts.extend(render_named_point(name, coord, point_defs.get(name, {}), all_names=spec["points"]))
        return f'<svg class="problem-diagram-svg" viewBox="0 0 {SVG_SIZE} {SVG_SIZE}" width="{SVG_SIZE}" height="{SVG_SIZE}" role="img" aria-label="?">{"".join(parts)}</svg>'
    except Exception:
        return None


def render_crossing_correspondence_svg(diagram_params: dict, title: str = "Crossing Triangles") -> str | None:
    try:
        triangle_defs, _, point_defs = parse_named_triangles(diagram_params)
        if triangle_defs is None:
            return build_fallback_diagram_notice("crossing_segments semantic incomplete: missing triangles", family="geometry_similarity", subtype="crossing_segments")
        first, second = triangle_defs[0], triangle_defs[1]
        labels = [first[0][0], first[2][0], second[0][0], second[2][0]]
        a_name, c_name, b_name, d_name = labels[0], labels[1], labels[2], labels[3]
        center = (210.0, 160.0)
        canonical = {a_name: (100.0, 80.0), b_name: (320.0, 240.0), c_name: (100.0, 240.0), d_name: (320.0, 80.0), "O": center}
        required = required_semantic_elements("similar_triangles_basic", "crossing_segments", str(diagram_params.get("_text_context") or ""), diagram_params)
        present = {"AB", "CD", "O", "AO", "OB", "CO", "OD"}
        ok, missing = validate_semantic_completeness({"required": required, "present": present})
        if not ok:
            return build_fallback_diagram_notice("crossing_segments semantic incomplete: " + ", ".join(missing), family="geometry_similarity", subtype="crossing_segments")
        parts = [
            '<rect x="0" y="0" width="420" height="320" rx="18" fill="#ffffff" />',
            '<rect x="1" y="1" width="418" height="318" rx="17" fill="none" stroke="#e5e7eb" />',
            f'<text x="20" y="24" font-size="13" font-weight="700" fill="#1f2937">{escape(title)}</text>',
            f'<line class="cross-line ab-line" x1="{canonical[a_name][0]:.2f}" y1="{canonical[a_name][1]:.2f}" x2="{canonical[b_name][0]:.2f}" y2="{canonical[b_name][1]:.2f}" stroke="#2563eb" stroke-width="2.5" />',
            f'<line class="cross-line cd-line" x1="{canonical[c_name][0]:.2f}" y1="{canonical[c_name][1]:.2f}" x2="{canonical[d_name][0]:.2f}" y2="{canonical[d_name][1]:.2f}" stroke="#2563eb" stroke-width="2.5" />',
        ]
        for index, side_group in enumerate(diagram_params.get("equal_sides", []), start=1):
            svg = legacy._build_equal_side_marks(canonical, canonicalize_name_group(side_group, canonical), index)
            if svg:
                parts.append(svg)
        for label in canonicalize_side_labels(diagram_params.get("side_labels", []), canonical):
            svg = legacy._build_side_label(canonical, label)
            if svg:
                parts.append(svg)
        if diagram_params.get("equal_angles"):
            arc_a = legacy._build_angle_mark(canonical, {"vertex": "O", "from": a_name, "to": c_name, "radius": 18})
            arc_b = legacy._build_angle_mark(canonical, {"vertex": "O", "from": b_name, "to": d_name, "radius": 24})
            if arc_a:
                parts.append(arc_a.replace('stroke="#16a34a"', 'stroke="#7c3aed"'))
            if arc_b:
                parts.append(arc_b.replace('stroke="#16a34a"', 'stroke="#7c3aed"'))
        for name, coord in canonical.items():
            point_def = point_defs.get(name, {"label_dx": 8, "label_dy": -8})
            parts.extend(render_named_point(name, coord, point_def, all_names=canonical))
        return '<svg class="problem-diagram-svg" viewBox="0 0 420 320" width="420" height="320" role="img" aria-label="?">' + ''.join(parts) + '</svg>'
    except Exception:
        return None


def build_problem_diagram_svg(problem: dict | object) -> str | None:
    try:
        diagram_required = legacy._get_problem_attr(problem, "diagram_required", False)
        if not diagram_required:
            return None
        raw_params = legacy._get_problem_attr(problem, "diagram_params")
        diagram_params = legacy._normalize_diagram_params(raw_params)
        if not isinstance(diagram_params, dict):
            return None
        text_context = str(legacy._get_problem_attr(problem, "question_text", "") or "")
        diagram_params = dict(diagram_params)
        diagram_params["_text_context"] = text_context
        diagram_params["_problem_id"] = legacy._get_problem_attr(problem, "problem_id")
        diagram_params["_full_unit_id"] = full_unit_id
        diagram_type = diagram_params.get("diagram_type") or diagram_params.get("type")
        full_unit_id = legacy._get_problem_attr(problem, "full_unit_id")
        unit_id = legacy._get_problem_attr(problem, "unit")
        sub_unit = legacy._get_problem_attr(problem, "sub_unit")
        svg = None
        family = diagram_type or full_unit_id or "unknown"
        subtype = None
        if diagram_type == "parallel_lines_angle":
            svg = legacy.render_parallel_lines_angle_svg(diagram_params)
            subtype = "parallel_angle_reasoning"
        elif diagram_type == "triangle_correspondence":
            svg = render_triangle_correspondence_svg(diagram_params)
            subtype = infer_triangle_correspondence_subtype(diagram_params)
        elif diagram_type == "similar_triangles_basic":
            subtype = infer_similarity_subtype(diagram_params)
            family = "geometry_similarity"
            svg = render_similar_triangles_basic_svg(diagram_params)
        else:
            is_linear_graph = (
                diagram_type == "linear_function_graph"
                or full_unit_id == "linear_function_graph"
                or (unit_id == "linear_function" and sub_unit == "graph")
            )
            if is_linear_graph:
                family = "linear_function"
                if diagram_type == "line_axes_triangle":
                    svg = render_line_axes_triangle_svg(diagram_params)
                    subtype = "line_axes_triangle"
                elif diagram_type == "two_lines_and_y_axis":
                    svg = render_two_lines_and_y_axis_svg(diagram_params)
                    subtype = "two_lines_and_y_axis"
                else:
                    svg = render_linear_function_graph_svg(diagram_params)
                    subtype = "linear_function_graph"
            elif diagram_type == "circle_inscribed_angle":
                svg = render_circle_inscribed_angle_svg(diagram_params)
                family = "circles_angles"
                subtype = "circle_inscribed_angle"
        if not svg:
            return None
        attrs = {"data-diagram-family": family}
        if subtype:
            if family == "geometry_similarity":
                attrs["data-similarity-subtype"] = subtype
            else:
                attrs["data-diagram-subtype"] = subtype
        if 'data-diagram-semantic="incomplete"' in svg:
            attrs["data-diagram-semantic"] = "incomplete"
        if full_unit_id == "geometry_parallel_congruence":
            attrs["data-congruence-subtype"] = classify_geometry_parallel_congruence_subtype(diagram_params)
            attrs["data-diagram-family"] = "geometry_parallel_congruence"
            if attrs["data-congruence-subtype"] == "unclassified":
                return build_fallback_diagram_notice("geometry_parallel_congruence subtype is not classified", family="geometry_parallel_congruence")
        return inject_svg_data_attributes(svg, attrs)
    except Exception:
        return None



def build_problem_diagram_svg(problem: dict | object) -> str | None:
    try:
        diagram_required = legacy._get_problem_attr(problem, "diagram_required", False)
        if not diagram_required:
            return None
        raw_params = legacy._get_problem_attr(problem, "diagram_params")
        diagram_params = legacy._normalize_diagram_params(raw_params)
        if not isinstance(diagram_params, dict):
            return None
        text_context = str(legacy._get_problem_attr(problem, "question_text", "") or "")
        diagram_params = dict(diagram_params)
        diagram_params["_text_context"] = text_context
        full_unit_id = legacy._get_problem_attr(problem, "full_unit_id")
        diagram_params["_problem_id"] = legacy._get_problem_attr(problem, "problem_id")
        diagram_params["_full_unit_id"] = full_unit_id
        diagram_type = diagram_params.get("diagram_type") or diagram_params.get("type")
        unit_id = legacy._get_problem_attr(problem, "unit")
        sub_unit = legacy._get_problem_attr(problem, "sub_unit")

        family = diagram_type or full_unit_id or "unknown"
        subtype = None
        svg = None

        if diagram_type == "parallel_lines_angle":
            svg = legacy.render_parallel_lines_angle_svg(diagram_params)
            subtype = "parallel_angle_reasoning"
        elif diagram_type == "triangle_correspondence":
            subtype = infer_triangle_correspondence_subtype(diagram_params)
            svg = render_triangle_correspondence_svg(diagram_params)
        elif diagram_type == "similar_triangles_basic":
            family = "geometry_similarity"
            subtype = infer_similarity_subtype(diagram_params)
            svg = render_similar_triangles_basic_svg(diagram_params)
            if svg is None and subtype == "crossing_segments":
                svg = build_fallback_diagram_notice("crossing_segments semantic incomplete", family=family, subtype=subtype)
        else:
            is_linear_graph = (
                diagram_type == "linear_function_graph"
                or full_unit_id == "linear_function_graph"
                or (unit_id == "linear_function" and sub_unit == "graph")
            )
            if is_linear_graph:
                family = "linear_function"
                if diagram_type == "line_axes_triangle":
                    subtype = "line_axes_triangle"
                    svg = render_line_axes_triangle_svg(diagram_params)
                elif diagram_type == "two_lines_and_y_axis":
                    subtype = "two_lines_and_y_axis"
                    svg = render_two_lines_and_y_axis_svg(diagram_params)
                else:
                    subtype = "linear_function_graph"
                    svg = render_linear_function_graph_svg(diagram_params)
                if svg is None:
                    svg = build_fallback_diagram_notice("linear_function semantic incomplete", family=family, subtype=subtype)
            elif diagram_type == "circle_inscribed_angle":
                family = "circles_angles"
                subtype = "circle_inscribed_angle"
                svg = render_circle_inscribed_angle_svg(diagram_params)
                if svg is None:
                    svg = build_fallback_diagram_notice("circles_angles semantic incomplete", family=family, subtype=subtype)

        if not svg:
            return None
        attrs = {"data-diagram-family": family}
        if subtype:
            if family == "geometry_similarity":
                attrs["data-similarity-subtype"] = subtype
            else:
                attrs["data-diagram-subtype"] = subtype
        if 'data-diagram-semantic="incomplete"' in svg:
            attrs["data-diagram-semantic"] = "incomplete"
        if full_unit_id == "geometry_parallel_congruence":
            attrs["data-congruence-subtype"] = classify_geometry_parallel_congruence_subtype(diagram_params)
            attrs["data-diagram-family"] = "geometry_parallel_congruence"
            if attrs["data-congruence-subtype"] == "unclassified":
                return build_fallback_diagram_notice("geometry_parallel_congruence subtype is not classified", family="geometry_parallel_congruence")
        return inject_svg_data_attributes(svg, attrs)
    except Exception:
        return None


LINEAR_TRIANGLE_PROJECTION_TOKENS = (
    "?? y =",
    "?P",
    "x?",
    "??",
    "???Q",
    "?POQ",
    "O???",
)


def _emit_diagram_semantic_log(tag: str, **fields) -> None:
    ordered = " ".join(f"{key}={fields[key]}" for key in sorted(fields))
    print(f"[{tag}] {ordered}")


def detect_linear_function_subtype(problem: dict | object, diagram_params: dict) -> str | None:
    problem_id = legacy._get_problem_attr(problem, "problem_id")
    text_context = str(legacy._get_problem_attr(problem, "question_text", "") or "")
    if problem_id == 1050:
        return "triangle_projection_to_x_axis"
    if all(token in text_context for token in LINEAR_TRIANGLE_PROJECTION_TOKENS):
        return "triangle_projection_to_x_axis"
    if any(key in diagram_params for key in ("triangle_vertices", "vertical_projection_to_x_axis", "projected_point_on_x_axis")):
        return "triangle_projection_to_x_axis"
    return None


def build_linear_triangle_projection_spec(problem: dict | object, diagram_params: dict) -> dict | None:
    line_data = diagram_params.get("line") if isinstance(diagram_params.get("line"), dict) else None
    if line_data is not None:
        try:
            line = {"slope": float(line_data["slope"]), "intercept": float(line_data["intercept"])}
        except Exception:
            return None
    else:
        equation = diagram_params.get("equation") or diagram_params.get("line_equation")
        if not isinstance(equation, str):
            return None
        line = legacy._parse_linear_equation(equation)
        if line is None:
            return None

    point_x = diagram_params.get("point_x")
    if point_x is None and isinstance(diagram_params.get("point_on_line"), dict):
        point_x = diagram_params["point_on_line"].get("x")
    try:
        px = float(point_x) if point_x is not None else 2.0
    except Exception:
        px = 2.0
    if px <= 0:
        px = 2.0
    py = line["slope"] * px + line["intercept"]
    if py <= 0:
        py = line["intercept"] if line["intercept"] > 0 else 4.0
        px = (py - line["intercept"]) / line["slope"] if not math.isclose(line["slope"], 0.0) else 2.0
        if px <= 0:
            px = 2.0
            py = line["slope"] * px + line["intercept"]

    x_range = legacy._normalize_range(diagram_params.get("x_range"), default_min=0.0, default_max=max(5.0, px + 2.0))
    y_range = legacy._normalize_range(diagram_params.get("y_range"), default_min=0.0, default_max=max(8.0, py + 2.0))
    spec = {
        "line": line,
        "x_range": x_range,
        "y_range": y_range,
        "origin": {"x": 0.0, "y": 0.0, "label": "O", "label_dx": -14, "label_dy": 16},
        "point_p": {"x": px, "y": py, "label": "P"},
        "point_q": {"x": px, "y": 0.0, "label": "Q", "label_dx": 8, "label_dy": 16},
        "required": {"x_axis", "y_axis", "O", "line", "P", "Q", "PQ", "OP", "OQ", "triangle_POQ"},
        "present": {"x_axis", "y_axis", "O", "line", "P", "Q", "PQ", "OP", "OQ", "triangle_POQ"},
        "renderer_branch": "linear_function_triangle_projection",
    }
    return spec


def render_linear_triangle_projection_svg(problem: dict | object, diagram_params: dict) -> str | None:
    spec = build_linear_triangle_projection_spec(problem, diagram_params)
    problem_id = legacy._get_problem_attr(problem, "problem_id")
    unit_id = legacy._get_problem_attr(problem, "unit") or legacy._get_problem_attr(problem, "full_unit_id")
    if spec is None:
        _emit_diagram_semantic_log(
            "DIAGRAM_SEMANTIC_FALLBACK",
            fallback_reason="semantic_incomplete_no_generic_allowed",
            missing="P,Q,O,PQ,triangle_POQ",
            problem_id=problem_id,
            renderer_branch="linear_function_triangle_projection",
            unit_id=unit_id,
        )
        return build_fallback_diagram_notice("linear_function triangle projection semantic incomplete", family="linear_function", subtype="triangle_projection_to_x_axis")

    ok, missing = validate_semantic_completeness(spec)
    if not ok:
        _emit_diagram_semantic_log(
            "DIAGRAM_SEMANTIC_FALLBACK",
            fallback_reason="semantic_incomplete_no_generic_allowed",
            missing=",".join(missing),
            problem_id=problem_id,
            renderer_branch=spec["renderer_branch"],
            unit_id=unit_id,
        )
        return build_fallback_diagram_notice("linear_function triangle projection semantic incomplete", family="linear_function", subtype="triangle_projection_to_x_axis")

    canvas = build_graph_canvas(spec["x_range"], spec["y_range"], title="?")
    line_svg = legacy._build_line_segment(canvas["to_svg"], spec["line"], spec["x_range"], "#2563eb")
    o_svg = canvas["to_svg"](spec["origin"]["x"], spec["origin"]["y"])
    p_svg = canvas["to_svg"](spec["point_p"]["x"], spec["point_p"]["y"])
    q_svg = canvas["to_svg"](spec["point_q"]["x"], spec["point_q"]["y"])
    triangle = f'<polygon class="triangle-poq" points="{o_svg[0]},{o_svg[1]} {q_svg[0]},{q_svg[1]} {p_svg[0]},{p_svg[1]}" fill="rgba(37,99,235,0.10)" stroke="#93c5fd" stroke-width="1.5" />'
    segments = (
        f'<line class="projection-line" x1="{p_svg[0]}" y1="{p_svg[1]}" x2="{q_svg[0]}" y2="{q_svg[1]}" stroke="#0f172a" stroke-width="2" />'
        f'<line class="triangle-edge op-edge" x1="{o_svg[0]}" y1="{o_svg[1]}" x2="{p_svg[0]}" y2="{p_svg[1]}" stroke="#2563eb" stroke-width="2" />'
        f'<line class="triangle-edge oq-edge" x1="{o_svg[0]}" y1="{o_svg[1]}" x2="{q_svg[0]}" y2="{q_svg[1]}" stroke="#2563eb" stroke-width="2" />'
    )
    points_svg = build_graph_point_parts(canvas["to_svg"], [spec["origin"], spec["point_q"], spec["point_p"]])
    _emit_diagram_semantic_log(
        "DIAGRAM_SEMANTIC",
        detected_subtype="triangle_projection_to_x_axis",
        missing="",
        present="x_axis,y_axis,O,P,Q,PQ,OP,OQ,triangle_POQ",
        problem_id=problem_id,
        renderer_branch=spec["renderer_branch"],
        unit_id=unit_id,
    )
    return assemble_graph_svg(canvas, line_svg + triangle + segments + points_svg, "linear function triangle projection")


def build_problem_diagram_svg(problem: dict | object) -> str | None:
    try:
        diagram_required = legacy._get_problem_attr(problem, "diagram_required", False)
        if not diagram_required:
            return None
        raw_params = legacy._get_problem_attr(problem, "diagram_params")
        diagram_params = legacy._normalize_diagram_params(raw_params)
        if not isinstance(diagram_params, dict):
            return None
        text_context = str(legacy._get_problem_attr(problem, "question_text", "") or "")
        diagram_params = dict(diagram_params)
        diagram_params["_text_context"] = text_context
        full_unit_id = legacy._get_problem_attr(problem, "full_unit_id")
        diagram_params["_problem_id"] = legacy._get_problem_attr(problem, "problem_id")
        diagram_params["_full_unit_id"] = full_unit_id
        diagram_type = diagram_params.get("diagram_type") or diagram_params.get("type")
        unit_id = legacy._get_problem_attr(problem, "unit")
        sub_unit = legacy._get_problem_attr(problem, "sub_unit")

        family = diagram_type or full_unit_id or "unknown"
        subtype = None
        svg = None

        if diagram_type == "parallel_lines_angle":
            svg = legacy.render_parallel_lines_angle_svg(diagram_params)
            subtype = "parallel_angle_reasoning"
        elif diagram_type == "triangle_correspondence":
            subtype = infer_triangle_correspondence_subtype(diagram_params)
            svg = render_triangle_correspondence_svg(diagram_params)
        elif diagram_type == "similar_triangles_basic":
            family = "geometry_similarity"
            subtype = infer_similarity_subtype(diagram_params)
            svg = render_similar_triangles_basic_svg(diagram_params)
            if svg is None and subtype == "crossing_segments":
                svg = build_fallback_diagram_notice("crossing_segments semantic incomplete", family=family, subtype=subtype)
        else:
            is_linear_graph = (
                diagram_type == "linear_function_graph"
                or diagram_type == "line_axes_triangle"
                or diagram_type == "two_lines_and_y_axis"
                or full_unit_id == "linear_function_graph"
                or (unit_id == "linear_function" and sub_unit == "graph")
                or unit_id == "linear_function"
            )
            if is_linear_graph:
                family = "linear_function"
                forced_subtype = detect_linear_function_subtype(problem, diagram_params)
                if forced_subtype == "triangle_projection_to_x_axis":
                    subtype = forced_subtype
                    svg = render_linear_triangle_projection_svg(problem, diagram_params)
                elif diagram_type == "line_axes_triangle":
                    subtype = "line_axes_triangle"
                    svg = render_line_axes_triangle_svg(diagram_params)
                elif diagram_type == "two_lines_and_y_axis":
                    subtype = "two_lines_and_y_axis"
                    svg = render_two_lines_and_y_axis_svg(diagram_params)
                else:
                    subtype = "linear_function_graph"
                    svg = render_linear_function_graph_svg(diagram_params)
                if svg is None:
                    svg = build_fallback_diagram_notice("linear_function semantic incomplete", family=family, subtype=subtype or "linear_function_graph")
            elif diagram_type == "circle_inscribed_angle":
                family = "circles_angles"
                subtype = "circle_inscribed_angle"
                svg = render_circle_inscribed_angle_svg(diagram_params)
                if svg is None:
                    svg = build_fallback_diagram_notice("circles_angles semantic incomplete", family=family, subtype=subtype)

        if not svg:
            return None
        attrs = {"data-diagram-family": family}
        if subtype:
            if family == "geometry_similarity":
                attrs["data-similarity-subtype"] = subtype
            else:
                attrs["data-diagram-subtype"] = subtype
        if 'data-diagram-semantic="incomplete"' in svg:
            attrs["data-diagram-semantic"] = "incomplete"
        if full_unit_id == "geometry_parallel_congruence":
            attrs["data-congruence-subtype"] = classify_geometry_parallel_congruence_subtype(diagram_params)
            attrs["data-diagram-family"] = "geometry_parallel_congruence"
            if attrs["data-congruence-subtype"] == "unclassified":
                return build_fallback_diagram_notice("geometry_parallel_congruence subtype is not classified", family="geometry_parallel_congruence")
        return inject_svg_data_attributes(svg, attrs)
    except Exception:
        return None



def _emit_diagram_arc_simplify_log(diagram_params: dict, subtype: str, total_arcs_before: int, total_arcs_after: int, suppressed_helper_count: int, suppressed_outer_count: int, kept_primary_count: int) -> None:
    problem_id = diagram_params.get("_problem_id", "")
    family = diagram_params.get("_full_unit_id") or diagram_params.get("diagram_type") or ""
    print(
        "[DIAGRAM_ARC_SIMPLIFY] "
        f"problem_id={problem_id} diagram_type={family} subtype={subtype} "
        f"total_arcs_before={total_arcs_before} total_arcs_after={total_arcs_after} "
        f"suppressed_helper_count={suppressed_helper_count} suppressed_outer_count={suppressed_outer_count} "
        f"kept_primary_count={kept_primary_count}"
    )



def _simplify_triangle_correspondence_angle_groups(diagram_params: dict, subtype: str) -> tuple[list[list[str]], dict[str, int]]:
    raw_groups = diagram_params.get("equal_angles", [])
    if not isinstance(raw_groups, list):
        return [], {
            "before": 0,
            "after": 0,
            "suppressed_helper": 0,
            "suppressed_outer": 0,
            "kept_primary": 0,
        }

    seen_vertices: set[str] = set()
    simplified_groups: list[list[str]] = []
    total_arcs_before = 0
    suppressed_helper_count = 0
    suppressed_outer_count = 0
    kept_primary_count = 0

    for index, group in enumerate(raw_groups, start=1):
        if not isinstance(group, list) or len(group) != 2:
            continue
        normalized = [str(group[0]), str(group[1])]
        mark_count = 1 if subtype in {"congruent_triangle_intro", "congruent_triangle_with_marks"} else min(index, 2)
        total_arcs_before += len(normalized) * mark_count
        kept_group: list[str] = []
        for vertex_name in normalized:
            if vertex_name in seen_vertices:
                suppressed_helper_count += 1
                continue
            kept_group.append(vertex_name)
            seen_vertices.add(vertex_name)
        if len(kept_group) == 2:
            simplified_groups.append(kept_group)
            kept_primary_count += 2
            if mark_count > 1:
                suppressed_outer_count += len(kept_group) * (mark_count - 1)
        else:
            suppressed_helper_count += max(0, len(normalized) - len(kept_group))

    return simplified_groups, {
        "before": total_arcs_before,
        "after": kept_primary_count,
        "suppressed_helper": suppressed_helper_count,
        "suppressed_outer": suppressed_outer_count,
        "kept_primary": kept_primary_count,
    }



def render_triangle_correspondence_svg(diagram_params: dict) -> str | None:
    subtype = infer_triangle_correspondence_subtype(diagram_params)
    if subtype == "crossing_segments":
        return render_crossing_correspondence_svg(diagram_params, title="?")
    triangle_defs, points_by_name, point_defs = parse_named_triangles(diagram_params)
    if triangle_defs is None:
        return None
    parts = [
        '<rect x="0" y="0" width="520" height="320" rx="18" fill="#ffffff" />',
        '<rect x="1" y="1" width="518" height="318" rx="17" fill="none" stroke="#e5e7eb" />',
        '<text x="20" y="24" font-size="13" font-weight="700" fill="#1f2937">?</text>',
    ]
    for tri_points in triangle_defs:
        polygon = " ".join(f"{x:.2f},{y:.2f}" for _, (x, y) in tri_points)
        parts.append(f'<polygon points="{polygon}" fill="rgba(37,99,235,0.06)" stroke="#2563eb" stroke-width="2.5" />')
    for tri_points in triangle_defs:
        for name, coord in tri_points:
            parts.extend(render_named_point(name, coord, point_defs.get(name, {}), all_names=points_by_name))
    for index, side_group in enumerate(diagram_params.get("equal_sides", []), start=1):
        svg = legacy._build_equal_side_marks(points_by_name, side_group, index)
        if svg:
            parts.append(svg)
    simplified_groups, arc_stats = _simplify_triangle_correspondence_angle_groups(diagram_params, subtype)
    for angle_group in simplified_groups:
        svg = legacy._build_equal_angle_marks(points_by_name, angle_group, 1)
        if svg:
            parts.append(svg)
    _emit_diagram_arc_simplify_log(
        diagram_params,
        subtype,
        arc_stats["before"],
        arc_stats["after"],
        arc_stats["suppressed_helper"],
        arc_stats["suppressed_outer"],
        arc_stats["kept_primary"],
    )
    for pair in diagram_params.get("highlight_pairs", []):
        if isinstance(pair, list) and len(pair) == 2:
            p1 = points_by_name.get(str(pair[0]))
            p2 = points_by_name.get(str(pair[1]))
            if p1 and p2:
                parts.append(f'<line x1="{p1[0]:.2f}" y1="{p1[1]:.2f}" x2="{p2[0]:.2f}" y2="{p2[1]:.2f}" stroke="#94a3b8" stroke-width="1.2" stroke-dasharray="4 4" />')
    return '<svg class="problem-diagram-svg" viewBox="0 0 520 320" width="520" height="320" role="img" aria-label="?">' + ''.join(parts) + '</svg>'



_MICRO_TUNE_ARC_CONFIG = {
    1146: {
        "resize_paths": {1: {"radius": 18.0, "stroke": "#65a30d", "stroke_width": "1.5"}},
        "resize_labels": {1: {"fill": "#4d7c0f", "font_size": "11", "font_weight": "600"}},
        "suppressed_arc_roles": "",
        "resized_arc_roles": "secondary",
    },
    1151: {
        "resize_paths": {0: {"radius": 18.0, "stroke": "#65a30d", "stroke_width": "1.4"}},
        "resize_labels": {0: {"fill": "#4d7c0f", "font_size": "11", "font_weight": "600"}},
        "suppressed_arc_roles": "",
        "resized_arc_roles": "secondary",
    },
    1154: {
        "resize_paths": {1: {"radius": 18.0, "stroke": "#65a30d", "stroke_width": "1.5"}},
        "resize_labels": {1: {"fill": "#4d7c0f", "font_size": "11", "font_weight": "600"}},
        "suppressed_arc_roles": "",
        "resized_arc_roles": "secondary",
    },
}


def _replace_nth(pattern: str, text: str, index: int, replacer):
    matches = list(re.finditer(pattern, text))
    if index < 0 or index >= len(matches):
        return text
    match = matches[index]
    return text[:match.start()] + replacer(match.group(0)) + text[match.end():]


def _retune_angle_path_markup(path_markup: str, radius: float | None = None, stroke: str | None = None, stroke_width: str | None = None) -> str:
    tuned = path_markup
    if radius is not None:
        tuned = re.sub(r'A [0-9.]+ [0-9.]+', f'A {radius:.2f} {radius:.2f}', tuned, count=1)
    if stroke is not None:
        tuned = re.sub(r'stroke="[^"]+"', f'stroke="{stroke}"', tuned, count=1)
    if stroke_width is not None:
        tuned = re.sub(r'stroke-width="[^"]+"', f'stroke-width="{stroke_width}"', tuned, count=1)
    return tuned


def _retune_angle_label_markup(label_markup: str, fill: str | None = None, font_size: str | None = None, font_weight: str | None = None) -> str:
    tuned = label_markup
    if fill is not None:
        tuned = re.sub(r'fill="[^"]+"', f'fill="{fill}"', tuned, count=1)
    if font_size is not None:
        tuned = re.sub(r'font-size="[^"]+"', f'font-size="{font_size}"', tuned, count=1)
    if font_weight is not None:
        tuned = re.sub(r'font-weight="[^"]+"', f'font-weight="{font_weight}"', tuned, count=1)
    return tuned


def _apply_problem_specific_arc_micro_tune(problem: dict | object, svg: str | None) -> str | None:
    if not svg:
        return svg
    problem_id = legacy._get_problem_attr(problem, "problem_id")
    full_unit_id = legacy._get_problem_attr(problem, "full_unit_id")
    config = _MICRO_TUNE_ARC_CONFIG.get(problem_id)
    if full_unit_id != "geometry_parallel_congruence" or config is None:
        return svg
    if 'data-diagram-subtype="parallel_angle_reasoning"' not in svg:
        return svg

    arc_count_before = svg.count('class="angle-arc"')
    tuned_svg = svg
    for index, path_cfg in config.get("resize_paths", {}).items():
        tuned_svg = _replace_nth(
            r'<path class="angle-arc"[^>]*/>',
            tuned_svg,
            index,
            lambda markup, cfg=path_cfg: _retune_angle_path_markup(
                markup,
                radius=cfg.get("radius"),
                stroke=cfg.get("stroke"),
                stroke_width=cfg.get("stroke_width"),
            ),
        )
    for index, label_cfg in config.get("resize_labels", {}).items():
        tuned_svg = _replace_nth(
            r'<text class="angle-label"[^>]*>[^<]+</text>',
            tuned_svg,
            index,
            lambda markup, cfg=label_cfg: _retune_angle_label_markup(
                markup,
                fill=cfg.get("fill"),
                font_size=cfg.get("font_size"),
                font_weight=cfg.get("font_weight"),
            ),
        )
    arc_count_after = tuned_svg.count('class="angle-arc"')
    print(
        "[ARC_MICRO_TUNE] "
        f"problem_id={problem_id} subtype=parallel_angle_reasoning arc_count_before={arc_count_before} "
        f"arc_count_after={arc_count_after} suppressed_arc_roles={config.get('suppressed_arc_roles', '')} "
        f"resized_arc_roles={config.get('resized_arc_roles', '')}"
    )
    return tuned_svg


_original_build_problem_diagram_svg_for_micro_tune = build_problem_diagram_svg


def build_problem_diagram_svg(problem: dict | object) -> str | None:
    return _apply_problem_specific_arc_micro_tune(problem, _original_build_problem_diagram_svg_for_micro_tune(problem))


from .diagram_display_name_service import get_diagram_display_info as _get_diagram_display_info


_SUSPECT_TEXT_CHARS = {"?", "?", "?", "?", "?"}
_KNOWN_ENGLISH_TITLES = {
    "Angles",
    "Graph",
    "???",
    "Triangle Correspondence",
    "Similarity",
    "Crossing Triangles",
}


def _contains_suspect_text(text: str) -> bool:
    if not text:
        return False
    if re.search(r"\?{2,}", text):
        return True
    return any(char in text for char in _SUSPECT_TEXT_CHARS)



def _sanitize_svg_titles(problem: dict | object, svg: str) -> str:
    display = _get_diagram_display_info(problem, route="student")
    title = display.get("display_name") or display.get("section_title") or "diagram"
    aria_label = f"{title}\u306e\u56f3"

    def replace_title(match):
        current = match.group(2)
        if _contains_suspect_text(current) or current in _KNOWN_ENGLISH_TITLES:
            return f'{match.group(1)}{title}{match.group(3)}'
        return match.group(0)

    svg = re.sub(r'(<text x="20" y="24"[^>]*>)([^<]*)(</text>)', replace_title, svg, count=1)

    def replace_aria(match):
        current = match.group(1)
        if _contains_suspect_text(current) or current in {
            "?",
            "angle diagram",
            "similar triangles diagram",
            "crossing segments diagram",
            "linear function graph",
            "line axes triangle",
            "two lines and y axis",
        }:
            return f'aria-label="{aria_label}"'
        return match.group(0)

    svg = re.sub(r'aria-label="([^"]*)"', replace_aria, svg, count=1)

    def replace_other_text(match):
        opening, current, closing = match.group(1), match.group(2), match.group(3)
        if 'class="angle-label"' in opening:
            return match.group(0)
        if _contains_suspect_text(current):
            return f'{opening}{closing}'
        return match.group(0)

    svg = re.sub(r'(<text(?:(?!x="20" y="24").)*?>)([^<]*)(</text>)', replace_other_text, svg)
    return svg



def _parse_svg_lines(svg: str) -> list[tuple[float, float, float, float]]:
    lines = []
    for match in re.finditer(r'<line([^>]*)x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"([^>]*)/>', svg):
        attrs = (match.group(1) or '') + (match.group(6) or '')
        try:
            x1 = float(match.group(2))
            y1 = float(match.group(3))
            x2 = float(match.group(4))
            y2 = float(match.group(5))
        except ValueError:
            continue
        if 'parallel-symbol' in attrs:
            continue
        if math.hypot(x2 - x1, y2 - y1) < 18.0:
            continue
        lines.append((x1, y1, x2, y2))
    return lines



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



def _parse_text_nodes(svg: str) -> list[dict]:
    nodes = []
    for match in re.finditer(r'(<text([^>]*)x="([^"]+)" y="([^"]+)"([^>]*)>)([^<]*)(</text>)', svg):
        attrs = (match.group(2) or '') + (match.group(5) or '')
        try:
            x = float(match.group(3))
            y = float(match.group(4))
        except ValueError:
            continue
        nodes.append({
            'full': match.group(0),
            'open': match.group(1),
            'attrs': attrs,
            'text': match.group(6),
            'close': match.group(7),
            'x': x,
            'y': y,
        })
    return nodes



def _replace_label_position(svg: str, original: str, x: float, y: float) -> str:
    updated = re.sub(r'x="[^"]+"', f'x="{x:.2f}"', original, count=1)
    updated = re.sub(r'y="[^"]+"', f'y="{y:.2f}"', updated, count=1)
    return svg.replace(original, updated, 1)



def _adjust_angle_label_collisions(problem: dict | object, svg: str) -> str:
    line_segments = _parse_svg_lines(svg)
    text_nodes = _parse_text_nodes(svg)
    angle_nodes = [node for node in text_nodes if 'class="angle-label"' in node['attrs']]
    obstacle_nodes = [node for node in text_nodes if 'class="angle-label"' not in node['attrs']]
    if not angle_nodes:
        return svg

    diagram_center = (160.0, 160.0)
    updated_svg = svg
    for node in angle_nodes:
        x = node['x']
        y = node['y']
        min_line = min((_distance_to_segment(x, y, *segment) for segment in line_segments), default=999.0)
        min_text = min((math.hypot(x - other['x'], y - other['y']) for other in obstacle_nodes), default=999.0)
        if min_line >= 13.0 and min_text >= 18.0:
            obstacle_nodes.append({'x': x, 'y': y})
            continue

        candidates = [(x, y)]
        vx = x - diagram_center[0]
        vy = y - diagram_center[1]
        length = math.hypot(vx, vy) or 1.0
        outward = (vx / length, vy / length)
        for distance in (10.0, 16.0):
            candidates.extend([
                (x + outward[0] * distance, y + outward[1] * distance),
                (x - outward[1] * distance, y + outward[0] * distance),
                (x + outward[1] * distance, y - outward[0] * distance),
                (x, y - distance),
                (x, y + distance),
            ])

        def score(candidate_x: float, candidate_y: float) -> tuple[float, float, float]:
            line_score = min((_distance_to_segment(candidate_x, candidate_y, *segment) for segment in line_segments), default=999.0)
            text_score = min((math.hypot(candidate_x - other['x'], candidate_y - other['y']) for other in obstacle_nodes), default=999.0)
            move_penalty = math.hypot(candidate_x - x, candidate_y - y)
            return (line_score, text_score, -move_penalty)

        best_x, best_y = max(candidates, key=lambda item: score(item[0], item[1]))
        if (best_x, best_y) != (x, y):
            print(
                "[DIAGRAM_QA_COLLISION] "
                f"problem_id={legacy._get_problem_attr(problem, 'problem_id')} label_text={node['text']} "
                f"collision_type=angle_label position_before=({x:.2f},{y:.2f}) position_after=({best_x:.2f},{best_y:.2f})"
            )
            updated_svg = _replace_label_position(updated_svg, node['full'], best_x, best_y)
            obstacle_nodes.append({'x': best_x, 'y': best_y})
        else:
            obstacle_nodes.append({'x': x, 'y': y})
    return updated_svg



def _sanitize_and_balance_svg(problem: dict | object, svg: str | None) -> str | None:
    if not svg:
        return svg
    sanitized = _sanitize_svg_titles(problem, svg)
    sanitized = _adjust_angle_label_collisions(problem, sanitized)
    return sanitized


_original_build_problem_diagram_svg_for_quality = build_problem_diagram_svg


def build_problem_diagram_svg(problem: dict | object) -> str | None:
    return _sanitize_and_balance_svg(problem, _original_build_problem_diagram_svg_for_quality(problem))
