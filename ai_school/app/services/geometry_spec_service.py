from dataclasses import dataclass
import math


QUADRANT_ORDER = ("upper_left", "upper_right", "lower_right", "lower_left")


@dataclass(frozen=True)
class ParallelLineSpec:
    id: str
    y: float
    label: str | None = None


@dataclass(frozen=True)
class TransversalSpec:
    id: str
    x_top: float
    x_bottom: float


@dataclass(frozen=True)
class IntersectionSpec:
    id: str
    line_id: str
    transversal_id: str
    label: str | None = None


@dataclass(frozen=True)
class AngleSpec:
    id: str
    vertex: str
    ray1: str | None
    ray2: str | None
    value: str
    angle_role: str = "given"
    angle_side: str = "auto"
    relation_hint: str | None = None
    render_priority: int = 0
    visible: bool = True
    reference_angle_id: str | None = None
    show_arc: bool = True


@dataclass(frozen=True)
class ParallelLinesAngleSpec:
    diagram_type: str
    parallel_lines: list[ParallelLineSpec]
    transversal: TransversalSpec
    intersections: list[IntersectionSpec]
    angles: list[AngleSpec]



def parse_parallel_lines_angle_spec(diagram_params: dict, svg_size: int = 320) -> ParallelLinesAngleSpec | None:
    if not isinstance(diagram_params, dict):
        return None
    if "transversal" in diagram_params:
        return _parse_canonical_parallel_lines_angle(diagram_params)
    return _adapt_legacy_parallel_lines_angle(diagram_params, svg_size)



def _parse_canonical_parallel_lines_angle(diagram_params: dict) -> ParallelLinesAngleSpec | None:
    parallel_lines_raw = diagram_params.get("parallel_lines")
    transversal_raw = diagram_params.get("transversal")
    intersections_raw = diagram_params.get("intersections")
    angles_raw = diagram_params.get("angles")
    if not isinstance(parallel_lines_raw, list) or len(parallel_lines_raw) < 2:
        return None
    if not isinstance(transversal_raw, dict):
        return None
    if not isinstance(intersections_raw, list) or not isinstance(angles_raw, list):
        return None

    try:
        parallel_lines = [
            ParallelLineSpec(
                id=str(item.get("id") or f"l{index + 1}"),
                y=float(item["y"]),
                label=str(item.get("label") or "").strip() or None,
            )
            for index, item in enumerate(parallel_lines_raw[:2])
        ]
        transversal = TransversalSpec(
            id=str(transversal_raw.get("id") or "t1"),
            x_top=float(transversal_raw["x_top"]),
            x_bottom=float(transversal_raw["x_bottom"]),
        )
        intersections = [
            IntersectionSpec(
                id=str(item.get("id") or f"I{index + 1}"),
                line_id=str(item["line_id"]),
                transversal_id=str(item["transversal_id"]),
                label=str(item.get("label") or "").strip() or None,
            )
            for index, item in enumerate(intersections_raw)
        ]
        angles = [
            AngleSpec(
                id=str(item.get("id") or f"ang{index + 1}"),
                vertex=str(item["vertex"]),
                ray1=str(item.get("ray1")) if item.get("ray1") is not None else None,
                ray2=str(item.get("ray2")) if item.get("ray2") is not None else None,
                value=str(item.get("value") or item.get("label") or "?"),
                angle_role=str(item.get("angle_role") or ("unknown" if str(item.get("value") or item.get("label") or "?") == "?" else "given")),
                angle_side=str(item.get("angle_side") or "auto"),
                relation_hint=str(item.get("relation_hint")) if item.get("relation_hint") is not None else None,
                render_priority=int(item.get("render_priority", 0)),
                visible=bool(item.get("visible", True)),
                reference_angle_id=str(item.get("reference_angle_id")) if item.get("reference_angle_id") is not None else None,
                show_arc=bool(item.get("show_arc", True)),
            )
            for index, item in enumerate(angles_raw)
        ]
    except (KeyError, TypeError, ValueError):
        return None

    return ParallelLinesAngleSpec("parallel_lines_angle", parallel_lines, transversal, intersections, angles)



def _adapt_legacy_parallel_lines_angle(diagram_params: dict, svg_size: int) -> ParallelLinesAngleSpec | None:
    parallel_lines_raw = diagram_params.get("parallel_lines")
    transversals_raw = diagram_params.get("transversals")
    angle_marks = diagram_params.get("angle_marks")
    if not isinstance(parallel_lines_raw, list) or len(parallel_lines_raw) < 2:
        return None
    if not isinstance(transversals_raw, list) or not transversals_raw:
        return None
    if not isinstance(angle_marks, list) or not angle_marks:
        return None

    try:
        ordered_lines = sorted(parallel_lines_raw[:2], key=lambda item: float(item["y"]))
        parallel_lines = [
            ParallelLineSpec(
                id=f"l{index + 1}",
                y=float(item["y"]) / svg_size,
                label=str(item.get("label_left") or item.get("label") or "").strip() or None,
            )
            for index, item in enumerate(ordered_lines)
        ]
    except (KeyError, TypeError, ValueError):
        return None

    endpoints: list[tuple[float, float]] = []
    for line in transversals_raw:
        try:
            endpoints.append((float(line["x1"]), float(line["y1"])))
            endpoints.append((float(line["x2"]), float(line["y2"])))
        except (KeyError, TypeError, ValueError):
            return None
    top_endpoint = min(endpoints, key=lambda point: (point[1], point[0]))
    bottom_endpoint = max(endpoints, key=lambda point: (point[1], point[0]))
    if math.isclose(top_endpoint[1], bottom_endpoint[1]):
        return None

    top_y = parallel_lines[0].y * svg_size
    bottom_y = parallel_lines[1].y * svg_size
    x_top = _interpolate_x_at_y(top_endpoint, bottom_endpoint, top_y) / svg_size
    x_bottom = _interpolate_x_at_y(top_endpoint, bottom_endpoint, bottom_y) / svg_size
    transversal = TransversalSpec(id="t1", x_top=x_top, x_bottom=x_bottom)

    intersection_positions = {"A": (x_top * svg_size, top_y), "B": (x_bottom * svg_size, bottom_y)}
    legacy_points = diagram_params.get("points") if isinstance(diagram_params.get("points"), list) else []
    intersections = [
        IntersectionSpec(id="A", line_id="l1", transversal_id="t1", label=_nearest_point_label(legacy_points, intersection_positions["A"]) or "A"),
        IntersectionSpec(id="B", line_id="l2", transversal_id="t1", label=_nearest_point_label(legacy_points, intersection_positions["B"]) or "B"),
    ]

    ray_candidates = _build_parallel_ray_candidates(parallel_lines, transversal, svg_size)
    angles: list[AngleSpec] = []
    for index, mark in enumerate(angle_marks, start=1):
        angle = _legacy_mark_to_angle_spec(mark, intersection_positions, ray_candidates, index)
        if angle is not None:
            angles.append(angle)
    if not angles:
        return None

    return ParallelLinesAngleSpec("parallel_lines_angle", parallel_lines, transversal, intersections, angles)



def _interpolate_x_at_y(p1: tuple[float, float], p2: tuple[float, float], y_target: float) -> float:
    x1, y1 = p1
    x2, y2 = p2
    ratio = (y_target - y1) / (y2 - y1)
    return x1 + (x2 - x1) * ratio



def _nearest_point_label(points: list[dict], target: tuple[float, float], tolerance: float = 18.0) -> str | None:
    best_label = None
    best_distance = tolerance
    for point in points:
        try:
            x = float(point["x"])
            y = float(point["y"])
        except (KeyError, TypeError, ValueError):
            continue
        name = str(point.get("name") or "").strip()
        if not name:
            continue
        distance = math.hypot(x - target[0], y - target[1])
        if distance <= best_distance:
            best_distance = distance
            best_label = name
    return best_label



def _build_parallel_ray_candidates(parallel_lines: list[ParallelLineSpec], transversal: TransversalSpec, svg_size: int) -> dict[str, dict[str, float]]:
    top_y = parallel_lines[0].y * svg_size
    bottom_y = parallel_lines[1].y * svg_size
    top_point = (transversal.x_top * svg_size, top_y)
    bottom_point = (transversal.x_bottom * svg_size, bottom_y)
    top_to_bottom_angle = _angle_deg(top_point, bottom_point)
    bottom_to_top_angle = _angle_deg(bottom_point, top_point)
    top_direction = _direction_token((bottom_point[0] - top_point[0], bottom_point[1] - top_point[1]))
    bottom_direction = _direction_token((top_point[0] - bottom_point[0], top_point[1] - bottom_point[1]))
    return {
        "A": {
            f"{parallel_lines[0].id}:left": 180.0,
            f"{parallel_lines[0].id}:right": 0.0,
            f"{transversal.id}:{top_direction}": top_to_bottom_angle,
            f"{transversal.id}:{_opposite_direction(top_direction)}": bottom_to_top_angle,
        },
        "B": {
            f"{parallel_lines[1].id}:left": 180.0,
            f"{parallel_lines[1].id}:right": 0.0,
            f"{transversal.id}:{bottom_direction}": bottom_to_top_angle,
            f"{transversal.id}:{_opposite_direction(bottom_direction)}": top_to_bottom_angle,
        },
    }



def _legacy_mark_to_angle_spec(mark: dict, intersection_positions: dict[str, tuple[float, float]], ray_candidates: dict[str, dict[str, float]], index: int) -> AngleSpec | None:
    vertex = mark.get("vertex")
    if not isinstance(vertex, dict):
        return None
    try:
        vx = float(vertex["x"])
        vy = float(vertex["y"])
    except (KeyError, TypeError, ValueError):
        return None

    vertex_id = min(intersection_positions, key=lambda item: math.hypot(vx - intersection_positions[item][0], vy - intersection_positions[item][1]))
    candidates = ray_candidates.get(vertex_id, {})
    if len(candidates) < 4:
        return None

    from_hint = float(mark.get("from_deg", 0.0))
    to_hint = float(mark.get("to_deg", 90.0))
    best_pair: tuple[str, str] | None = None
    best_score: float | None = None
    for ray1, angle1 in candidates.items():
        for ray2, angle2 in candidates.items():
            if ray1 == ray2 or ray1.split(":", 1)[0] == ray2.split(":", 1)[0]:
                continue
            ordered = _circular_distance(angle1, from_hint) + _circular_distance(angle2, to_hint)
            swapped = _circular_distance(angle1, to_hint) + _circular_distance(angle2, from_hint)
            score = min(ordered, swapped)
            if best_score is None or score < best_score:
                best_score = score
                best_pair = (ray1, ray2)
    if best_pair is None:
        return None

    region_map = _build_region_map(candidates)
    inferred_side = _region_from_pair(region_map, best_pair) or "auto"
    value = str(mark.get("label") or mark.get("value") or "?")
    angle_role = "unknown" if "?" in value else "given"
    return AngleSpec(
        id=f"ang{index}",
        vertex=vertex_id,
        ray1=best_pair[0],
        ray2=best_pair[1],
        value=value,
        angle_role=angle_role,
        angle_side=inferred_side,
        relation_hint=None,
        render_priority=0 if angle_role == "unknown" else 1,
        visible=True,
        reference_angle_id=None,
        show_arc=bool(mark.get("show_arc", True)),
    )



def _build_region_map(candidates: dict[str, float]) -> dict[str, tuple[str, str]]:
    ordered = sorted(candidates.items(), key=lambda item: item[1])
    regions: dict[str, tuple[str, str]] = {}
    for index, (token_a, angle_a) in enumerate(ordered):
        token_b, angle_b = ordered[(index + 1) % len(ordered)]
        delta = (angle_b - angle_a) % 360.0
        mid_angle = (angle_a + delta / 2.0) % 360.0
        regions[_quadrant_from_angle(mid_angle)] = (token_a, token_b)
    return regions



def _region_from_pair(region_map: dict[str, tuple[str, str]], pair: tuple[str, str]) -> str | None:
    expected = {pair[0], pair[1]}
    for region, tokens in region_map.items():
        if set(tokens) == expected:
            return region
    return None



def _quadrant_from_angle(angle: float) -> str:
    normalized = angle % 360.0
    if 90.0 <= normalized < 180.0:
        return "upper_left"
    if 0.0 <= normalized < 90.0:
        return "upper_right"
    if 270.0 <= normalized < 360.0:
        return "lower_right"
    return "lower_left"



def _direction_token(vector: tuple[float, float]) -> str:
    dx, dy = vector
    vertical = "up" if dy < 0 else "down"
    horizontal = "left" if dx < 0 else "right"
    return f"{vertical}_{horizontal}"



def _opposite_direction(token: str) -> str:
    vertical, horizontal = token.split("_", 1)
    return f'{"down" if vertical == "up" else "up"}_{"right" if horizontal == "left" else "left"}'



def _angle_deg(origin: tuple[float, float], target: tuple[float, float]) -> float:
    dx = target[0] - origin[0]
    dy = origin[1] - target[1]
    return math.degrees(math.atan2(dy, dx)) % 360.0



def _circular_distance(a: float, b: float) -> float:
    diff = abs((a % 360.0) - (b % 360.0))
    return min(diff, 360.0 - diff)


# ---------------------------------------------------------------------------
# CircleInscribedAngle spec  (新パイプライン)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CircleAngleMark:
    vertex: str
    from_point: str
    to_point: str
    value: str
    angle_role: str = "given"   # "given" | "unknown" | "helper"
    radius: float = 22.0


@dataclass(frozen=True)
class CircleInscribedAngleSpec:
    diagram_type: str
    center: tuple[float, float]
    radius: float
    center_label: str
    points: dict[str, tuple[float, float]]     # name → (x, y)
    point_defs: dict[str, dict]                # name → raw dict with label_dx/dy
    segments: list[tuple[str, str]]
    angle_marks: list[CircleAngleMark]


def parse_circle_inscribed_angle_spec(diagram_params: dict, svg_size: int = 320) -> CircleInscribedAngleSpec | None:
    """diagram_params を CircleInscribedAngleSpec に変換する。"""
    points_data = diagram_params.get("points")
    if not isinstance(points_data, list) or len(points_data) < 3:
        return None

    center = (svg_size / 2.0, svg_size / 2.0)
    radius = float(diagram_params.get("circle", {}).get("radius", 108))
    center_label = str(diagram_params.get("circle", {}).get("center_label", "O")).strip() or "O"

    points_by_name: dict[str, tuple[float, float]] = {}
    point_defs: dict[str, dict] = {}
    for item in points_data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        angle_deg = item.get("angle_deg")
        if not name or angle_deg is None:
            continue
        theta = math.radians(float(angle_deg))
        x = round(center[0] + radius * math.cos(theta), 2)
        y = round(center[1] - radius * math.sin(theta), 2)
        points_by_name[name] = (x, y)
        point_defs[name] = item

    if len(points_by_name) < 3:
        return None

    segments: list[tuple[str, str]] = []
    for item in diagram_params.get("segments", []):
        if isinstance(item, list) and len(item) == 2:
            a, b = str(item[0]), str(item[1])
            if a in points_by_name and b in points_by_name:
                segments.append((a, b))

    angle_marks: list[CircleAngleMark] = []
    for mark in diagram_params.get("angle_marks", []):
        if not isinstance(mark, dict):
            continue
        vertex = str(mark.get("vertex") or "").strip()
        from_p = str(mark.get("from") or mark.get("from_point") or "").strip()
        to_p = str(mark.get("to") or mark.get("to_point") or "").strip()
        raw_value = str(mark.get("label") or mark.get("value") or "?").strip()
        value = "?" if raw_value == "?" else raw_value
        angle_role = "unknown" if value == "?" else "given"
        radius_mark = float(mark.get("radius", 28 if value == "?" else 22))
        all_names = set(points_by_name) | {center_label}
        if vertex in all_names and from_p in all_names and to_p in all_names:
            angle_marks.append(CircleAngleMark(
                vertex=vertex, from_point=from_p, to_point=to_p,
                value=value, angle_role=angle_role, radius=radius_mark,
            ))

    return CircleInscribedAngleSpec(
        diagram_type="circle_inscribed_angle",
        center=center, radius=radius, center_label=center_label,
        points=points_by_name, point_defs=point_defs,
        segments=segments, angle_marks=angle_marks,
    )


# ---------------------------------------------------------------------------
# TriangleCorrespondence / SimilarTriangles spec  (新パイプライン)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TrianglePointSpec:
    name: str
    x: float
    y: float
    label_dx: float = 8.0
    label_dy: float = -8.0


@dataclass(frozen=True)
class TriangleDef:
    points: list[TrianglePointSpec]


@dataclass(frozen=True)
class EqualSideMark:
    p1: str
    p2: str
    count: int = 1


@dataclass(frozen=True)
class EqualAngleMark:
    vertex: str
    ray1: str
    ray2: str
    count: int = 1
    angle_role: str = "given"


@dataclass(frozen=True)
class SideLabelSpec:
    p1: str
    p2: str
    value: str


@dataclass(frozen=True)
class TriangleCorrespondenceSpec:
    diagram_type: str
    subtype: str        # "congruent_triangle_intro" | "congruent_triangle_with_marks" | "crossing_segments"
    triangles: list[TriangleDef]
    points: dict[str, tuple[float, float]]
    point_defs: dict[str, dict]
    equal_sides: list[list[EqualSideMark]]
    equal_angles: list[list[EqualAngleMark]]
    highlight_pairs: list[tuple[str, str]]


@dataclass(frozen=True)
class SimilarTrianglesSpec:
    diagram_type: str
    subtype: str        # "comparison_pair" | "parallel_cut" | "crossing_segments"
    triangles: list[TriangleDef]
    points: dict[str, tuple[float, float]]
    point_defs: dict[str, dict]
    equal_angles: list[list[EqualAngleMark]]
    parallel_marks: list[list[EqualSideMark]]
    side_labels: list[SideLabelSpec]


def _parse_triangles_from_params(diagram_params: dict) -> tuple[list[TriangleDef], dict[str, tuple[float, float]], dict[str, dict]] | None:
    """diagram_params["triangles"] を TriangleDef リストに変換する共通処理。"""
    triangles_raw = diagram_params.get("triangles")
    if not isinstance(triangles_raw, list) or len(triangles_raw) < 2:
        return None
    triangle_defs: list[TriangleDef] = []
    points_by_name: dict[str, tuple[float, float]] = {}
    point_defs: dict[str, dict] = {}
    for tri_raw in triangles_raw[:2]:
        if not isinstance(tri_raw, dict):
            return None
        pts_raw = tri_raw.get("points")
        if not isinstance(pts_raw, list) or len(pts_raw) < 3:
            return None
        tri_points: list[TrianglePointSpec] = []
        for p in pts_raw[:3]:
            if not isinstance(p, dict):
                return None
            name = str(p.get("name") or "").strip()
            x = p.get("x")
            y = p.get("y")
            if not name or x is None or y is None:
                return None
            tri_points.append(TrianglePointSpec(
                name=name, x=float(x), y=float(y),
                label_dx=float(p.get("label_dx", 8)),
                label_dy=float(p.get("label_dy", -8)),
            ))
            points_by_name[name] = (float(x), float(y))
            point_defs[name] = p
        triangle_defs.append(TriangleDef(points=tri_points))
    return triangle_defs, points_by_name, point_defs


def _parse_equal_sides(raw: list) -> list[list[EqualSideMark]]:
    result: list[list[EqualSideMark]] = []
    for index, group in enumerate(raw, start=1):
        if not isinstance(group, list):
            continue
        marks = []
        for pair in group:
            if isinstance(pair, list) and len(pair) == 2:
                marks.append(EqualSideMark(p1=str(pair[0]), p2=str(pair[1]), count=index))
        if marks:
            result.append(marks)
    return result


def _parse_equal_angles(raw: list) -> list[list[EqualAngleMark]]:
    result: list[list[EqualAngleMark]] = []
    for index, group in enumerate(raw, start=1):
        if not isinstance(group, list):
            continue
        marks = []
        for triple in group:
            if isinstance(triple, list) and len(triple) == 3:
                v, r1, r2 = str(triple[0]), str(triple[1]), str(triple[2])
                marks.append(EqualAngleMark(vertex=v, ray1=r1, ray2=r2, count=index))
            elif isinstance(triple, dict):
                v = str(triple.get("vertex") or "").strip()
                r1 = str(triple.get("ray1") or triple.get("from") or "").strip()
                r2 = str(triple.get("ray2") or triple.get("to") or "").strip()
                if v and r1 and r2:
                    marks.append(EqualAngleMark(vertex=v, ray1=r1, ray2=r2, count=index))
        if marks:
            result.append(marks)
    return result


def _parse_side_labels(raw: list) -> list[SideLabelSpec]:
    labels: list[SideLabelSpec] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        p1 = str(item.get("from") or item.get("p1") or "").strip()
        p2 = str(item.get("to") or item.get("p2") or "").strip()
        value = str(item.get("label") or item.get("value") or "").strip()
        if p1 and p2 and value:
            labels.append(SideLabelSpec(p1=p1, p2=p2, value=value))
    return labels


def _infer_triangle_subtype(diagram_params: dict) -> str:
    explicit = str(diagram_params.get("subtype") or "").strip()
    if explicit:
        return explicit
    triangles = diagram_params.get("triangles")
    if isinstance(triangles, list):
        all_names: list[str] = []
        for t in triangles[:2]:
            if isinstance(t, dict):
                for p in (t.get("points") or []):
                    if isinstance(p, dict):
                        all_names.append(str(p.get("name") or ""))
        # 末尾に '数字' が付いているラベルを crossing_segments と判断
        if any(name[-1].isdigit() for name in all_names if name):
            return "crossing_segments"
    if diagram_params.get("equal_sides") or diagram_params.get("equal_angles"):
        return "congruent_triangle_with_marks"
    return "congruent_triangle_intro"


def _infer_similarity_subtype(diagram_params: dict) -> str:
    explicit = str(diagram_params.get("subtype") or diagram_params.get("relation_type") or "").strip()
    if explicit in {"parallel_cut", "crossing_segments", "comparison_pair"}:
        return explicit
    if diagram_params.get("parallel_marks"):
        return "parallel_cut"
    triangles = diagram_params.get("triangles")
    if isinstance(triangles, list):
        all_names: list[str] = []
        for t in triangles[:2]:
            if isinstance(t, dict):
                for p in (t.get("points") or []):
                    if isinstance(p, dict):
                        all_names.append(str(p.get("name") or ""))
        # 共有頂点がある → parallel_cut
        from collections import Counter
        name_counts = Counter(all_names)
        if any(v >= 2 for v in name_counts.values()):
            return "parallel_cut"
        if any(name[-1].isdigit() for name in all_names if name):
            return "crossing_segments"
    return "comparison_pair"


def parse_triangle_correspondence_spec(diagram_params: dict) -> TriangleCorrespondenceSpec | None:
    parsed = _parse_triangles_from_params(diagram_params)
    if parsed is None:
        return None
    triangle_defs, points_by_name, point_defs = parsed
    subtype = _infer_triangle_subtype(diagram_params)
    equal_sides = _parse_equal_sides(diagram_params.get("equal_sides", []))
    equal_angles = _parse_equal_angles(diagram_params.get("equal_angles", []))
    highlight_pairs: list[tuple[str, str]] = []
    for pair in diagram_params.get("highlight_pairs", []):
        if isinstance(pair, list) and len(pair) == 2:
            highlight_pairs.append((str(pair[0]), str(pair[1])))
    return TriangleCorrespondenceSpec(
        diagram_type="triangle_correspondence",
        subtype=subtype,
        triangles=triangle_defs,
        points=points_by_name,
        point_defs=point_defs,
        equal_sides=equal_sides,
        equal_angles=equal_angles,
        highlight_pairs=highlight_pairs,
    )


def parse_similar_triangles_spec(diagram_params: dict) -> SimilarTrianglesSpec | None:
    parsed = _parse_triangles_from_params(diagram_params)
    if parsed is None:
        return None
    triangle_defs, points_by_name, point_defs = parsed
    subtype = _infer_similarity_subtype(diagram_params)
    equal_angles = _parse_equal_angles(diagram_params.get("equal_angles", []))
    parallel_marks = _parse_equal_sides(diagram_params.get("parallel_marks", []))
    side_labels = _parse_side_labels(diagram_params.get("side_labels", []))
    return SimilarTrianglesSpec(
        diagram_type="similar_triangles_basic",
        subtype=subtype,
        triangles=triangle_defs,
        points=points_by_name,
        point_defs=point_defs,
        equal_angles=equal_angles,
        parallel_marks=parallel_marks,
        side_labels=side_labels,
    )

