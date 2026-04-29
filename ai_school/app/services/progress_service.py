from __future__ import annotations

from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from zoneinfo import ZoneInfo

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..models import LearningLog, Problem, Student, StudentBoardCell, StudentState, UnitDependency
from .intervention_service import ADVANCE_WITH_CONFIDENCE
from .routing_service import ADVANCE_ROUTE, FALLBACK_ROUTE
from .state_service import build_student_summary
from .unit_map_service import get_unit_map_entry


JST = ZoneInfo("Asia/Tokyo")

DIAGNOSTIC_LABEL_TEXT = {
    "stable_mastery": "しっかりできているね。",
    "hint_dependent": "ヒントがあるとできるようになってきたね。",
    "slow_but_correct": "ていねいに考えて正解できているね。",
    "unstable_understanding": "もう少し練習するともっと安定しそうだね。",
    "prerequisite_gap": "前の内容を少し見直すとわかりやすくなるよ",
    "in_progress": "少しずつ力がついてきているね。",
    "not_started": "これから始めるところだね。",
}

INTERVENTION_TITLE_TEXT = {
    "reinforce_same_pattern": "次は同じ形をもう1問やってみよう",
    "retry_with_hint": "次はヒントを見ながらもう一回やってみよう",
    "fallback_prerequisite": "一度、前の内容を少し復習しよう",
    "slow_down_and_confirm": "あわてず一つずつ確かめながら進めよう",
    "explain_differently": "説明の見方を変えてみよう",
    "teacher_intervention_needed": "わからないところを聞きながら進めよう",
    "advance_with_confidence": "次の内容に進んでみよう",
    "monitor_only": "この調子で今の単元を進めよう",
}

INTERVENTION_BODY_TEXT = {
    "reinforce_same_pattern": "同じ形をくり返すと、考え方がしっかりつながっていくよ。",
    "retry_with_hint": "ヒントを使いながら進めると、次は自分で解ける形が増えていくよ。",
    "fallback_prerequisite": "前の内容を少し見直してから戻ると、今の単元がわかりやすくなるよ。",
    "slow_down_and_confirm": "ていねいに進める力も大事だよ。式を一つずつ確かめながらいこう。",
    "explain_differently": "見方を少し変えると、急にわかりやすくなることがあるよ。",
    "teacher_intervention_needed": "ひとりで止まらなくて大丈夫。聞きながら進めれば次の一歩が見えてくるよ。",
    "advance_with_confidence": "今までの積み重ねができてきたよ。次の内容にも手をのばしてみよう。",
    "monitor_only": "いまの進め方で前に進めているよ。そのまま1問ずつ続けよう。",
}

ROUTE_TITLE_TEXT = {
    ADVANCE_ROUTE: "次の単元に進む準備ができているね。",
    FALLBACK_ROUTE: "前の内容を見直すと進みやすいよ",
    "reinforce_current_unit": "今の単元をもう少し進めよう",
}

ROUTE_BODY_TEXT = {
    ADVANCE_ROUTE: "いまの単元がだいぶ安定してきたよ。次の内容にもチャレンジできそう。",
    FALLBACK_ROUTE: "土台をもう少し固めると、今の内容がもっとわかりやすくなるよ。",
    "reinforce_current_unit": "今の単元でできる形を増やしていく時間だよ。",
}

DIFFICULTY_TEXT = {
    1: "基本",
    2: "標準",
    3: "少しむずかしい",
}


def _preview_challenge_question(text: str | None, max_len: int = 72) -> str:
    t = (text or "").replace("\n", " ").strip()
    if len(t) > max_len:
        return t[: max_len - 1] + "…"
    return t


def _build_challenge_shop_groups(
    db: Session, unit_labels: dict[str, str], dependency_map: dict[str, UnitDependency]
) -> list[dict]:
    problems = db.scalars(
        select(Problem)
        .where(
            Problem.difficulty == 5,
            Problem.problem_type == "practice",
            Problem.status == "approved",
            Problem.subject == "math",
        )
        .order_by(func.coalesce(Problem.full_unit_id, Problem.unit, "").asc(), Problem.problem_id.asc())
    ).all()
    by_unit: dict[str, list[dict]] = {}
    for p in problems:
        uid = p.full_unit_id or p.unit
        by_unit.setdefault(uid, []).append(
            {
                "problem_id": p.problem_id,
                "preview": _preview_challenge_question(p.question_text),
            }
        )

    def _unit_sort_key(uid: str | None) -> tuple[int, str]:
        dep = dependency_map.get(uid) if uid is not None else None
        return (dep.display_order if dep else 9999, str(uid or ""))

    groups: list[dict] = []
    for uid in sorted(by_unit.keys(), key=_unit_sort_key):
        label = unit_labels.get(uid, uid or "その他")
        groups.append(
            {
                "unit_id": uid,
                "unit_name": label,
                "items": by_unit[uid],
            }
        )
    return groups


def _to_jst(value: datetime) -> datetime:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return aware.astimezone(JST)


def _load_recent_logs(db: Session, student_id: int, limit: int = 120) -> list[LearningLog]:
    stmt = (
        select(LearningLog)
        .where(LearningLog.student_id == student_id)
        .order_by(desc(LearningLog.created_at))
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def _today_and_week_stats(logs: list[LearningLog]) -> tuple[dict, dict]:
    today = datetime.now(JST).date()
    week_start = today - timedelta(days=6)
    today_logs = [log for log in logs if _to_jst(log.created_at).date() == today]
    week_logs = [log for log in logs if _to_jst(log.created_at).date() >= week_start]
    active_days = sorted({_to_jst(log.created_at).date().isoformat() for log in week_logs})

    def summarize(items: list[LearningLog]) -> dict:
        total_sec = sum(max(0, log.elapsed_sec or 0) for log in items)
        return {
            "count": len(items),
            "correct": sum(1 for log in items if log.is_correct),
            "hinted_correct": sum(1 for log in items if log.is_correct and (log.hint_used or 0) > 0),
            "minutes": round(total_sec / 60) if total_sec else 0,
        }

    today_summary = summarize(today_logs)
    week_summary = summarize(week_logs)
    week_summary["active_days"] = len(active_days)
    return today_summary, week_summary


def _current_correct_streak(logs: list[LearningLog]) -> int:
    streak = 0
    for log in logs:
        if log.is_correct:
            streak += 1
            continue
        break
    return streak


def _progress_tone(score: float, attempts: int) -> tuple[str, str]:
    if attempts == 0:
        return "progress-waiting", "これから"
    if score >= 0.75:
        return "progress-strong", "しっかりできている"
    if score >= 0.4:
        return "progress-growing", "少しずつ成長中"
    return "progress-support", "もう少しで安定"


def _position_label(full_unit_id: str | None, fallback_name: str | None) -> str:
    entry = get_unit_map_entry(full_unit_id)
    if entry and entry.get("display_name"):
        return entry["display_name"]
    return fallback_name or "これから進むところ"


def _learning_position(summary, dependency_map: dict[str, UnitDependency]) -> dict:
    current_dependency = dependency_map.get(summary.current_unit or "")
    previous_name = _position_label(
        summary.prerequisite_full_unit_id,
        dependency_map.get(current_dependency.prerequisite_unit_id).display_name
        if current_dependency and current_dependency.prerequisite_unit_id in dependency_map
        else None,
    )
    next_name = _position_label(
        summary.next_full_unit_id,
        dependency_map.get(current_dependency.next_unit_id).display_name
        if current_dependency and current_dependency.next_unit_id in dependency_map
        else None,
    )
    if not summary.prerequisite_full_unit_id and not (current_dependency and current_dependency.prerequisite_unit_id):
        previous_name = "ここからスタート"
    if not summary.next_full_unit_id and not (current_dependency and current_dependency.next_unit_id):
        next_name = "この単元のまとめ"

    current_name = summary.current_unit_display_name or (
        current_dependency.display_name if current_dependency else "いま取り組み中の単元"
    )
    if summary.current_position_summary:
        position_note = f"{summary.current_position_summary} を確認しているよ。"
    else:
        position_note = f"{current_name} を学習しているよ。"
    return {
        "current": current_name,
        "previous": previous_name,
        "next": next_name,
        "note": position_note,
    }


def _unit_progress_cards(summary) -> list[dict]:
    cards = []
    current_unit_id = summary.current_unit
    for unit in summary.unit_mastery_summary:
        attempts = unit["correct_count"] + unit["wrong_count"]
        tone_class, status_label = _progress_tone(unit["mastery_score"], attempts)
        progress_percent = int(round(unit["mastery_score"] * 100))
        message = "最初の1問から始めてみよう。"
        if attempts > 0 and unit["mastery_score"] >= 0.75:
            message = "かなり順調に進めているよ。"
        elif attempts > 0 and unit["mastery_score"] >= 0.4:
            message = "できる形が増えてきているよ。"
        elif attempts > 0:
            message = "あと少しで安定しそう。"
        cards.append(
            {
                "unit_id": unit["unit_id"],
                "display_name": unit["display_name"],
                "subject": unit.get("subject", "math"),
                "progress_percent": progress_percent,
                "status_label": status_label,
                "message": message,
                "tone_class": tone_class,
                "is_current": unit["unit_id"] == current_unit_id,
            }
        )
    return cards


def _build_today_cards(today_summary: dict, week_summary: dict, streak: int) -> list[dict]:
    total = today_summary["count"]
    correct = today_summary["correct"]
    hinted = today_summary["hinted_correct"]
    minutes = today_summary["minutes"]
    active_days = week_summary["active_days"]
    return [
        {
            "label": "今日といた問題",
            "value": total,
            "note": f"今日は{total}問がんばったね" if total else "今日はまだこれから。1問から始めてみよう",
        },
        {
            "label": "今日の正解",
            "value": correct,
            "note": f"{correct}問できたね" if correct else "あせらず1問ずつ進めれば大丈夫",
        },
        {
            "label": "連続正解",
            "value": streak,
            "note": f"{streak}問連続で正解できたね" if streak >= 2 else "次は連続正解をねらえるよ",
        },
        {
            "label": "ヒントで前進",
            "value": hinted,
            "note": f"{hinted}問でヒントを使って前に進めたね" if hinted else "必要なときはヒントを使っていいよ",
        },
        {
            "label": "学習時間",
            "value": f"{minutes}分" if minutes else "記録なし",
            "note": f"この7日で{active_days}日つづけているね" if active_days else "最初の一歩を踏み出してみよう",
        },
    ]


def _build_today_message(today_summary: dict, week_summary: dict, streak: int) -> str:
    if today_summary["count"] > 0:
        if streak >= 2:
            return "今日はいい流れで進められているよ。"
        if today_summary["correct"] >= today_summary["count"] / 2:
            return "今日はできた問題がしっかり増えているよ。"
        return "今日は考えながら前に進めているよ。"
    if week_summary["count"] > 0:
        return f"この7日で{week_summary['count']}問に取り組めているよ。次の1問で流れをつなごう。"
    return "まだ始めたばかり。ここから少しずつ進めていこう。"


def _build_strengths(summary, week_summary: dict, streak: int) -> list[str]:
    items: list[str] = []
    current_name = summary.current_unit_display_name or "今の単元"
    recent_correct_rate = summary.recent_signal_summary.get("recent_correct_rate", 0.0)
    if streak >= 2:
        items.append(f"{streak}問連続で正解できていて、いい流れで進めているよ。")
    if recent_correct_rate >= 0.75 and len(summary.recent_results) >= 4:
        items.append("最近の正解率が高まっていて、できる形が増えてきているよ。")
    if summary.hint_dependency_level == "low" and sum(1 for item in summary.recent_results[:5] if item["is_correct"]) >= 3:
        items.append("ヒントにたよりすぎずに進める場面が増えてきているよ。")
    if summary.mastery_score >= 0.6:
        items.append(f"{current_name}はだんだん安定してきているよ。")
    if week_summary["count"] >= 5:
        items.append(f"この7日で{week_summary['count']}問に取り組めていて、学習の流れができてきているよ。")

    if not items:
        diagnostic_text = DIAGNOSTIC_LABEL_TEXT.get(summary.diagnostic_label, "少しずつ前に進めているね。")
        items.append(f"{diagnostic_text}")
        items.append("今日のチャレンジを自信につなげていこう。")

    unique_items: list[str] = []
    for item in items:
        if item not in unique_items:
            unique_items.append(item)
    return unique_items[:3]


def _weak_point_support(summary) -> str | None:
    if not summary.weak_points:
        return None
    point = summary.weak_points[0]
    difficulty_text = DIFFICULTY_TEXT.get(point["difficulty"], "基本")
    current_unit = next(
        (unit["display_name"] for unit in summary.unit_mastery_summary if unit["unit_id"] == point["unit_id"]),
        None,
    )
    if current_unit is None:
        return None
    return f"{current_unit}の{difficulty_text}の問題をもう少し練習すると、もっと安定しそうだよ。"


def _build_recommendation(summary, position: dict) -> dict:
    intervention = summary.recommended_intervention
    route = summary.recommended_route
    support = _weak_point_support(summary)

    title = INTERVENTION_TITLE_TEXT.get(intervention) or ROUTE_TITLE_TEXT.get(route) or "次の1問に進もう"
    body = INTERVENTION_BODY_TEXT.get(intervention) or ROUTE_BODY_TEXT.get(route) or "今の流れのまま進めていこう。"

    if intervention == "fallback_prerequisite" and position["previous"] != "ここからスタート":
        body = f"{position['previous']}を見直してから戻ると、今の内容がわかりやすくなるよ。"
    elif intervention == ADVANCE_WITH_CONFIDENCE and position["next"] != "この単元のまとめ":
        body = f"次は{position['next']}にもチャレンジできそうだよ。"
    elif route == ADVANCE_ROUTE and position["next"] != "この単元のまとめ":
        body = f"{position['next']}へ進む準備ができてきたよ。"

    if support and intervention != ADVANCE_WITH_CONFIDENCE:
        body = support

    return {
        "title": title,
        "body": body,
        "badge": "これからのおすすめ",
        "reason": summary.intervention_reason,
    }


def _build_encouragement(summary, streak: int) -> str:
    if summary.recommended_intervention == ADVANCE_WITH_CONFIDENCE or summary.recommended_route == ADVANCE_ROUTE:
        return "少しずつ力がついてきているよ。このまま次の内容にもチャレンジしてみよう。"
    if summary.recommended_intervention == "fallback_prerequisite":
        return "いまは土台を整える大事な時間だよ。前の内容を見直してから進めば大丈夫。"
    if streak >= 2:
        return "いい流れで進められているよ。この調子で次の一問も進めよう。"
    if summary.diagnostic_label == "hint_dependent":
        return "ヒントを使いながらでも前に進めているよ。次は一つだけでも自分で考える時間を増やしてみよう。"
    return "今日のチャレンジがちゃんと力になっているよ。次もあわてず一問ずつ進めよう。"


def _hero_summary(summary, week_summary: dict) -> tuple[str, str]:
    current_name = summary.current_unit_display_name or "今の単元"
    diagnostic_text = DIAGNOSTIC_LABEL_TEXT.get(summary.diagnostic_label, "少しずつ力がついてきているね。")
    lead = f"いまは{current_name}をがんばっているよ。"
    if week_summary["count"] > 0:
        follow = f"{diagnostic_text} この7日で{week_summary['count']}問に取り組めたよ。"
    else:
        follow = diagnostic_text
    return lead, follow


def _cta(summary) -> dict:
    if summary.recommended_intervention == ADVANCE_WITH_CONFIDENCE or summary.recommended_route == ADVANCE_ROUTE:
        label = "次の問題へ"
        subtext = "次の内容に進めるよ。まずは1問ためしてみよう。"
    elif summary.recommended_intervention == "fallback_prerequisite":
        label = "復習してから進む"
        subtext = "前の内容を見直してから戻ると、もっと進みやすくなるよ。"
    else:
        label = "このまま続ける"
        subtext = "いまの調子のまま、そのまま学習を進めていこう。"
    return {
        "label": label,
        "href": f"/students/{summary.student_id}",
        "subtext": subtext,
    }


def build_student_progress_view(db: Session, student_id: int) -> dict | None:
    student = db.get(Student, student_id)
    if student is None:
        return None

    summary = build_student_summary(db, student_id, current_user_role="student")
    if summary is None:
        return None

    logs = _load_recent_logs(db, student_id)
    today_summary, week_summary = _today_and_week_stats(logs)
    streak = _current_correct_streak(logs)

    dependency_map = {
        item.unit_id: item
        for item in db.scalars(select(UnitDependency).order_by(UnitDependency.display_order.asc())).all()
    }
    position = _learning_position(summary, dependency_map)
    hero_lead, hero_follow = _hero_summary(summary, week_summary)

    unit_cards = _unit_progress_cards(summary)
    math_unit_cards = [u for u in unit_cards if u.get("subject", "math") == "math"]
    eng_unit_cards = [u for u in unit_cards if u.get("subject", "math") == "english"]
    cleared_units = [u for u in unit_cards if u["progress_percent"] >= 60]
    mastered_units = [u for u in unit_cards if u["progress_percent"] >= 75]
    avg_progress = (
        int(round(sum(u["progress_percent"] for u in unit_cards) / len(unit_cards)))
        if unit_cards else 0
    )

    # ===== すごろくボードデータ =====
    state = db.get(StudentState, student_id)
    gold = (state.gold if state else None) or 0
    current_unit = summary.current_unit

    # 現在ユニットのボードセル
    board_cells_raw = db.scalars(
        select(StudentBoardCell)
        .where(StudentBoardCell.student_id == student_id, StudentBoardCell.unit_id == current_unit)
        .order_by(StudentBoardCell.cell_index.asc())
    ).all() if current_unit else []

    board_cells = [
        {
            "cell_index": c.cell_index,
            "cell_type": c.cell_type,
            "is_correct": c.is_correct,
            "hint_used": c.hint_used,
            "ai_event_text": c.ai_event_text,
            "g_earned": c.g_earned,
        }
        for c in board_cells_raw
    ]

    # 過去ユニットのボード（折りたたみ）
    past_units_stmt = (
        select(StudentBoardCell.unit_id)
        .where(StudentBoardCell.student_id == student_id)
        .distinct()
    )
    past_unit_ids = [r[0] for r in db.execute(past_units_stmt).all() if r[0] != current_unit]

    past_boards = []
    unit_labels = {u.unit_id: u.display_name for u in db.scalars(select(UnitDependency)).all()}
    challenge_shop_groups = _build_challenge_shop_groups(db, unit_labels, dependency_map)
    for uid in past_unit_ids:
        cells = db.scalars(
            select(StudentBoardCell)
            .where(StudentBoardCell.student_id == student_id, StudentBoardCell.unit_id == uid)
            .order_by(StudentBoardCell.cell_index.asc())
        ).all()
        correct_count = sum(1 for c in cells if c.is_correct)
        total_g = sum(c.g_earned for c in cells)
        past_boards.append({
            "unit_id": uid,
            "unit_name": unit_labels.get(uid, uid),
            "cell_count": len(cells),
            "correct_count": correct_count,
            "total_g": total_g,
            "cells": [{"cell_type": c.cell_type, "ai_event_text": c.ai_event_text} for c in cells],
        })

    return {
        "student": {
            "student_id": student.student_id,
            "display_name": student.display_name,
        },
        "hero": {
            "title": "あなたの進みぐあい",
            "lead": hero_lead,
            "follow": hero_follow,
        },
        "today": {
            "cards": _build_today_cards(today_summary, week_summary, streak),
            "message": _build_today_message(today_summary, week_summary, streak),
        },
        "position": position,
        "unit_progress": unit_cards,
        "math_unit_progress": math_unit_cards,
        "eng_unit_progress": eng_unit_cards,
        "strengths": _build_strengths(summary, week_summary, streak),
        "recommendation": _build_recommendation(summary, position),
        "encouragement": _build_encouragement(summary, streak),
        "cta": _cta(summary),
        "current_status": DIAGNOSTIC_LABEL_TEXT.get(summary.diagnostic_label, "少しずつ力がついてきているね。"),
        "aqua": {
            "energy_pct": max(3, avg_progress),
            "cleared_count": len(cleared_units),
            "crystal_units": [u["display_name"] for u in mastered_units],
        },
        "board": {
            "current_unit_id": current_unit,
            "current_unit_name": unit_labels.get(current_unit, current_unit) if current_unit else "—",
            "cells": board_cells,
            "past_boards": past_boards,
        },
        "gold": gold,
        "can_buy_challenge": gold >= 100,
        "challenge_shop_groups": challenge_shop_groups,
        "has_challenge_problems": len(challenge_shop_groups) > 0,
    }
