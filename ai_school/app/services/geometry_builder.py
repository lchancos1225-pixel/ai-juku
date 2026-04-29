from dataclasses import dataclass
import math

from .geometry_spec_service import ParallelLinesAngleSpec, QUADRANT_ORDER


VERTICAL_OPPOSITE = {
    "upper_left": "lower_right",
    "upper_right": "lower_left",
    "lower_right": "upper_left",
    "lower_left": "upper_right",
}

CLOCKWISE_ADJACENT = {
    "upper_left": "upper_right",
    "upper_right": "lower_right",
    "lower_right": "lower_left",
    "lower_left": "upper_left",
}

COUNTERCLOCKWISE_ADJACENT = {value: key for key, value in CLOCKWISE_ADJACENT.items()}


@dataclass(frozen=True)
class GeometryPoint:
    id: str
    x: float
    y: float
    visible: bool
    label: str | None = None


@dataclass(frozen=True)
class GeometryLine:
    id: str
    kind: str
    p1: tuple[float, float]
    p2: tuple[float, float]
    visible: bool
    label: str | None = None
    style: str | None = None


@dataclass(frozen=True)
class GeometryIntersection:
    id: str
    point_id: str
    line_a: str
    line_b: str


@dataclass(frozen=True)
class GeometryAngle:
    id: str
    vertex_point_id: str
    ray_a_token: str
    ray_b_token: str
    ray_a_direction: float
    ray_b_direction: float
    selected_region: str
    region_mid_direction: float
    region_span: float
    value: str
    angle_role: str
    angle_side: str
    relation_hint: str | None
    render_priority: int
    visible: bool
    show_arc: bool


@dataclass(frozen=True)
class GeometryDiagram:
    width: int
    height: int
    points: dict[str, GeometryPoint]
    lines: dict[str, GeometryLine]
    intersections: dict[str, GeometryIntersection]
    angles: list[GeometryAngle]


@dataclass(frozen=True)
class _AngleContext:
    angle_id: str
    vertex_id: str
    candidate_directions: dict[str, float]
    region_map: dict[str, tuple[str, str]]
    region_midpoints: dict[str, float]
    line_id: str
    transversal_id: str


def build_parallel_lines_angle_geometry(
    spec: ParallelLinesAngleSpec,
    *,
    width: int = 320,
    height: int = 320,
    horizontal_margin: float = 36.0,
    vertical_margin: float = 28.0,
) -> GeometryDiagram | None:
    if len(spec.parallel_lines) < 2:
        return None

    sorted_lines = sorted(spec.parallel_lines, key=lambda item: item.y)
    top_line_spec, bottom_line_spec = sorted_lines[:2]
    top_y = top_line_spec.y * height
    bottom_y = bottom_line_spec.y * height
    if math.isclose(top_y, bottom_y):
        return None

    top_intersection = (spec.transversal.x_top * width, top_y)
    bottom_intersection = (spec.transversal.x_bottom * width, bottom_y)
    trans_start = _project_line_to_y(top_intersection, bottom_intersection, vertical_margin)
    trans_end = _project_line_to_y(top_intersection, bottom_intersection, height - vertical_margin)

    lines = {
        top_line_spec.id: GeometryLine(
            id=top_line_spec.id,
            kind="infinite_line",
            p1=(horizontal_margin, top_y),
            p2=(width - horizontal_margin, top_y),
            visible=True,
            label=top_line_spec.label,
            style="parallel",
        ),
        bottom_line_spec.id: GeometryLine(
            id=bottom_line_spec.id,
            kind="infinite_line",
            p1=(horizontal_margin, bottom_y),
            p2=(width - horizontal_margin, bottom_y),
            visible=True,
            label=bottom_line_spec.label,
            style="parallel",
        ),
        spec.transversal.id: GeometryLine(
            id=spec.transversal.id,
            kind="segment",
            p1=trans_start,
            p2=trans_end,
            visible=True,
            label=None,
            style="transversal",
        ),
    }

    points: dict[str, GeometryPoint] = {}
    intersections: dict[str, GeometryIntersection] = {}
    vertex_positions: dict[str, tuple[float, float]] = {}
    for intersection_spec in spec.intersections:
        base_line = lines.get(intersection_spec.line_id)
        transversal = lines.get(intersection_spec.transversal_id)
        if base_line is None or transversal is None:
            return None
        point = _line_intersection(base_line.p1, base_line.p2, transversal.p1, transversal.p2)
        if point is None:
            return None
        vertex_positions[intersection_spec.id] = point
        points[intersection_spec.id] = GeometryPoint(
            id=intersection_spec.id,
            x=point[0],
            y=point[1],
            visible=True,
            label=intersection_spec.label,
        )
        intersections[intersection_spec.id] = GeometryIntersection(
            id=intersection_spec.id,
            point_id=intersection_spec.id,
            line_a=intersection_spec.line_id,
            line_b=intersection_spec.transversal_id,
        )

    contexts = _build_angle_contexts(lines, vertex_positions, top_line_spec.id, bottom_line_spec.id, spec.transversal.id)
    if contexts is None:
        return None

    spec_by_id = {angle.id: angle for angle in spec.angles}
    resolved_regions: dict[str, str] = {}
    unresolved = list(spec.angles)
    angles: list[GeometryAngle] = []

    for _ in range(max(len(unresolved), 1) * 2):
        if not unresolved:
            break
        pending: list = []
        progress = False
        for angle_spec in unresolved:
            context = contexts.get(angle_spec.vertex)
            if context is None:
                return None
            region = choose_angle_region(angle_spec, context, spec_by_id, resolved_regions, points)
            if region is None:
                pending.append(angle_spec)
                continue
            geometry_angle = _build_geometry_angle(angle_spec, context, region)
            if geometry_angle is None:
                return None
            angles.append(geometry_angle)
            resolved_regions[angle_spec.id] = region
            progress = True
        if not progress:
            for angle_spec in pending:
                context = contexts.get(angle_spec.vertex)
                if context is None:
                    return None
                region = _fallback_region(angle_spec, context)
                geometry_angle = _build_geometry_angle(angle_spec, context, region)
                if geometry_angle is None:
                    return None
                angles.append(geometry_angle)
                resolved_regions[angle_spec.id] = region
            pending = []
        unresolved = pending

    angles.sort(key=lambda item: (item.vertex_point_id, -item.render_priority, item.id))
    return GeometryDiagram(
        width=width,
        height=height,
        points=points,
        lines=lines,
        intersections=intersections,
        angles=angles,
    )


def choose_angle_region(angle_spec, context: _AngleContext, spec_by_id: dict, resolved_regions: dict[str, str], points: dict[str, GeometryPoint]) -> str | None:
    if angle_spec.angle_side in context.region_map:
        return angle_spec.angle_side

    pair_region = _region_from_pair(context.region_map, angle_spec.ray1, angle_spec.ray2)
    if pair_region is not None:
        return pair_region

    if angle_spec.relation_hint:
        region = _resolve_relation_region(angle_spec, context, spec_by_id, resolved_regions, points)
        if region is not None:
            return region

    if angle_spec.angle_role == "helper" and pair_region is not None:
        return pair_region

    return _fallback_region(angle_spec, context)


def _fallback_region(angle_spec, context: _AngleContext) -> str:
    if angle_spec.angle_side in QUADRANT_ORDER:
        return angle_spec.angle_side
    pair_region = _region_from_pair(context.region_map, angle_spec.ray1, angle_spec.ray2)
    if pair_region is not None:
        return pair_region
    if angle_spec.angle_role == "unknown":
        return "upper_left" if "upper_left" in context.region_map else next(iter(context.region_map))
    return next(iter(context.region_map))


def _build_geometry_angle(angle_spec, context: _AngleContext, region: str) -> GeometryAngle | None:
    pair = context.region_map.get(region)
    if pair is None:
        return None
    ray_a_token, ray_b_token = pair
    ray_a_direction = context.candidate_directions[ray_a_token]
    ray_b_direction = context.candidate_directions[ray_b_token]
    span = (ray_b_direction - ray_a_direction) % 360.0
    return GeometryAngle(
        id=angle_spec.id,
        vertex_point_id=angle_spec.vertex,
        ray_a_token=ray_a_token,
        ray_b_token=ray_b_token,
        ray_a_direction=ray_a_direction,
        ray_b_direction=ray_b_direction,
        selected_region=region,
        region_mid_direction=context.region_midpoints[region],
        region_span=span,
        value=angle_spec.value,
        angle_role=angle_spec.angle_role,
        angle_side=angle_spec.angle_side,
        relation_hint=angle_spec.relation_hint,
        render_priority=angle_spec.render_priority,
        visible=angle_spec.visible,
        show_arc=angle_spec.show_arc,
    )


def _resolve_relation_region(angle_spec, context: _AngleContext, spec_by_id: dict, resolved_regions: dict[str, str], points: dict[str, GeometryPoint]) -> str | None:
    reference_id = angle_spec.reference_angle_id
    relation = angle_spec.relation_hint
    if not reference_id or relation is None:
        return None
    reference_region = resolved_regions.get(reference_id)
    reference_spec = spec_by_id.get(reference_id)
    if reference_region is None or reference_spec is None:
        return None

    if relation == "corresponding":
        return reference_region if reference_region in context.region_map else None
    if relation == "vertical":
        candidate = VERTICAL_OPPOSITE.get(reference_region)
        return candidate if candidate in context.region_map else None
    if relation == "linear_pair":
        candidate = _linear_pair_region(reference_spec.vertex, angle_spec.vertex, reference_region, context, points)
        return candidate if candidate in context.region_map else None
    if relation in {"alternate_interior", "alternate_exterior", "same_side_interior"}:
        candidate = _parallel_relation_region(reference_spec.vertex, angle_spec.vertex, reference_region, relation, context, points)
        return candidate if candidate in context.region_map else None
    return None


def _linear_pair_region(reference_vertex: str, target_vertex: str, reference_region: str, context: _AngleContext, points: dict[str, GeometryPoint]) -> str:
    if reference_vertex != target_vertex:
        return reference_region
    target_point = points[target_vertex]
    moving_down = context.candidate_directions[context.ray_a_token if False else next(iter(context.candidate_directions))] >= 0
    del moving_down, target_point
    return CLOCKWISE_ADJACENT.get(reference_region, reference_region)


def _parallel_relation_region(reference_vertex: str, target_vertex: str, reference_region: str, relation: str, context: _AngleContext, points: dict[str, GeometryPoint]) -> str | None:
    reference_point = points.get(reference_vertex)
    target_point = points.get(target_vertex)
    if reference_point is None or target_point is None:
        return None
    ref_meta = _region_metadata(reference_point, context.region_midpoints[reference_region], context.candidate_directions, context.transversal_id)
    if ref_meta is None:
        return None
    candidates: list[str] = []
    for region in QUADRANT_ORDER:
        if region not in context.region_map:
            continue
        candidate_meta = _region_metadata(target_point, context.region_midpoints[region], context.candidate_directions, context.transversal_id)
        if candidate_meta is None:
            continue
        if relation == "alternate_interior":
            matches = candidate_meta["vertical_band"] == "interior" and candidate_meta["transversal_side"] != ref_meta["transversal_side"]
        elif relation == "alternate_exterior":
            matches = candidate_meta["vertical_band"] == "exterior" and candidate_meta["transversal_side"] != ref_meta["transversal_side"]
        else:
            matches = candidate_meta["vertical_band"] == "interior" and candidate_meta["transversal_side"] == ref_meta["transversal_side"]
        if matches:
            candidates.append(region)
    if not candidates:
        return None
    if reference_region in candidates:
        return reference_region
    return candidates[0]


def _region_metadata(point: GeometryPoint, mid_direction: float, candidate_directions: dict[str, float], transversal_id: str) -> dict[str, str] | None:
    mid_rad = math.radians(mid_direction)
    sample_dx = math.cos(mid_rad)
    sample_dy = -math.sin(mid_rad)
    sample_x = point.x + sample_dx * 16.0
    sample_y = point.y + sample_dy * 16.0
    vertical_band = "interior" if sample_y > point.y else "exterior"
    if point.id == "B":
        vertical_band = "interior" if sample_y < point.y else "exterior"

    trans_down_token = next((token for token in candidate_directions if token.startswith(f"{transversal_id}:down_")), None)
    if trans_down_token is None:
        return None
    trans_angle = math.radians(candidate_directions[trans_down_token])
    trans_dx = math.cos(trans_angle)
    trans_dy = -math.sin(trans_angle)
    cross = trans_dx * (sample_y - point.y) - trans_dy * (sample_x - point.x)
    transversal_side = "left" if cross > 0 else "right"
    return {"vertical_band": vertical_band, "transversal_side": transversal_side}


def _build_angle_contexts(
    lines: dict[str, GeometryLine],
    vertex_positions: dict[str, tuple[float, float]],
    top_line_id: str,
    bottom_line_id: str,
    transversal_id: str,
) -> dict[str, _AngleContext] | None:
    ray_map = _build_parallel_ray_map(lines, vertex_positions, top_line_id, bottom_line_id, transversal_id)
    contexts: dict[str, _AngleContext] = {}
    for vertex_id, candidate_directions in ray_map.items():
        region_map, midpoints = _build_region_map(candidate_directions)
        line_id = top_line_id if vertex_id == "A" else bottom_line_id
        contexts[vertex_id] = _AngleContext(
            angle_id=vertex_id,
            vertex_id=vertex_id,
            candidate_directions=candidate_directions,
            region_map=region_map,
            region_midpoints=midpoints,
            line_id=line_id,
            transversal_id=transversal_id,
        )
    return contexts


def _project_line_to_y(p1: tuple[float, float], p2: tuple[float, float], y_target: float) -> tuple[float, float]:
    x1, y1 = p1
    x2, y2 = p2
    if math.isclose(y1, y2):
        return x1, y_target
    ratio = (y_target - y1) / (y2 - y1)
    return round(x1 + (x2 - x1) * ratio, 2), round(y_target, 2)


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


def _build_parallel_ray_map(
    lines: dict[str, GeometryLine],
    vertex_positions: dict[str, tuple[float, float]],
    top_line_id: str,
    bottom_line_id: str,
    transversal_id: str,
) -> dict[str, dict[str, float]]:
    top_point = vertex_positions.get("A")
    bottom_point = vertex_positions.get("B")
    if top_point is None or bottom_point is None:
        top_point, bottom_point = list(vertex_positions.values())[:2]
    down_angle = _angle_deg(top_point, bottom_point)
    up_angle = _angle_deg(bottom_point, top_point)
    top_down_token = _direction_token((bottom_point[0] - top_point[0], bottom_point[1] - top_point[1]))
    bottom_up_token = _direction_token((top_point[0] - bottom_point[0], top_point[1] - bottom_point[1]))
    return {
        "A": {
            f"{top_line_id}:left": 180.0,
            f"{top_line_id}:right": 0.0,
            f"{transversal_id}:{top_down_token}": down_angle,
            f"{transversal_id}:{_opposite_direction(top_down_token)}": up_angle,
        },
        "B": {
            f"{bottom_line_id}:left": 180.0,
            f"{bottom_line_id}:right": 0.0,
            f"{transversal_id}:{bottom_up_token}": up_angle,
            f"{transversal_id}:{_opposite_direction(bottom_up_token)}": down_angle,
        },
    }


def _build_region_map(candidates: dict[str, float]) -> tuple[dict[str, tuple[str, str]], dict[str, float]]:
    ordered = sorted(candidates.items(), key=lambda item: item[1])
    regions: dict[str, tuple[str, str]] = {}
    midpoints: dict[str, float] = {}
    for index, (token_a, angle_a) in enumerate(ordered):
        token_b, angle_b = ordered[(index + 1) % len(ordered)]
        delta = (angle_b - angle_a) % 360.0
        mid_angle = (angle_a + delta / 2.0) % 360.0
        region = _quadrant_from_angle(mid_angle)
        regions[region] = (token_a, token_b)
        midpoints[region] = mid_angle
    return regions, midpoints


def _region_from_pair(region_map: dict[str, tuple[str, str]], ray1: str | None, ray2: str | None) -> str | None:
    if not ray1 or not ray2:
        return None
    expected = {ray1, ray2}
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
