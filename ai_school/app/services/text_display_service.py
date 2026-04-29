from ..services.math_text_service import format_math_for_display


def render_math_text(text: str | None):
    return format_math_for_display(text)
