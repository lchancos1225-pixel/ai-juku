"""
レクチャーステップ生成サービス

cascade（Claude）が生成したテンプレートを基に、
単元情報からステップJSONを組み立ててDBにキャッシュする。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from ..models import UnitDependency

logger = logging.getLogger(__name__)

# ─── 定数 ───────────────────────────────────────────────────────────────────
MAX_STEPS = 4

_VISUAL_TYPE_RULES = [
    (["加法", "減法", "正負", "数直線", "負の数", "たし算", "ひき算"], "number_line"),
    (["分数", "通分", "約分"], "fraction_bar"),
    (["面積", "乗法", "かけ算", "掛け算"], "area_grid"),
    (["筆算"], "pen_calc"),
]


def _suggest_visual_type(display_name: str) -> str:
    for keywords, vtype in _VISUAL_TYPE_RULES:
        if any(kw in display_name for kw in keywords):
            return vtype
    return "text_only"


# ─── cascade生成テンプレート ─────────────────────────────────────────────────
# 各visual_type用のステップテンプレート（cascadeが設計・検証済み）
STEP_TEMPLATES = {
    "number_line": {
        "unit_title": "{unit_name}",
        "steps": [
            {
                "id": 1,
                "title": "まず確認",
                "body": "「{unit_name}」の問題を見て、数直線のどこからスタートするか確認しよう。",
                "formula": "",
                "visual_type": "number_line",
                "visual_params": {"range_min": -5, "range_max": 10, "moves": [], "result": 0},
                "highlight": "スタート位置を見つけよう",
            },
            {
                "id": 2,
                "title": "数直線で動く",
                "body": "足し算は右へ、引き算は左へ動くよ。数直線上で矢印を動かしてみよう。",
                "formula": "",
                "visual_type": "number_line",
                "visual_params": {"range_min": -5, "range_max": 10, "moves": [{"from": 0, "to": 3, "label": "+3"}], "result": 3},
                "highlight": "方向を確認しよう",
            },
            {
                "id": 3,
                "title": "答えを確認",
                "body": "最後に止まった場所が答えだよ。数直線上で確認してみよう。",
                "formula": "",
                "visual_type": "number_line",
                "visual_params": {"range_min": -5, "range_max": 10, "moves": [{"from": 0, "to": 3, "label": "+3"}], "result": 3},
                "highlight": "答えはここ！",
            },
        ],
    },
    "fraction_bar": {
        "unit_title": "{unit_name}",
        "steps": [
            {
                "id": 1,
                "title": "分数を見る",
                "body": "「{unit_name}」の問題で出てくる分数を確認しよう。分母はバーを何等分するかを表すよ。",
                "formula": "",
                "visual_type": "fraction_bar",
                "visual_params": {"numerators": [1], "denominator": 4, "result_num": 1, "result_den": 4},
                "highlight": "分母＝分割数",
            },
            {
                "id": 2,
                "title": "バーの長さ",
                "body": "分子はそのうち何個分かを表すよ。バーの長さで分数の大きさを見てみよう。",
                "formula": "",
                "visual_type": "fraction_bar",
                "visual_params": {"numerators": [1, 2], "denominator": 4, "result_num": 3, "result_den": 4},
                "highlight": "分子＝個数",
            },
            {
                "id": 3,
                "title": "答えを出す",
                "body": "分数を足す時は、分母が同じなら分子だけ足せばOK！",
                "formula": "1/4 + 2/4 = 3/4",
                "visual_type": "fraction_bar",
                "visual_params": {"numerators": [1, 2], "denominator": 4, "result_num": 3, "result_den": 4},
                "highlight": "分子だけ足す",
            },
        ],
    },
    "area_grid": {
        "unit_title": "{unit_name}",
        "steps": [
            {
                "id": 1,
                "title": "グリッドを見る",
                "body": "「{unit_name}」をマス目で考えてみよう。横の数と縦の数をかけ合わせると...",
                "formula": "",
                "visual_type": "area_grid",
                "visual_params": {"rows": 3, "cols": 4, "highlight_row": 1, "highlight_col": 1},
                "highlight": "マス目を数えよう",
            },
            {
                "id": 2,
                "title": "行と列",
                "body": "横のマス数（列）と縦のマス数（行）をかけると、全部のマス数が出るよ。",
                "formula": "3 × 4 = 12",
                "visual_type": "area_grid",
                "visual_params": {"rows": 3, "cols": 4, "highlight_row": 2, "highlight_col": 2},
                "highlight": "行×列＝全部",
            },
            {
                "id": 3,
                "title": "答えを確認",
                "body": "マス目を実際に数えて、計算の答えが合っているか確認しよう。",
                "formula": "3 × 4 = 12",
                "visual_type": "area_grid",
                "visual_params": {"rows": 3, "cols": 4, "highlight_row": 3, "highlight_col": 3},
                "highlight": "数えて確かめよう",
            },
        ],
    },
    "pen_calc": {
        "unit_title": "{unit_name}",
        "steps": [
            {
                "id": 1,
                "title": "位をそろえる",
                "body": "「{unit_name}」の筆算では、まず数の位（いちのくらい、じゅうのくらい）をそろえて書こう。",
                "formula": "",
                "visual_type": "pen_calc",
                "visual_params": {"lines": ["  23", "+ 45", "────"]},
                "highlight": "位をそろえる",
            },
            {
                "id": 2,
                "title": "下から計算",
                "body": "いちのくらいから順に計算していこう。くり上がりに注意！",
                "formula": "3 + 5 = 8",
                "visual_type": "pen_calc",
                "visual_params": {"lines": ["  23", "+ 45", "────", "  68"]},
                "highlight": "下から順に",
            },
            {
                "id": 3,
                "title": "答えを書く",
                "body": "計算が終わったら、答えをきれいに書こう。",
                "formula": "23 + 45 = 68",
                "visual_type": "pen_calc",
                "visual_params": {"lines": ["  23", "+ 45", "────", "= 68"]},
                "highlight": "答えは68",
            },
        ],
    },
    "text_only": {
        "unit_title": "{unit_name}",
        "steps": [
            {
                "id": 1,
                "title": "問題を読む",
                "body": "「{unit_name}」の問題文をよく読んで、何を求めるか確認しよう。",
                "formula": "",
                "visual_type": "text_only",
                "visual_params": {},
                "highlight": "求めるものを確認",
            },
            {
                "id": 2,
                "title": "考え方",
                "body": "問題を小さく分けて、一つずつ解いていこう。",
                "formula": "",
                "visual_type": "text_only",
                "visual_params": {},
                "highlight": "分けて考える",
            },
            {
                "id": 3,
                "title": "答えを出す",
                "body": "計算して答えを出し、問題文と合っているか確認しよう。",
                "formula": "",
                "visual_type": "text_only",
                "visual_params": {},
                "highlight": "答えを確認",
            },
        ],
    },
}


def _make_fallback_steps(unit_display_name: str) -> dict:
    """テンプレートがない場合のフォールバック"""
    template = STEP_TEMPLATES["text_only"]
    return _fill_template(template, unit_display_name)


def _fill_template(template: dict, unit_name: str) -> dict:
    """テンプレートに単元名を埋め込む"""
    result = json.loads(json.dumps(template))  # ディープコピー
    result["unit_title"] = result["unit_title"].format(unit_name=unit_name)
    for step in result["steps"]:
        step["body"] = step["body"].format(unit_name=unit_name)
    return result


def generate_lecture_steps(unit: "UnitDependency") -> dict:
    """
    cascadeテンプレートからステップJSONを生成して返す。
    DB保存はしない（呼び出し元で保存すること）。
    """
    vtype = _suggest_visual_type(unit.display_name)
    template = STEP_TEMPLATES.get(vtype, STEP_TEMPLATES["text_only"])
    return _fill_template(template, unit.display_name)


def get_or_generate_steps(db: "Session", unit: "UnitDependency") -> dict:
    """
    DBキャッシュ優先。なければAI生成してDBに保存し返す。
    """
    if unit.lecture_steps_json:
        try:
            cached = json.loads(unit.lecture_steps_json)
            if isinstance(cached.get("steps"), list):
                return cached
        except (json.JSONDecodeError, ValueError):
            pass

    steps_data = generate_lecture_steps(unit)
    try:
        unit.lecture_steps_json = json.dumps(steps_data, ensure_ascii=False)
        db.add(unit)
        db.commit()
        logger.info("lecture_step_service: steps生成 unit=%s vtype=%s", unit.unit_id, vtype)
    except (json.JSONDecodeError, TypeError) as e:
        logger.error("lecture_step_service: JSON変換失敗 unit=%s err=%s", unit.unit_id, e)
    except Exception as e:
        logger.error("lecture_step_service: DB保存失敗 unit=%s err=%s", unit.unit_id, e)

    return steps_data
