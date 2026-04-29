"""Parent-facing report helpers: aggregation and AI draft text (Claude API, same key as teacher summary)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LearningLog, Problem
from ..services.ai_service import generate_claude_text
from ..services.problem_service import get_unit_label_map

JST = ZoneInfo("Asia/Tokyo")
_WEEKDAY_JA = "\u6708\u706b\u6c34\u6728\u91d1\u571f\u65e5"


def jst_now() -> datetime:
    return datetime.now(JST)


def format_jst_date_header(dt_jst: datetime) -> str:
    if dt_jst.tzinfo is None:
        dt_jst = dt_jst.replace(tzinfo=JST)
    else:
        dt_jst = dt_jst.astimezone(JST)
    wd = _WEEKDAY_JA[dt_jst.weekday()]
    return f"{dt_jst.year}\u5e74{dt_jst.month}\u6708{dt_jst.day}\u65e5\uff08{wd}\uff09"


def format_jst_month_day(dt_jst: datetime) -> str:
    if dt_jst.tzinfo is None:
        dt_jst = dt_jst.replace(tzinfo=JST)
    else:
        dt_jst = dt_jst.astimezone(JST)
    return f"{dt_jst.month}\u6708{dt_jst.day}\u65e5"


def utc_naive_bounds_for_jst_calendar_day_to_now() -> tuple[datetime, datetime]:
    now_j = jst_now()
    start_j = now_j.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_j.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = now_j.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


def aggregate_today_learning_logs(db: Session, student_id: int) -> dict:
    start_utc, end_utc = utc_naive_bounds_for_jst_calendar_day_to_now()
    now_j = jst_now()

    rows = db.execute(
        select(LearningLog, Problem)
        .join(Problem, LearningLog.problem_id == Problem.problem_id)
        .where(
            LearningLog.student_id == student_id,
            LearningLog.created_at >= start_utc,
            LearningLog.created_at <= end_utc,
        )
        .order_by(LearningLog.created_at.asc())
    ).all()

    unit_labels = get_unit_label_map(db)
    unit_keys_order: list[str] = []
    seen: set[str] = set()
    for _log, prob in rows:
        key = prob.full_unit_id or prob.unit
        if key not in seen:
            seen.add(key)
            unit_keys_order.append(key)
    unit_names = [unit_labels.get(k, k) for k in unit_keys_order]

    total = len(rows)
    correct = sum(1 for log, _ in rows if log.is_correct)
    wrong = total - correct
    hint_sum = sum((log.hint_used or 0) for log, _ in rows)
    rate = round(correct / total * 100) if total > 0 else 0

    err_counts: dict[str, int] = defaultdict(int)
    for log, _ in rows:
        if not log.is_correct and log.error_pattern:
            err_counts[log.error_pattern] += 1
    top_errors = sorted(err_counts.items(), key=lambda x: x[1], reverse=True)[:2]

    return {
        "jst_date_header": format_jst_date_header(now_j),
        "jst_month_day": format_jst_month_day(now_j),
        "start_utc": start_utc,
        "end_utc": end_utc,
        "rows": rows,
        "unit_names": unit_names,
        "total_count": total,
        "correct_count": correct,
        "wrong_count": wrong,
        "rate": rate,
        "hint_total": hint_sum,
        "top_error_patterns": top_errors,
        "top_error_pattern_key": top_errors[0][0] if top_errors else None,
    }


_ERROR_COMMENT = {
    "sign_error": "\u7b26\u53f7\u306e\u6271\u3044\u3092\u91cd\u70b9\u7684\u306b\u7df4\u7fd2\u4e2d\u3067\u3059\u3002",
    "arithmetic_error": "\u8a08\u7b97\u306e\u6b63\u78ba\u3055\u3092\u9ad8\u3081\u308b\u30c8\u30ec\u30fc\u30cb\u30f3\u30b0\u3092\u7d99\u7d9a\u4e2d\u3067\u3059\u3002",
    "comprehension_gap": "\u554f\u984c\u6587\u306e\u8aad\u307f\u53d6\u308a\u306b\u5c11\u3057\u6642\u9593\u304c\u304b\u304b\u3063\u3066\u3044\u307e\u3059\u3002",
}


def error_comment_for_pattern(pattern: str | None) -> str:
    if not pattern:
        return "\u7740\u5b9f\u306b\u529b\u3092\u3064\u3051\u3066\u3044\u307e\u3059\u3002"
    return _ERROR_COMMENT.get(pattern, "\u7740\u5b9f\u306b\u529b\u3092\u3064\u3051\u3066\u3044\u307e\u3059\u3002")


def build_today_fallback_message(
    date_short: str,
    unit_name_joined: str,
    total_count: int,
    correct_count: int,
    rate: int,
    top_pattern: str | None,
) -> str:
    unit_name = unit_name_joined or "\u5404\u5358\u5143"
    err = error_comment_for_pattern(top_pattern)
    lines = [
        f"\U0001f4da {date_short} \u306e\u5b66\u7fd2\u5831\u544a",
        "",
        f"\u672c\u65e5\u306f\u300c{unit_name}\u300d\u306b\u53d6\u308a\u7d44\u307f\u307e\u3057\u305f\u3002",
        f"{total_count}\u554f\u3092\u89e3\u304d\u3001{correct_count}\u554f\u6b63\u89e3\uff08\u6b63\u7b54\u7387{rate}%\uff09\u3067\u3057\u305f\u3002",
        "",
        err,
        "",
        "\u6b21\u56de\u3082\u5f15\u304d\u7d9a\u304d\u540c\u3058\u5358\u5143\u3092\u9032\u3081\u308b\u4e88\u5b9a\u3067\u3059\u3002",
        "\u5f15\u304d\u7d9a\u304d\u3088\u308d\u3057\u304f\u304a\u9858\u3044\u3057\u307e\u3059\u3002",
    ]
    return "\n".join(lines)


def generate_today_parent_message_ai(
    date_header: str,
    unit_names_csv: str,
    total_count: int,
    correct_count: int,
    diagnostic_label_ja: str,
    top_error_label_ja: str,
) -> str | None:
    none_units = "\uff08\u8a72\u5f53\u306a\u3057\uff09"
    user_prompt = (
        "\u4ee5\u4e0b\u306e\u5b66\u7fd2\u30c7\u30fc\u30bf\u3092\u3082\u3068\u306b\u3001\u4fdd\u8b77\u8005\u5411\u3051\u306e\u77ed\u3044\u9032\u6357\u5831\u544a\u6587\u3092\u65e5\u672c\u8a9e\u3067\u4f5c\u6210\u3057\u3066\u304f\u3060\u3055\u3044\u3002\n\n"
        "\u6761\u4ef6:\n"
        "- \u5168\u4f53\u3067150\u301c200\u5b57\u7a0b\u5ea6\n"
        "- \u4fdd\u8b77\u8005\u304c\u8aad\u307f\u3084\u3059\u3044\u4e01\u5be7\u306a\u53e3\u8a9e\u4f53\n"
        "- \u6570\u5b57\uff08\u554f\u984c\u6570\u30fb\u6b63\u7b54\u7387\uff09\u3092\u5177\u4f53\u7684\u306b\u542b\u3081\u308b\n"
        "- \u3064\u307e\u305a\u304d\u3092\u8cac\u3081\u305a\u3001\u524d\u5411\u304d\u306a\u8868\u73fe\u306b\u3059\u308b\n"
        "- \u6700\u5f8c\u306b\u6b21\u56de\u5b66\u7fd2\u306e\u4e00\u8a00\u6848\u5185\u3092\u5165\u308c\u308b\n\n"
        "\u30c7\u30fc\u30bf:\n"
        f"- \u5b66\u7fd2\u65e5: {date_header}\n"
        f"- \u5b66\u7fd2\u5358\u5143: {unit_names_csv or none_units}\n"
        f"- \u554f\u984c\u6570: {total_count}\u554f\n"
        f"- \u6b63\u89e3: {correct_count}\u554f\n"
        f"- \u4e3b\u306a\u3064\u307e\u305a\u304d: {top_error_label_ja}\n"
        f"- \u8a3a\u65ad\u30e9\u30d9\u30eb: {diagnostic_label_ja}\n"
    )
    system_prompt = (
        "\u3042\u306a\u305f\u306f\u5b66\u7fd2\u5875\u306e\u9023\u7d61\u62c5\u5f53\u3067\u3059\u3002\u4e0e\u3048\u3089\u308c\u305f\u5b66\u7fd2\u30c7\u30fc\u30bf\u306e\u307f\u306b\u57fa\u3065\u304d\u3001"
        "\u4fdd\u8b77\u8005\u5411\u3051\u306e\u77ed\u6587\u3092\u66f8\u3044\u3066\u304f\u3060\u3055\u3044\u3002\u898b\u51fa\u3057\u3084\u7b87\u6761\u66f8\u304d\u306f\u4f7f\u308f\u305a\u3001\u81ea\u7136\u306a\u6bb5\u843d\u3067\u51fa\u529b\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
    )
    # Same Claude API as teacher AI summary (CLAUDE_API_KEY).
    return generate_claude_text(system_prompt, user_prompt, max_output_tokens=400)


def weekly_trend_text_for_prompt(trend: str | None, prev_rate: int | None, correct_rate: int) -> str:
    if prev_rate is None:
        return "\u5148\u9031\u30c7\u30fc\u30bf\u306a\u3057"
    diff = correct_rate - prev_rate
    if trend == "up":
        return f"\u5148\u9031\u6bd4 \u7d04+{diff}%\uff08\u4e0a\u5411\u304d\uff09"
    if trend == "down":
        return f"\u5148\u9031\u6bd4 \u7d04{diff}%\uff08\u4e0b\u5411\u304d\uff09"
    return "\u5148\u9031\u3068\u540c\u7a0b\u5ea6"


def generate_weekly_parent_message_ai(
    start_date: str,
    end_date: str,
    total_count: int,
    correct_rate: int,
    trend_prompt: str,
    unit_names: str,
    top_errors: str,
) -> str | None:
    user_prompt = (
        "\u4ee5\u4e0b\u306e1\u9031\u9593\u306e\u5b66\u7fd2\u30c7\u30fc\u30bf\u3092\u3082\u3068\u306b\u3001\u4fdd\u8b77\u8005\u5411\u3051\u306e\u9031\u6b21\u5831\u544a\u6587\u3092\u65e5\u672c\u8a9e\u3067\u4f5c\u6210\u3057\u3066\u304f\u3060\u3055\u3044\u3002\n\n"
        "\u6761\u4ef6:\n"
        "- \u5168\u4f53\u3067200\u301c300\u5b57\u7a0b\u5ea6\n"
        "- \u4fdd\u8b77\u8005\u304c\u8aad\u307f\u3084\u3059\u3044\u4e01\u5be7\u306a\u53e3\u8a9e\u4f53\n"
        "- \u7dcf\u554f\u984c\u6570\u30fb\u6b63\u7b54\u7387\u30fb\u3088\u304f\u53d6\u308a\u7d44\u3093\u3060\u5358\u5143\u3092\u542b\u3081\u308b\n"
        "- \u8aa4\u7b54\u50be\u5411\u306f\u8cac\u3081\u305a\u3001\u6539\u5584\u306e\u5146\u3057\u3084\u9811\u5f35\u308a\u3092\u524d\u5411\u304d\u306b\u4f1d\u3048\u308b\n"
        "- \u6765\u9031\u306e\u304a\u3059\u3059\u3081\u5b66\u7fd2\u65b9\u91dd\u3092\u4e00\u8a00\u6dfb\u3048\u308b\n\n"
        "\u30c7\u30fc\u30bf:\n"
        f"- \u5bfe\u8c61\u671f\u9593: {start_date} \u301c {end_date}\n"
        f"- \u7dcf\u56de\u7b54\u6570: {total_count}\u554f\n"
        f"- \u6b63\u7b54\u7387: {correct_rate}%\uff08{trend_prompt}\uff09\n"
        f"- \u4e3b\u306a\u5b66\u7fd2\u5358\u5143: {unit_names}\n"
        f"- \u8aa4\u7b54\u50be\u5411: {top_errors}\n"
    )
    system_prompt = (
        "\u3042\u306a\u305f\u306f\u5b66\u7fd2\u5875\u306e\u9023\u7d61\u62c5\u5f53\u3067\u3059\u3002\u4e0e\u3048\u3089\u308c\u305f\u9031\u6b21\u30c7\u30fc\u30bf\u306e\u307f\u306b\u57fa\u3065\u304d\u3001"
        "\u4fdd\u8b77\u8005\u5411\u3051\u306e\u9031\u6b21\u5831\u544a\u3092\u66f8\u3044\u3066\u304f\u3060\u3055\u3044\u3002\u898b\u51fa\u3057\u3084\u7b87\u6761\u66f8\u304d\u306f\u4f7f\u308f\u305a\u3001\u81ea\u7136\u306a\u6bb5\u843d\u3067\u51fa\u529b\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
    )
    # Same Claude API as teacher AI summary (CLAUDE_API_KEY).
    return generate_claude_text(system_prompt, user_prompt, max_output_tokens=500)
