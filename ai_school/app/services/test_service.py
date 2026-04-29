"""テストセッション管理サービス (mini_test / unit_test)"""
import json
import random
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Problem, Student, TestSession, UnitMastery
from .math_text_service import pair_for_student_numeric_result_display

_MINI_TEST_SIZE = 5
_UNIT_TEST_SIZE = 10

MINI_TEST_TIME_LIMIT_SEC = 300
UNIT_TEST_TIME_LIMIT_SEC = 600

# テスト発動マスタリー閾値
_MINI_TEST_MASTERY_THRESHOLD = 0.60
_MINI_TEST_CORRECT_THRESHOLD = 5
_UNIT_TEST_MASTERY_THRESHOLD = 0.80
_UNIT_TEST_CORRECT_THRESHOLD = 8

# 同一単元で再テストを抑制する期間（日）
_RETEST_SUPPRESS_DAYS = 7

_SCOPE_LABELS = {
    "mini_test": "ミニテスト",
    "unit_test": "単元テスト",
}


def _test_time_limit_for_scope(test_scope: str) -> int:
    return MINI_TEST_TIME_LIMIT_SEC if test_scope == "mini_test" else UNIT_TEST_TIME_LIMIT_SEC


def _parse_deferred(session: TestSession) -> list[int]:
    raw = getattr(session, "deferred_problem_ids", None) or "[]"
    try:
        return [int(x) for x in json.loads(raw)]
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def _answer_row_status(row: dict) -> str:
    st = row.get("answer_status")
    if st in ("correct", "wrong", "unanswered"):
        return st
    return "correct" if row.get("is_correct") else "wrong"


def _count_correct_answers(answers: list[dict]) -> int:
    return sum(1 for a in answers if _answer_row_status(a) == "correct")


def _count_wrong_answers(answers: list[dict]) -> int:
    return sum(1 for a in answers if _answer_row_status(a) == "wrong")


def _count_unanswered_answers(answers: list[dict]) -> int:
    return sum(1 for a in answers if _answer_row_status(a) == "unanswered")


def get_test_remaining_seconds(session: TestSession) -> int:
    """進行中テストの残り秒数。完了済みは 0。"""
    if session.status != "in_progress":
        return 0
    limit = int(getattr(session, "time_limit_sec", 0) or 0)
    if limit <= 0:
        return 0
    deadline = session.started_at + timedelta(seconds=limit)
    rem = (deadline - datetime.utcnow()).total_seconds()
    return max(0, int(rem))


def finalize_test_session_timeout(db: Session, session: TestSession) -> None:
    """時間切れ: 未回答を unanswered で確定し完了する。"""
    if session.status != "in_progress":
        return
    answers: list[dict] = json.loads(session.answers)
    answered_ids = {a["problem_id"] for a in answers}
    for pid in json.loads(session.problem_ids):
        if pid not in answered_ids:
            answers.append(
                {
                    "problem_id": pid,
                    "answer": "",
                    "is_correct": False,
                    "elapsed_sec": 0,
                    "hint_used": 0,
                    "answer_status": "unanswered",
                }
            )
    completed = datetime.utcnow()
    session.answers = json.dumps(answers, ensure_ascii=False)
    session.score_correct = _count_correct_answers(answers)
    session.completed_at = completed
    session.status = "completed"
    session.time_expired = True
    session.time_spent_sec = int((completed - session.started_at).total_seconds())
    db.add(session)
    db.commit()
    db.refresh(session)


def check_and_finalize_test_if_expired(db: Session, session: TestSession | None) -> bool:
    """期限切れなら finalize して True。"""
    if session is None or session.status != "in_progress":
        return False
    if get_test_remaining_seconds(session) > 0:
        return False
    finalize_test_session_timeout(db, session)
    return True


def complete_test_session_normal(db: Session, session: TestSession) -> bool:
    """全問に解答レコードがあるとき完了処理（通常終了）。"""
    if session.status != "in_progress":
        return False
    problem_ids: list[int] = json.loads(session.problem_ids)
    answers: list[dict] = json.loads(session.answers)
    answered_ids = {a["problem_id"] for a in answers}
    if len(answered_ids) < len(problem_ids):
        return False
    completed = datetime.utcnow()
    session.score_correct = _count_correct_answers(answers)
    session.completed_at = completed
    session.status = "completed"
    session.time_expired = False
    session.time_spent_sec = int((completed - session.started_at).total_seconds())
    db.add(session)
    db.commit()
    db.refresh(session)
    return True


def count_pending_deferred(session: TestSession) -> int:
    """あとで解くキューにあり、まだ解答がない問題数。"""
    deferred = _parse_deferred(session)
    if not deferred:
        return 0
    answered = {a["problem_id"] for a in json.loads(session.answers)}
    return sum(1 for pid in deferred if pid not in answered)


def defer_test_problem(db: Session, session: TestSession, student_id: int, problem_id: int) -> None:
    if session.student_id != student_id or session.status != "in_progress":
        raise ValueError("invalid session")
    if get_test_remaining_seconds(session) <= 0:
        raise ValueError("time expired")
    current = get_current_test_problem(db, session)
    if current is None or current.problem_id != problem_id:
        raise ValueError("not current problem")
    deferred = _parse_deferred(session)
    deferred = [x for x in deferred if x != problem_id]
    deferred.append(problem_id)
    session.deferred_problem_ids = json.dumps(deferred)
    session.defer_count = int(getattr(session, "defer_count", 0) or 0) + 1
    db.add(session)
    db.commit()
    db.refresh(session)


def test_session_summary_row(session: TestSession) -> dict:
    """教師画面用の1行サマリー。"""
    answers = json.loads(session.answers)
    return {
        "wrong_count": _count_wrong_answers(answers),
        "unanswered_count": _count_unanswered_answers(answers),
        "defer_count": int(getattr(session, "defer_count", 0) or 0),
        "time_limit_sec": int(getattr(session, "time_limit_sec", 0) or 0),
        "time_spent_sec": session.time_spent_sec,
        "time_expired": bool(getattr(session, "time_expired", False)),
    }


# ---------------------------------------------------------------------------
# テスト発動判定
# ---------------------------------------------------------------------------

def should_trigger_test(db: Session, student_id: int, unit_id: str) -> str | None:
    """テストを受けるべきなら 'mini_test' または 'unit_test' を返す。なければ None。"""
    mastery = db.get(UnitMastery, (student_id, unit_id))
    if mastery is None:
        return None

    # 進行中テストがあれば発動しない
    if get_active_test_session(db, student_id) is not None:
        return None

    # 直近 N 日以内に同単元のテストを完了済みなら発動しない
    cutoff = datetime.utcnow() - timedelta(days=_RETEST_SUPPRESS_DAYS)
    recent = db.scalar(
        select(TestSession)
        .where(
            TestSession.student_id == student_id,
            TestSession.unit_id == unit_id,
            TestSession.status == "completed",
            TestSession.started_at >= cutoff,
        )
        .limit(1)
    )
    if recent is not None:
        return None

    unit_test_count = db.scalar(
        select(func.count(Problem.problem_id)).where(
            Problem.full_unit_id == unit_id,
            Problem.problem_type == "unit_test",
        )
    ) or 0
    mini_test_count = db.scalar(
        select(func.count(Problem.problem_id)).where(
            Problem.full_unit_id == unit_id,
            Problem.problem_type == "mini_test",
        )
    ) or 0

    if (
        mastery.mastery_score >= _UNIT_TEST_MASTERY_THRESHOLD
        and mastery.correct_count >= _UNIT_TEST_CORRECT_THRESHOLD
        and unit_test_count >= _UNIT_TEST_SIZE
    ):
        return "unit_test"

    if (
        mastery.mastery_score >= _MINI_TEST_MASTERY_THRESHOLD
        and mastery.correct_count >= _MINI_TEST_CORRECT_THRESHOLD
        and mini_test_count >= _MINI_TEST_SIZE
    ):
        return "mini_test"

    return None


# ---------------------------------------------------------------------------
# テスト問題取得
# ---------------------------------------------------------------------------

def _get_test_problems_for_unit(db: Session, unit_id: str, test_scope: str, count: int) -> list[Problem]:
    subject = 'english' if unit_id.startswith('eng_') else 'math'
    stmt = (
        select(Problem)
        .where(Problem.full_unit_id == unit_id, Problem.subject == subject, Problem.problem_type == test_scope)
        .order_by(Problem.difficulty.asc(), Problem.problem_id.asc())
    )
    problems = list(db.scalars(stmt).all())
    if not problems:
        return []
    if len(problems) <= count:
        return problems
    # 難易度バランスを保ちながらランダムサンプリング
    random.shuffle(problems)
    return problems[:count]


# ---------------------------------------------------------------------------
# テストセッション管理
# ---------------------------------------------------------------------------

def start_test_session(db: Session, student_id: int, unit_id: str, test_scope: str) -> TestSession | None:
    """新しいテストセッションを開始する。問題がなければ None を返す。"""
    count = _MINI_TEST_SIZE if test_scope == "mini_test" else _UNIT_TEST_SIZE
    problems = _get_test_problems_for_unit(db, unit_id, test_scope, count)
    if not problems:
        return None

    full_unit_id = problems[0].full_unit_id
    limit = _test_time_limit_for_scope(test_scope)

    session = TestSession(
        student_id=student_id,
        unit_id=unit_id,
        full_unit_id=full_unit_id,
        test_scope=test_scope,
        status="in_progress",
        problem_ids=json.dumps([p.problem_id for p in problems]),
        answers="[]",
        score_correct=0,
        score_total=len(problems),
        started_at=datetime.utcnow(),
        time_limit_sec=limit,
        time_spent_sec=None,
        time_expired=False,
        deferred_problem_ids=json.dumps([]),
        defer_count=0,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_active_test_session(db: Session, student_id: int) -> TestSession | None:
    """進行中のテストセッションを返す。"""
    return db.scalar(
        select(TestSession)
        .where(
            TestSession.student_id == student_id,
            TestSession.status == "in_progress",
        )
        .order_by(TestSession.started_at.desc())
        .limit(1)
    )


def get_test_session_by_id(db: Session, session_id: int) -> TestSession | None:
    return db.get(TestSession, session_id)


def get_current_test_problem(db: Session, session: TestSession) -> Problem | None:
    """テストセッション内で次に回答すべき問題を返す（あとで解くは後回し）。"""
    problem_ids: list[int] = json.loads(session.problem_ids)
    answers: list[dict] = json.loads(session.answers)
    answered_ids = {a["problem_id"] for a in answers}
    deferred_set = set(_parse_deferred(session))

    for pid in problem_ids:
        if pid in answered_ids:
            continue
        if pid in deferred_set:
            continue
        return db.get(Problem, pid)

    for pid in _parse_deferred(session):
        if pid not in answered_ids:
            return db.get(Problem, pid)
    return None


def record_test_answer(
    db: Session,
    session: TestSession,
    problem_id: int,
    answer: str,
    is_correct: bool,
    elapsed_sec: int,
    hint_used: int,
) -> bool:
    """テストセッションに回答を記録する。テスト完了なら True を返す。"""
    answers: list[dict] = json.loads(session.answers)

    # 二重登録防止
    if any(a["problem_id"] == problem_id for a in answers):
        problem_ids: list[int] = json.loads(session.problem_ids)
        return len(answers) >= len(problem_ids)

    st = "correct" if is_correct else "wrong"
    was_in_deferred = problem_id in set(_parse_deferred(session))

    answers.append(
        {
            "problem_id": problem_id,
            "answer": answer,
            "is_correct": is_correct,
            "elapsed_sec": elapsed_sec,
            "hint_used": hint_used,
            "answer_status": st,
            "returned_after_defer": was_in_deferred,
        }
    )
    session.answers = json.dumps(answers, ensure_ascii=False)
    session.score_correct = _count_correct_answers(answers)

    problem_ids = json.loads(session.problem_ids)
    is_complete = len(answers) >= len(problem_ids)

    if is_complete:
        completed = datetime.utcnow()
        session.status = "completed"
        session.completed_at = completed
        session.time_expired = False
        session.time_spent_sec = int((completed - session.started_at).total_seconds())

    db.add(session)
    db.commit()
    db.refresh(session)
    return is_complete


# ---------------------------------------------------------------------------
# テスト結果
# ---------------------------------------------------------------------------

def get_test_result_detail(db: Session, session: TestSession) -> dict:
    """結果画面表示用の詳細データを構築する。"""
    answers: list[dict] = json.loads(session.answers)

    detail_answers = []
    for a in answers:
        problem = db.get(Problem, a["problem_id"])
        status = _answer_row_status(a)
        sm, sa = pair_for_student_numeric_result_display(
            a["answer"],
            subject=problem.subject if problem else None,
            answer_type=problem.answer_type if problem else None,
        )
        cm, ca = pair_for_student_numeric_result_display(
            problem.correct_answer if problem else "",
            subject=problem.subject if problem else None,
            answer_type=problem.answer_type if problem else None,
        )
        detail_answers.append(
            {
                "problem_id": a["problem_id"],
                "question_text": problem.question_text if problem else "",
                "unit": problem.unit if problem else "",
                "difficulty": problem.difficulty if problem else 0,
                "correct_answer": problem.correct_answer if problem else "",
                "submitted_answer": a["answer"],
                "submitted_main": sm,
                "submitted_aux": sa,
                "correct_main": cm,
                "correct_aux": ca,
                "is_correct": a["is_correct"],
                "answer_status": status,
                "elapsed_sec": a["elapsed_sec"],
                "hint_used": a.get("hint_used", 0),
            }
        )

    percentage = (
        round(session.score_correct / session.score_total * 100) if session.score_total > 0 else 0
    )

    if percentage >= 80:
        pass_status = "pass"
        message = "すばらしい！しっかり身についています！"
        message_en = "Excellent!"
    elif percentage >= 60:
        pass_status = "partial"
        message = "もう少し！あと一踏ん張りしてみよう。"
        message_en = "Almost there!"
    else:
        pass_status = "fail"
        message = "一緒に復習して、次は解けるようにしよう！"
        message_en = "Let's review together!"

    scope_label = _SCOPE_LABELS.get(session.test_scope, session.test_scope)
    wrong_count = _count_wrong_answers(answers)
    unanswered_count = _count_unanswered_answers(answers)

    return {
        "session": session,
        "scope_label": scope_label,
        "score_correct": session.score_correct,
        "score_total": session.score_total,
        "wrong_count": wrong_count,
        "unanswered_count": unanswered_count,
        "percentage": percentage,
        "pass_status": pass_status,
        "message": message,
        "message_en": message_en,
        "answers": detail_answers,
        "time_expired": bool(getattr(session, "time_expired", False)),
        "time_limit_sec": int(getattr(session, "time_limit_sec", 0) or 0),
        "time_spent_sec": session.time_spent_sec,
        "defer_count": int(getattr(session, "defer_count", 0) or 0),
    }


# ---------------------------------------------------------------------------
# 教師ダッシュボード用
# ---------------------------------------------------------------------------

def get_recent_test_sessions_for_student(
    db: Session, student_id: int, limit: int = 5
) -> list[TestSession]:
    return list(
        db.scalars(
            select(TestSession)
            .where(
                TestSession.student_id == student_id,
                TestSession.status == "completed",
            )
            .order_by(TestSession.started_at.desc())
            .limit(limit)
        ).all()
    )


def get_recent_test_sessions_for_classroom(
    db: Session, student_ids: list[int], limit: int = 30
) -> list[tuple]:
    if not student_ids:
        return []
    stmt = (
        select(TestSession, Student)
        .join(Student, TestSession.student_id == Student.student_id)
        .where(
            TestSession.student_id.in_(student_ids),
            TestSession.status == "completed",
        )
        .order_by(TestSession.started_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).all())


def scope_label(scope: str) -> str:
    return _SCOPE_LABELS.get(scope, scope)
