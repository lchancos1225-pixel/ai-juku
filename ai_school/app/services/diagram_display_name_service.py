from __future__ import annotations

from typing import Any


DIAGRAM_TYPE_DISPLAY_NAMES = {
    "linear_function_graph": "\u4e00\u6b21\u95a2\u6570\u306e\u30b0\u30e9\u30d5",
    "two_lines_and_y_axis": "2\u76f4\u7dda\u306e\u30b0\u30e9\u30d5",
    "line_axes_triangle": "\u30b0\u30e9\u30d5\u3068\u4e09\u89d2\u5f62",
    "circle_inscribed_angle": "\u5186\u3068\u89d2",
    "parallel_lines_angle": "\u5e73\u884c\u7dda\u3068\u89d2",
    "triangle_correspondence": "\u4e09\u89d2\u5f62\u306e\u5bfe\u5fdc",
    "similar_triangles_basic": "\u76f8\u4f3c\u306e\u56f3",
}

UNIT_DISPLAY_NAMES = {
    "geometry_parallel_congruence": "\u5e73\u884c\u7dda\u30fb\u5408\u540c\u306e\u56f3",
    "geometry_similarity": "\u76f8\u4f3c\u306e\u56f3",
    "circles_angles": "\u5186\u3068\u89d2",
    "linear_function": "\u4e00\u6b21\u95a2\u6570\u306e\u56f3",
    "linear_function_graph": "\u4e00\u6b21\u95a2\u6570\u306e\u30b0\u30e9\u30d5",
}

SUBTYPE_DISPLAY_NAMES = {
    ("geometry_similarity", "parallel_cut"): "\u76f8\u4f3c\u306e\u56f3\uff08\u5e73\u884c\u7dda\u3067\u5207\u308b\uff09",
    ("geometry_similarity", "crossing_segments"): "\u76f8\u4f3c\u306e\u56f3\uff08\u4ea4\u5dee\u3059\u308b\u7dda\u5206\uff09",
    ("geometry_parallel_congruence", "parallel_angle_reasoning"): "\u5e73\u884c\u7dda\u3068\u89d2",
    ("geometry_parallel_congruence", "triangle_correspondence"): "\u4e09\u89d2\u5f62\u306e\u5bfe\u5fdc",
    ("geometry_parallel_congruence", "congruent_triangle_intro"): "\u4e09\u89d2\u5f62\u306e\u5bfe\u5fdc",
    ("geometry_parallel_congruence", "congruent_triangle_with_marks"): "\u4e09\u89d2\u5f62\u306e\u5bfe\u5fdc",
    ("geometry_parallel_congruence", "crossing_segments"): "\u4ea4\u5dee\u3059\u308b\u7dda\u5206\u306e\u56f3",
    ("linear_function", "triangle_projection_to_x_axis"): "\u30b0\u30e9\u30d5\u3068\u4e09\u89d2\u5f62",
}


SECTION_TITLE = "\u554f\u984c\u306e\u56f3"


def _get_problem_attr(problem: dict | object | None, key: str, default=None):
    if problem is None:
        return default
    if isinstance(problem, dict):
        return problem.get(key, default)
    return getattr(problem, key, default)


def _normalize_diagram_params(problem: dict | object | None = None, diagram_params: dict | None = None) -> dict:
    if isinstance(diagram_params, dict):
        return dict(diagram_params)
    raw = _get_problem_attr(problem, "diagram_params")
    return dict(raw) if isinstance(raw, dict) else {}


def infer_diagram_type(problem: dict | object | None = None, diagram_params: dict | None = None) -> str | None:
    params = _normalize_diagram_params(problem, diagram_params)
    diagram_type = params.get("diagram_type") or params.get("type")
    if diagram_type:
        return str(diagram_type)
    full_unit_id = _get_problem_attr(problem, "full_unit_id")
    unit_id = _get_problem_attr(problem, "unit")
    if full_unit_id == "linear_function_graph":
        return "linear_function_graph"
    if unit_id == "linear_function":
        return "linear_function_graph"
    return None


def infer_diagram_subtype(problem: dict | object | None = None, diagram_params: dict | None = None) -> str | None:
    params = _normalize_diagram_params(problem, diagram_params)
    explicit = params.get("subtype")
    if explicit:
        return str(explicit)

    diagram_type = infer_diagram_type(problem, params)
    full_unit_id = _get_problem_attr(problem, "full_unit_id")
    problem_id = _get_problem_attr(problem, "problem_id")
    text = str(_get_problem_attr(problem, "question_text", "") or params.get("_text_context") or "")

    if diagram_type in {"linear_function_graph", "line_axes_triangle", "two_lines_and_y_axis"}:
        if problem_id == 1050:
            return "triangle_projection_to_x_axis"
        tokens = ("\u76f4\u7dda y =", "\u70b9P", "x\u8ef8", "\u5782\u7dda", "\u4ea4\u70b9", "Q", "POQ", "\u539f\u70b9")
        if all(token in text for token in tokens):
            return "triangle_projection_to_x_axis"
        return diagram_type

    if diagram_type == "similar_triangles_basic":
        triangles = params.get("triangles")
        if isinstance(triangles, list):
            labels = []
            for triangle in triangles[:2]:
                if isinstance(triangle, dict):
                    for point in triangle.get("points", []):
                        if isinstance(point, dict):
                            labels.append(str(point.get("name") or ""))
            if any(label.endswith("2") for label in labels):
                return "crossing_segments"
        return "parallel_cut"

    if diagram_type == "triangle_correspondence":
        if full_unit_id == "geometry_parallel_congruence":
            equal_sides = params.get("equal_sides")
            equal_angles = params.get("equal_angles")
            if equal_sides or equal_angles:
                return "triangle_correspondence"
        return str(params.get("subtype") or "triangle_correspondence")

    if diagram_type == "parallel_lines_angle":
        return "parallel_angle_reasoning"
    if diagram_type == "circle_inscribed_angle":
        return "circle_inscribed_angle"
    return None


def get_diagram_display_name(diagram_type: str | None, subtype: str | None = None, unit_id: str | None = None, full_unit_id: str | None = None, route: str = "student") -> str:
    if full_unit_id and subtype:
        value = SUBTYPE_DISPLAY_NAMES.get((full_unit_id, subtype))
        if value:
            return value
    if diagram_type and diagram_type in DIAGRAM_TYPE_DISPLAY_NAMES:
        return DIAGRAM_TYPE_DISPLAY_NAMES[diagram_type]
    if unit_id and unit_id in UNIT_DISPLAY_NAMES:
        return UNIT_DISPLAY_NAMES[unit_id]
    if full_unit_id and full_unit_id in UNIT_DISPLAY_NAMES:
        return UNIT_DISPLAY_NAMES[full_unit_id]
    return SECTION_TITLE


def get_diagram_display_info(problem: dict | object | None = None, diagram_params: dict | None = None, route: str = "student") -> dict[str, Any]:
    params = _normalize_diagram_params(problem, diagram_params)
    diagram_type = infer_diagram_type(problem, params)
    subtype = infer_diagram_subtype(problem, params)
    unit_id = _get_problem_attr(problem, "unit")
    full_unit_id = _get_problem_attr(problem, "full_unit_id")
    display_name = get_diagram_display_name(diagram_type, subtype, unit_id=unit_id, full_unit_id=full_unit_id, route=route)
    internal_key = subtype or diagram_type or full_unit_id or unit_id or ""
    print(
        "[DIAGRAM_DISPLAY_NAME] "
        f"problem_id={_get_problem_attr(problem, 'problem_id', '')} unit_id={unit_id or ''} "
        f"diagram_type={diagram_type or ''} subtype={subtype or ''} route={route} "
        f"display_name={display_name} section_title={SECTION_TITLE}"
    )
    return {
        "section_title": SECTION_TITLE,
        "display_name": display_name,
        "internal_key": internal_key,
        "show_internal_key": route in {"teacher_preview", "teacher_list"},
        "diagram_type": diagram_type,
        "subtype": subtype,
    }
