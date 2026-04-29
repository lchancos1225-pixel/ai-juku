import math
from html import escape

from .geometry_builder import GeometryDiagram, GeometryAngle
from .geometry_layout_service import GeometryLayout


def render_parallel_lines_angle_svg(diagram: GeometryDiagram, layout: GeometryLayout) -> str:
    parts: list[str] = [
        f'<rect x="0" y="0" width="{diagram.width}" height="{diagram.height}" rx="18" fill="#ffffff" />',
        f'<rect x="1" y="1" width="{diagram.width - 2}" height="{diagram.height - 2}" rx="17" fill="none" stroke="#e5e7eb" />',
        '<text x="20" y="24" font-size="13" font-weight="700" fill="#1f2937">?</text>',
    ]

    for line in diagram.lines.values():
        stroke = "#475569" if line.style == "parallel" else "#2563eb"
        stroke_width = "2.5" if line.style == "parallel" else "2.6"
        parts.append(
            f'<line x1="{line.p1[0]:.2f}" y1="{line.p1[1]:.2f}" x2="{line.p2[0]:.2f}" y2="{line.p2[1]:.2f}" '
            f'stroke="{stroke}" stroke-width="{stroke_width}" />'
        )

    for mark in layout.parallel_marks:
        line = diagram.lines[mark.line_id]
        parts.append(_render_parallel_mark(line.p1, line.p2, mark.count))

    for point in diagram.points.values():
        if not point.visible:
            continue
        parts.append(f'<circle cx="{point.x:.2f}" cy="{point.y:.2f}" r="3.8" fill="#f97316" />')

    for placement in layout.line_labels:
        parts.append(
            f'<text x="{placement.x:.2f}" y="{placement.y:.2f}" text-anchor="{placement.anchor}" '
            f'font-size="12" font-weight="700" fill="#334155">{escape(placement.text)}</text>'
        )

    for angle in diagram.angles:
        angle_layout = layout.angle_layouts.get(angle.id)
        if angle_layout is None or not angle_layout.visible or not angle.show_arc:
            continue
        point = diagram.points[angle.vertex_point_id]
        arc_path = _render_angle_arc(point.x, point.y, angle_layout.radius, angle)
        label_fill = "#166534" if angle.angle_role == "given" else "#0f172a"
        label_size = "12" if angle.angle_role == "given" else "13"
        parts.append(arc_path)
        parts.append(
            f'<text class="angle-label" data-angle-role="{angle.angle_role}" x="{angle_layout.label_x:.2f}" y="{angle_layout.label_y:.2f}" text-anchor="middle" '
            f'dominant-baseline="middle" font-size="{label_size}" font-weight="700" fill="{label_fill}" '
            'stroke="#ffffff" stroke-width="3" paint-order="stroke fill">'
            f'{escape(angle.value)}</text>'
        )

    for placement in layout.point_labels:
        parts.append(
            f'<text x="{placement.x:.2f}" y="{placement.y:.2f}" text-anchor="{placement.anchor}" '
            f'font-size="12" font-weight="700" fill="#9a3412">{escape(placement.text)}</text>'
        )

    return (
        f'<svg class="problem-diagram-svg" viewBox="0 0 {diagram.width} {diagram.height}" '
        f'width="{diagram.width}" height="{diagram.height}" role="img" aria-label="?">'
        f'{"".join(parts)}'
        '</svg>'
    )


def _render_angle_arc(cx: float, cy: float, radius: float, angle: GeometryAngle) -> str:
    start_deg, end_deg, large_arc_flag, sweep_flag = compute_arc_sweep(angle)
    start_x = cx + radius * math.cos(math.radians(start_deg))
    start_y = cy - radius * math.sin(math.radians(start_deg))
    end_x = cx + radius * math.cos(math.radians(end_deg))
    end_y = cy - radius * math.sin(math.radians(end_deg))
    stroke = "#16a34a" if angle.angle_role == "given" else "#0f172a"
    stroke_width = "2" if angle.angle_role == "given" else "2.4"
    return (
        f'<path class="angle-arc" data-angle-role="{angle.angle_role}" data-angle-region="{angle.selected_region}" '
        f'd="M {start_x:.2f} {start_y:.2f} A {radius:.2f} {radius:.2f} 0 {large_arc_flag} {sweep_flag} {end_x:.2f} {end_y:.2f}" '
        f'fill="none" stroke="{stroke}" stroke-width="{stroke_width}" />'
    )


def compute_arc_sweep(angle: GeometryAngle) -> tuple[float, float, int, int]:
    ccw_span = (angle.ray_b_direction - angle.ray_a_direction) % 360.0
    cw_span = (angle.ray_a_direction - angle.ray_b_direction) % 360.0
    if math.isclose(ccw_span, angle.region_span, abs_tol=0.01) or ccw_span <= cw_span:
        return angle.ray_a_direction, angle.ray_b_direction, 1 if ccw_span > 180.0 else 0, 0
    return angle.ray_b_direction, angle.ray_a_direction, 1 if cw_span > 180.0 else 0, 1


def _render_parallel_mark(p1: tuple[float, float], p2: tuple[float, float], mark_count: int) -> str:
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
        shift = (offset_index - (mark_count - 1) / 2) * 9.0
        cx = mx + ux * shift
        cy = my + uy * shift
        x1 = cx - nx * 7.0 - ux * 3.0
        y1 = cy - ny * 7.0 - uy * 3.0
        x2 = cx + nx * 7.0 + ux * 3.0
        y2 = cy + ny * 7.0 + uy * 3.0
        parts.append(
            f'<line class="parallel-symbol" x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="#0f766e" stroke-width="2" />'
        )
    return "".join(parts)
