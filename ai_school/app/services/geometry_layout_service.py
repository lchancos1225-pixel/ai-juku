from dataclasses import dataclass
import math

from .geometry_builder import GeometryAngle, GeometryDiagram


@dataclass(frozen=True)
class TextPlacement:
    target_id: str
    text: str
    x: float
    y: float
    anchor: str = "middle"


@dataclass(frozen=True)
class AngleLayout:
    angle_id: str
    radius: float
    label_x: float
    label_y: float
    visible: bool


@dataclass(frozen=True)
class ParallelMarkPlacement:
    line_id: str
    center_x: float
    center_y: float
    angle_deg: float
    count: int = 2


@dataclass(frozen=True)
class GeometryLayout:
    point_labels: list[TextPlacement]
    line_labels: list[TextPlacement]
    angle_layouts: dict[str, AngleLayout]
    parallel_marks: list[ParallelMarkPlacement]


def resolve_parallel_lines_angle_layout(diagram: GeometryDiagram) -> GeometryLayout:
    reserved_positions: list[tuple[float, float]] = []
    point_labels: list[TextPlacement] = []
    for point in diagram.points.values():
        if not point.visible or not point.label:
            continue
        dx = -14 if point.x < diagram.width / 2 else 10
        dy = -10 if point.y < diagram.height / 2 else 18
        x, y = _nudge_away_from_reserved(point.x + dx, point.y + dy, reserved_positions)
        point_labels.append(TextPlacement(target_id=point.id, text=point.label, x=x, y=y, anchor="start"))
        reserved_positions.append((x, y))

    line_labels: list[TextPlacement] = []
    for line in diagram.lines.values():
        if not line.label:
            continue
        x = line.p1[0] - 14
        y = line.p1[1] - 10
        x, y = _nudge_away_from_reserved(x, y, reserved_positions)
        line_labels.append(TextPlacement(target_id=line.id, text=line.label, x=x, y=y, anchor="middle"))
        reserved_positions.append((x, y))

    angle_layouts: dict[str, AngleLayout] = {}
    for vertex_id, grouped_angles in _group_angles_by_vertex(diagram.angles).items():
        visible_angles = resolve_multi_arc_at_same_vertex(grouped_angles)
        for index, angle in enumerate(visible_angles):
            point = diagram.points[vertex_id]
            radius = _radius_for_angle(angle, index)
            label_x, label_y = place_angle_label(point.x, point.y, angle, radius + 11.0, reserved_positions)
            angle_layouts[angle.id] = AngleLayout(
                angle_id=angle.id,
                radius=radius,
                label_x=label_x,
                label_y=label_y,
                visible=True,
            )
            reserved_positions.append((label_x, label_y))
        hidden_ids = {angle.id for angle in grouped_angles if angle.id not in {item.id for item in visible_angles}}
        for angle_id in hidden_ids:
            angle_layouts[angle_id] = AngleLayout(angle_id=angle_id, radius=0.0, label_x=0.0, label_y=0.0, visible=False)

    parallel_marks: list[ParallelMarkPlacement] = []
    for line in diagram.lines.values():
        if line.style != "parallel":
            continue
        center_x = (line.p1[0] + line.p2[0]) / 2
        center_y = (line.p1[1] + line.p2[1]) / 2
        parallel_marks.append(ParallelMarkPlacement(line_id=line.id, center_x=center_x, center_y=center_y, angle_deg=60.0, count=2))

    return GeometryLayout(
        point_labels=point_labels,
        line_labels=line_labels,
        angle_layouts=angle_layouts,
        parallel_marks=parallel_marks,
    )


def resolve_multi_arc_at_same_vertex(angles: list[GeometryAngle]) -> list[GeometryAngle]:
    visible = [angle for angle in angles if angle.visible and angle.show_arc]
    if not visible:
        return []
    has_primary = any(angle.angle_role in {"given", "unknown"} for angle in visible)
    filtered = [angle for angle in visible if angle.angle_role != "helper"] if has_primary else visible
    return sorted(filtered, key=_angle_sort_key)


def place_angle_label(
    cx: float,
    cy: float,
    angle: GeometryAngle,
    distance: float,
    reserved_positions: list[tuple[float, float]],
) -> tuple[float, float]:
    x = cx + math.cos(math.radians(angle.region_mid_direction)) * distance
    y = cy - math.sin(math.radians(angle.region_mid_direction)) * distance
    return _nudge_away_from_reserved(x, y, reserved_positions)


def _group_angles_by_vertex(angles: list[GeometryAngle]) -> dict[str, list[GeometryAngle]]:
    grouped: dict[str, list[GeometryAngle]] = {}
    for angle in angles:
        grouped.setdefault(angle.vertex_point_id, []).append(angle)
    return grouped


def _angle_sort_key(angle: GeometryAngle) -> tuple[int, int, str]:
    role_order = {"given": 0, "unknown": 1, "helper": 2}
    return (role_order.get(angle.angle_role, 3), -angle.render_priority, angle.id)


def _radius_for_angle(angle: GeometryAngle, index: int) -> float:
    role_base = {"given": 22.0, "unknown": 30.0, "helper": 38.0}.get(angle.angle_role, 26.0)
    return role_base + index * 4.0


def _nudge_away_from_reserved(x: float, y: float, reserved_positions: list[tuple[float, float]]) -> tuple[float, float]:
    adjusted_x, adjusted_y = x, y
    for _ in range(5):
        if all(math.hypot(adjusted_x - rx, adjusted_y - ry) >= 18 for rx, ry in reserved_positions):
            break
        adjusted_y += 10
        adjusted_x += 4
    return round(adjusted_x, 2), round(adjusted_y, 2)
