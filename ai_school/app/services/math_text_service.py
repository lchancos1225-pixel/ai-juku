import re
import unicodedata

from markupsafe import Markup, escape


# 括弧付き分数: (-1/3), (+1/2), (3/4), （-1/3）など
_PAREN_FRACTION_PATTERN = re.compile(
    r"(?P<oparen>[（(])"
    r"(?P<psign>[+\-])?"
    r"(?P<pnum>\d+)"
    r"\s*/\s*"
    r"(?P<pden>\d+)"
    r"(?P<cparen>[）)])"
)

_FRACTION_PATTERN = re.compile(
    r"(?<![0-9A-Za-z_./])"
    r"(?P<num>(?:-?\d+|[A-Za-z]+(?:\^[-+]?\d+)?|\([^()\s]+\)(?:\^[-+]?\d+)?))"
    r"\s*/\s*"
    r"(?P<den>(?:\d+|[A-Za-z]+(?:\^[-+]?\d+)?|\([^()\s]+\)(?:\^[-+]?\d+)?))"
    r"(?![0-9A-Za-z_./])"
)
_SUPERSCRIPT_PATTERN = re.compile(
    r"(?P<base>\([^()\s]+\)|[A-Za-z]+|\d+)(?:\^(?P<exp>[-+]?\d+))"
)
_SPACE_PATTERN = re.compile(r"[\s\u3000]+")
_PAREN_SPACE_PATTERN = re.compile(r"\(\s+|\s+\)")
_SLASH_SPACE_PATTERN = re.compile(r"\s*/\s*")
# 数値係数と変数の間の明示的な乗算記号を検出: 2*x → 2x
_COEFF_MULT_PATTERN = re.compile(r"(\d)\*([A-Za-z])")
# 結果画面用: 先頭の数値・分数と、その後に続く単位などを分離（例: 2℃ → 2 + ℃）
_NUMERIC_CORE_WITH_SUFFIX = re.compile(
    r"^([+\-]?(?:\d+/\d+|\d+(?:\.\d+)?))(.*)$"
)

_MINUS_TRANSLATION = str.maketrans(
    {
        "−": "-",
        "－": "-",
        "—": "-",
        "–": "-",
        "‒": "-",
        "―": "-",
    }
)
_SUPERSCRIPT_TRANSLATION = str.maketrans(
    {
        "⁰": "^0",
        "¹": "^1",
        "²": "^2",
        "³": "^3",
        "⁴": "^4",
        "⁵": "^5",
        "⁶": "^6",
        "⁷": "^7",
        "⁸": "^8",
        "⁹": "^9",
        "⁻": "^-",
        "⁺": "^+",
    }
)


def format_math_for_display(text: str | None) -> Markup:
    if not text:
        return Markup("")
    return Markup(_render_with_patterns(str(text)))



def normalize_answer_for_grading(answer: str | None) -> str:
    if answer is None:
        return ""

    normalized = str(answer).translate(_SUPERSCRIPT_TRANSLATION)
    normalized = unicodedata.normalize("NFKC", normalized)
    normalized = normalized.translate(_MINUS_TRANSLATION)
    normalized = normalized.replace("／", "/").replace("⁄", "/").replace("\\", "/")
    normalized = normalized.replace("×", "*").replace("÷", "/")
    normalized = normalized.strip()
    normalized = _SPACE_PATTERN.sub("", normalized)
    normalized = _SLASH_SPACE_PATTERN.sub("/", normalized)
    normalized = _PAREN_SPACE_PATTERN.sub(lambda match: "(" if "(" in match.group(0) else ")", normalized)
    # 数値係数と変数の間の乗算記号を除去: 2*x → 2x, 3*a → 3a
    normalized = _COEFF_MULT_PATTERN.sub(r"\1\2", normalized)
    # 連続する符号を整理: +- → -, -+ → -, -- → +
    normalized = normalized.replace("+-", "-").replace("-+", "-").replace("--", "+")
    # 先頭の冗長なプラス記号を除去: +3 → 3, +x → x
    if normalized.startswith("+"):
        normalized = normalized[1:]
    return normalized


def _split_trailing_unit_single(raw: str) -> tuple[str, str | None]:
    """Normalize then split a leading integer, decimal, or fraction from a trailing non-empty suffix (units, 点, etc.)."""
    if not raw:
        return raw, None
    t = normalize_answer_for_grading(raw)
    if not t:
        return raw.strip(), None
    m = _NUMERIC_CORE_WITH_SUFFIX.match(t)
    if not m:
        return raw.strip(), None
    core, tail = m.group(1), m.group(2).strip()
    if not tail:
        return raw.strip(), None
    return core, tail


def pair_for_student_numeric_result_display(
    answer: str | None,
    *,
    subject: str | None,
    answer_type: str | None,
) -> tuple[str, str | None]:
    """Math numeric answers only: main value vs auxiliary unit/suffix for student-facing results."""
    if subject == "english" or answer_type != "numeric":
        return ((answer or "").strip(), None)
    from .answer_input_spec_service import MULTI_ANSWER_DELIMITER

    d = MULTI_ANSWER_DELIMITER
    raw = (answer or "").strip()
    if not raw:
        return "", None
    if d in raw:
        parts = raw.split(d)
        mains: list[str] = []
        auxes: list[str | None] = []
        for p in parts:
            m, a = _split_trailing_unit_single(p.strip())
            mains.append(m)
            auxes.append(a)
        main_joined = d.join(mains)
        nonempty = [x for x in auxes if x]
        if not nonempty:
            return raw, None
        if len(set(nonempty)) == 1:
            return main_joined, nonempty[0]
        return main_joined, "\u3001".join(nonempty)
    return _split_trailing_unit_single(raw)


def _render_with_patterns(text: str) -> str:
    parts: list[str] = []
    index = 0
    while index < len(text):
        paren_frac_match = _PAREN_FRACTION_PATTERN.search(text, index)
        fraction_match = _FRACTION_PATTERN.search(text, index)
        superscript_match = _SUPERSCRIPT_PATTERN.search(text, index)
        match = _pick_earliest_match(paren_frac_match, fraction_match, superscript_match)
        if match is None:
            parts.append(str(escape(text[index:])))
            break
        start, end = match.span()
        if start > index:
            parts.append(str(escape(text[index:start])))
        if match.re is _PAREN_FRACTION_PATTERN:
            parts.append(_render_paren_fraction(
                match.group("oparen"),
                match.group("psign") or "",
                match.group("pnum"),
                match.group("pden"),
                match.group("cparen"),
            ))
        elif match.re is _FRACTION_PATTERN:
            parts.append(_render_fraction(match.group("num"), match.group("den")))
        else:
            parts.append(_render_superscript(match.group("base"), match.group("exp")))
        index = end
    return "".join(parts)



def _pick_earliest_match(*matches):
    valid = [match for match in matches if match is not None]
    if not valid:
        return None
    return min(valid, key=lambda match: (match.start(), match.end()))



def _render_paren_fraction(oparen: str, sign: str, numerator: str, denominator: str, cparen: str) -> str:
    """(-1/3) のような括弧付き分数を縦中央揃えで描画する。"""
    num_text = sign + numerator
    frac_html = _render_fraction(num_text, denominator)
    return (
        '<span class="math-paren-group">'
        f'<span class="math-paren-brace">{escape(oparen)}</span>'
        f"{frac_html}"
        f'<span class="math-paren-brace">{escape(cparen)}</span>'
        "</span>"
    )


def _render_fraction(numerator: str, denominator: str) -> str:
    numerator_html = _render_with_patterns(numerator)
    denominator_html = _render_with_patterns(denominator)
    aria = f"{numerator}/{denominator}"
    return (
        '<span class="math-frac" aria-label="'
        f'{escape(aria)}'
        '"><span class="math-frac-top">'
        f"{numerator_html}"
        '</span><span class="math-frac-bar"></span><span class="math-frac-bottom">'
        f"{denominator_html}"
        "</span></span>"
    )



def _render_superscript(base: str, exponent: str) -> str:
    base_html = str(escape(base))
    exponent_html = str(escape(exponent))
    return f'{base_html}<sup class="math-sup">{exponent_html}</sup>'
