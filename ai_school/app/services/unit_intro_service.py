"""
単元intro_html生成サービス

cascade（Claude）が生成したテンプレートを基に、
単元情報からintro_htmlを組み立ててDBにキャッシュする。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from ..models import UnitDependency

logger = logging.getLogger(__name__)

# ─── 定数 ───────────────────────────────────────────────────────────────────
VISUAL_TYPE_RULES = [
    (["加法", "減法", "正負", "数直線", "負の数", "たし算", "ひき算"], "number_line"),
    (["分数", "通分", "約分"], "fraction_bar"),
    (["面積", "乗法", "かけ算", "掛け算"], "area_grid"),
    (["筆算"], "pen_calc"),
]


# ─── テンプレート ─────────────────────────────────────────────────────────
# cascade生成: 各visual_type用のintro_htmlテンプレート
INTRO_TEMPLATES = {
    "number_line": """<p><strong>「{unit_name}」</strong>を数直線を使って学ぼう！</p>
<p>数を直線上の位置として考えると、大きさの比較や足し算・引き算が見える化できます。</p>
<p>ステップ解説で、数直線を動かしながら考え方を確認しよう。</p>""",

    "fraction_bar": """<p><strong>「{unit_name}」</strong>を分数バーで学ぼう！</p>
<p>分数は「バーの長さ」として見える化できます。分母はバーを何等分するか、分子はそのうち何個分かを表します。</p>
<p>ステップ解説で、分数バーを動かしながら考え方を確認しよう。</p>""",

    "area_grid": """<p><strong>「{unit_name}」</strong>を面積グリッドで学ぼう！</p>
<p>かけ算は「横×縦」のマス目の数として見える化できます。グリッドを数えながら計算の意味を理解しよう。</p>
<p>ステップ解説で、マス目を数えながら考え方を確認しよう。</p>""",

    "pen_calc": """<p><strong>「{unit_name}」</strong>を筆算で学ぼう！</p>
<p>筆算は大きな数の計算を小さな計算に分けて解く方法です。位をそろえて、くり上がり・くり下がりに注意しよう。</p>
<p>ステップ解説で、1桁ずつ計算する考え方を確認しよう。</p>""",

    "text_only": """<p><strong>「{unit_name}」</strong>をステップで学ぼう！</p>
<p>問題を小さく分けて、ひとつずつ確認していこう。重要なポイントを押さえながら進めます。</p>
<p>ステップ解説で、考え方を一緒に確認しよう。</p>""",
}


def suggest_visual_type(display_name: str) -> str:
    """単元名から推奨図解タイプを判定"""
    for keywords, vtype in VISUAL_TYPE_RULES:
        if any(kw in display_name for kw in keywords):
            return vtype
    return "text_only"


def generate_unit_intro(unit: "UnitDependency") -> str:
    """単元に応じたintro_htmlを生成する（cascadeテンプレートから組み立て）"""
    vtype = suggest_visual_type(unit.display_name)
    template = INTRO_TEMPLATES.get(vtype, INTRO_TEMPLATES["text_only"])
    return template.format(unit_name=unit.display_name)


def get_or_generate_intro(db: "Session", unit: "UnitDependency") -> str:
    """DBキャッシュ優先。なければcascadeテンプレートから生成して保存。"""
    if unit.intro_html:
        return unit.intro_html

    intro = generate_unit_intro(unit)
    try:
        unit.intro_html = intro
        db.add(unit)
        db.commit()
        logger.info("unit_intro_service: intro生成 unit=%s", unit.unit_id)
    except Exception as e:
        logger.error("unit_intro_service: DB保存失敗 unit=%s err=%s", unit.unit_id, e)

    return intro
