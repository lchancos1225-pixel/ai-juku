"""SM-2ベースの忘却曲線復習スケジューリングサービス。

SM-2アルゴリズム概要:
- q（品質スコア）: 0=完全不正解, 1=不正解+ヒントあり, 3=ヒントありで正解, 4=正解, 5=素早く正解
- ease_factor（EF）: 問題の難易度係数。初期2.5、最小1.3。q<3で減少、q>=3で増加。
- interval: 次の復習までの日数。repetitions=0→1日, 1→6日, 以降はEF倍。
- q<3の場合はrepetitionsをリセット（再学習）。

参考: https://www.supermemo.com/en/blog/application-of-a-computer-to-improve-the-results-obtained-in-working-with-the-supermemo-method
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Problem, ProblemReview


INITIAL_EASE_FACTOR = 2.5
MIN_EASE_FACTOR = 1.3


def _compute_next_interval(repetitions: int, interval: int, ease_factor: float) -> int:
    """次の復習間隔（日数）を計算する。"""
    if repetitions == 0:
        return 1
    if repetitions == 1:
        return 6
    return max(1, round(interval * ease_factor))


def _compute_ease_factor(ease_factor: float, q: int) -> float:
    """品質スコア q に基づいて ease_factor を更新する。"""
    new_ef = ease_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    return max(MIN_EASE_FACTOR, new_ef)


def update_review_schedule(
    db: Session,
    student_id: int,
    problem: Problem,
    is_correct: bool,
    hint_used: int,
    elapsed_sec: int,
) -> ProblemReview:
    """回答結果に基づいて復習スケジュールを更新（または新規作成）する。

    mini_test / unit_test 問題は復習対象から除外する（practice のみ）。
    """
    # テスト問題は復習スケジュール管理しない
    if problem.problem_type in ("mini_test", "unit_test"):
        return None

    # 品質スコアを算出
    if not is_correct:
        q = 1 if hint_used >= 1 else 0
    elif hint_used >= 2:
        q = 3
    elif hint_used >= 1:
        q = 3
    elif elapsed_sec <= 10:
        q = 5  # 素早く正解
    else:
        q = 4  # 通常正解

    today = date.today().isoformat()

    review = db.get(ProblemReview, (student_id, problem.problem_id))
    if review is None:
        review = ProblemReview(
            student_id=student_id,
            problem_id=problem.problem_id,
            repetitions=0,
            interval=1,
            ease_factor=INITIAL_EASE_FACTOR,
            next_review_date=today,
        )

    if q < 3:
        # 不正解系: repetitionsをリセット、翌日に復習
        review.repetitions = 0
        review.interval = 1
        next_date = date.today() + timedelta(days=1)
    else:
        # 正解系: SM-2で次の間隔を計算
        new_interval = _compute_next_interval(review.repetitions, review.interval, review.ease_factor)
        review.repetitions += 1
        review.interval = new_interval
        review.ease_factor = _compute_ease_factor(review.ease_factor, q)
        next_date = date.today() + timedelta(days=new_interval)

    review.next_review_date = next_date.isoformat()
    db.add(review)
    return review


def get_due_reviews(
    db: Session,
    student_id: int,
    today: str | None = None,
    limit: int = 10,
) -> list[tuple[ProblemReview, Problem]]:
    """今日復習すべき問題一覧を返す（next_review_date <= today かつ q<3 が一度でもあった問題）。

    repetitions=0 かつ today が next_review_date 以降 のもの（＝一度でも失敗した問題）を返す。
    """
    if today is None:
        today = date.today().isoformat()

    stmt = (
        select(ProblemReview, Problem)
        .join(Problem, ProblemReview.problem_id == Problem.problem_id)
        .where(
            ProblemReview.student_id == student_id,
            ProblemReview.next_review_date <= today,
        )
        .order_by(ProblemReview.next_review_date)
        .limit(limit)
    )
    return db.execute(stmt).all()


def count_due_reviews(db: Session, student_id: int, today: str | None = None) -> int:
    """今日復習すべき問題数を返す。"""
    if today is None:
        today = date.today().isoformat()

    stmt = (
        select(ProblemReview)
        .where(
            ProblemReview.student_id == student_id,
            ProblemReview.next_review_date <= today,
        )
    )
    return len(db.scalars(stmt).all())


def get_next_review_problem(
    db: Session,
    student_id: int,
    today: str | None = None,
) -> Problem | None:
    """復習キューから次の1問を返す。"""
    if today is None:
        today = date.today().isoformat()

    stmt = (
        select(Problem)
        .join(ProblemReview, ProblemReview.problem_id == Problem.problem_id)
        .where(
            ProblemReview.student_id == student_id,
            ProblemReview.next_review_date <= today,
        )
        .order_by(ProblemReview.next_review_date)
        .limit(1)
    )
    return db.scalar(stmt)
