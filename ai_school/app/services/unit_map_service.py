import json
from functools import lru_cache
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[3] / 'data'
GRADE_FILES = ('unit_map_grade7.json', 'unit_map_grade8.json', 'unit_map_grade9.json')


@lru_cache(maxsize=1)
def load_all_unit_maps() -> list[dict]:
    items: list[dict] = []
    for filename in GRADE_FILES:
        path = DATA_DIR / filename
        if not path.exists():
            continue
        with path.open('r', encoding='utf-8') as file:
            payload = json.load(file)
        if isinstance(payload, list):
            items.extend(payload)
    return items


@lru_cache(maxsize=1)
def unit_map_by_full_unit_id() -> dict[str, dict]:
    return {item['full_unit_id']: item for item in load_all_unit_maps()}


@lru_cache(maxsize=1)
def unit_map_by_parent_and_sub_unit() -> dict[tuple[str, str], dict]:
    mapping: dict[tuple[str, str], dict] = {}
    for item in load_all_unit_maps():
        mapping[(item['parent_unit'], item['sub_unit'])] = item
    return mapping


@lru_cache(maxsize=1)
def first_entry_by_parent_unit() -> dict[str, dict]:
    mapping: dict[str, dict] = {}
    for item in sorted(load_all_unit_maps(), key=lambda row: (row['grade'], row['display_order'])):
        mapping.setdefault(item['parent_unit'], item)
    return mapping


@lru_cache(maxsize=1)
def known_parent_units() -> set[str]:
    return {item['parent_unit'] for item in load_all_unit_maps()}


def get_unit_map_entry(full_unit_id: str | None) -> dict | None:
    if not full_unit_id:
        return None
    return unit_map_by_full_unit_id().get(full_unit_id)


def resolve_full_unit_id(parent_unit: str | None, sub_unit: str | None = None) -> str | None:
    if not parent_unit:
        return None
    if sub_unit:
        entry = unit_map_by_parent_and_sub_unit().get((parent_unit, sub_unit))
        if entry:
            return entry['full_unit_id']
    first_entry = first_entry_by_parent_unit().get(parent_unit)
    return first_entry['full_unit_id'] if first_entry else None


def resolve_unit_map_entry(parent_unit: str | None, sub_unit: str | None = None, full_unit_id: str | None = None) -> dict | None:
    if full_unit_id:
        entry = get_unit_map_entry(full_unit_id)
        if entry:
            return entry
    resolved = resolve_full_unit_id(parent_unit, sub_unit)
    return get_unit_map_entry(resolved)


def build_current_position_summary(entry: dict | None) -> str | None:
    if not entry:
        return None
    grade_label = f"中{entry['grade'] - 6}数学"
    return f"{grade_label} / {entry['display_name'].replace('（', ' / ').replace('）', '')}"
