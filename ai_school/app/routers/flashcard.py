"""単語帳モジュール — 4段階学習ルーター。

Stage 1: インプット（英単語 + 品詞 + 発音記号 + 例文 + Web Speech API 音声）
Stage 2: 認識（日本語を見て英語4択）
Stage 3: 定着（日本語を見てキーボードタイピング）
Stage 4: 実践（音声のみ聞いて日本語4択）
→ SM-2 による忘却曲線レビュー（stage_cleared=4 の単語を後日再出題）
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Flashcard, FlashcardProgress, Student
from ..services.auth_service import require_student_login
from ..paths import TEMPLATES_DIR

router = APIRouter(prefix="/students/{student_id}/flashcards", tags=["flashcards"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)

INITIAL_EASE = 2.5
MIN_EASE = 1.3

# ── セット表示名（unit_id → 日本語名） ───────────────────────────────────────────
UNIT_DISPLAY_NAMES: dict[str, str] = {
    # 中1 (grade 7)
    "eng_alphabet_basic":        "アルファベット・基本",
    "eng_be_verb":               "be動詞",
    "eng_verbs_1":               "一般動詞①",
    "eng_verbs_2":               "一般動詞②",
    "eng_verbs_3":               "一般動詞③",
    "eng_verbs_4":               "一般動詞④",
    "eng_verbs_5":               "一般動詞⑤",
    "eng_school_verbs":          "学校の動詞",
    "eng_school_nouns":          "学校の名詞",
    "eng_people_time":           "人・時間",
    "eng_adjectives_basic":      "形容詞・基本",
    "eng_nature_weather":        "自然・天気",
    "eng_food_drink":            "食べ物・飲み物",
    "eng_present_progressive":   "現在進行形",
    "eng_question_negative":     "疑問文・否定文",
    "eng_third_person_singular": "三人称単数",
    "eng_can_modal":             "can（助動詞）",
    "eng_numbers_ordinals":      "数字・序数",
    "eng_days_months":           "曜日・月・季節",
    "eng_body_parts":            "体の部位",
    "eng_home_furniture":        "家・部屋・家具",
    "eng_town_places":           "街・場所・施設",
    "eng_transportation":        "乗り物・交通",
    "eng_emotions_expanded":     "感情・状態（拡充）",
    "eng_colors_shapes":         "色・形・大きさ",
    "eng_clothes_items":         "衣類・持ち物",
    "eng_irregular_past_g1":     "不規則動詞の過去形",
    "eng_daily_actions":         "日常の動作",
    "eng_animals_nature_g1":     "動物・自然（基礎）",
    # 中2 (grade 8)
    "eng_past_tense":            "過去形",
    "eng_future_tense":          "未来の表現",
    "eng_infinitive":            "不定詞・基本",
    "eng_gerund":                "動名詞",
    "eng_sentence_patterns":     "文型パターン",
    "eng_conjunctions":          "接続詞",
    "eng_modal_verbs":           "助動詞",
    "eng_travel_culture":        "旅行・文化",
    "eng_environment":           "環境",
    "eng_technology":            "テクノロジー",
    "eng_business":              "ビジネス",
    "eng_verbs_advanced":        "動詞・発展",
    "eng_irregular_past_g2":     "不規則動詞の過去形（中2）",
    "eng_comparison":            "比較表現",
    "eng_hobbies_sports":        "趣味・スポーツ",
    "eng_feelings_opinions":     "気持ち・意見",
    "eng_daily_life_g2":         "日常生活・ルーティン",
    "eng_school_subjects":       "学校教科・学習活動",
    "eng_people_relationships":  "人間関係・社会",
    "eng_health_body_g2":        "健康・病気",
    "eng_media_communication":   "メディア・コミュニケーション",
    "eng_science_nature_g2":     "理科・自然（中2）",
    "eng_adjectives_g2":         "形容詞・副詞（中2）",
    # 中3 (grade 9)
    "eng_present_perfect":       "現在完了形",
    "eng_passive_voice":         "受動態",
    "eng_relative_pronoun":      "関係代名詞",
    "eng_infinitive_advanced":   "不定詞・発展",
    "eng_participle":            "分詞",
    "eng_subjunctive":           "仮定法",
    "eng_society_politics":      "社会・政治",
    "eng_academic_thinking":     "学術思考",
    "eng_communication":         "コミュニケーション",
    "eng_health_medical":        "健康・医療",
    "eng_planning_change":       "計画・変化",
    "eng_academic_writing":      "学術ライティング",
    "eng_adverbs_connectors":    "副詞・接続詞",
    "eng_adjectives_advanced":   "形容詞（発展）",
    "eng_compound_terms":        "複合語・専門用語",
}


# ── ヘルパー ───────────────────────────────────────────────────────────────────

def _get_student_or_404(db: Session, student_id: int) -> Student:
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


def _get_progress(db: Session, student_id: int, flashcard_id: int) -> FlashcardProgress | None:
    return db.get(FlashcardProgress, (student_id, flashcard_id))


def _ensure_progress(db: Session, student_id: int, flashcard_id: int) -> FlashcardProgress:
    prog = _get_progress(db, student_id, flashcard_id)
    if prog is None:
        prog = FlashcardProgress(
            student_id=student_id,
            flashcard_id=flashcard_id,
            stage_cleared=0,
            repetitions=0,
            interval=1,
            ease_factor=INITIAL_EASE,
        )
        db.add(prog)
    return prog


def _sm2_update(prog: FlashcardProgress, is_correct: bool) -> None:
    """SM-2 アルゴリズムで next_review_date を更新。"""
    q = 4 if is_correct else 1
    new_ef = prog.ease_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    prog.ease_factor = max(MIN_EASE, new_ef)

    if not is_correct:
        prog.repetitions = 0
        prog.interval = 1
    else:
        if prog.repetitions == 0:
            prog.interval = 1
        elif prog.repetitions == 1:
            prog.interval = 6
        else:
            prog.interval = max(1, round(prog.interval * prog.ease_factor))
        prog.repetitions += 1

    prog.next_review_date = (date.today() + timedelta(days=prog.interval)).isoformat()


def _pick_wrong_choices(db: Session, card: Flashcard, n: int = 3) -> list[str]:
    """ランダムに n 個の不正解選択肢（日本語）を返す。"""
    stmt = (
        select(Flashcard.japanese)
        .where(Flashcard.flashcard_id != card.flashcard_id)
        .order_by(Flashcard.flashcard_id)  # 安定ソート後にランダム化
    )
    all_ja = [r for r in db.scalars(stmt).all() if r != card.japanese]
    random.shuffle(all_ja)
    return all_ja[:n]


def _get_next_card(db: Session, student_id: int, unit_id: str | None, grade: int | None) -> Flashcard | None:
    """学習対象の次のカードを返す。優先順: レビュー期限 > 未学習。"""
    today = date.today().isoformat()

    # ベースクエリ
    base = select(Flashcard)
    if unit_id:
        base = base.where(Flashcard.unit_id == unit_id)
    elif grade:
        base = base.where(Flashcard.grade == grade)

    all_cards = db.scalars(base).all()

    # レビュー期限のカード（stage_cleared=4）
    for card in all_cards:
        prog = _get_progress(db, student_id, card.flashcard_id)
        if prog and prog.stage_cleared >= 4 and prog.next_review_date and prog.next_review_date <= today:
            return card

    # 未学習または未完了のカード（stage_cleared < 4）
    for card in all_cards:
        prog = _get_progress(db, student_id, card.flashcard_id)
        if prog is None or prog.stage_cleared < 4:
            return card

    return None


def _count_due_flashcards(db: Session, student_id: int) -> int:
    today = date.today().isoformat()
    stmt = (
        select(FlashcardProgress)
        .where(
            FlashcardProgress.student_id == student_id,
            FlashcardProgress.stage_cleared >= 4,
            FlashcardProgress.next_review_date <= today,
        )
    )
    return len(db.scalars(stmt).all())


def _count_new_flashcards(db: Session, student_id: int) -> int:
    """まだ stage_cleared < 4 のカード数（新規学習対象）。"""
    all_ids = set(db.scalars(select(Flashcard.flashcard_id)).all())
    done_ids = set(
        db.scalars(
            select(FlashcardProgress.flashcard_id)
            .where(
                FlashcardProgress.student_id == student_id,
                FlashcardProgress.stage_cleared >= 4,
            )
        ).all()
    )
    return len(all_ids - done_ids)


# ── エンドポイント ───────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
def flashcard_home(request: Request, student_id: int, db: Session = Depends(get_db)):
    """単語帳ホーム：単元別セット一覧。"""
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth

    student = _get_student_or_404(db, student_id)
    today = date.today().isoformat()

    # 単元ごとの進捗サマリー
    units_stmt = select(Flashcard.unit_id, Flashcard.grade).distinct()
    unit_combos = db.execute(units_stmt).all()

    sets = []
    seen_units: set[str | None] = set()
    for unit_id, grade in sorted(unit_combos, key=lambda x: (x[1], x[0] or "")):
        if unit_id in seen_units:
            continue
        seen_units.add(unit_id)

        total_count = len(db.scalars(select(Flashcard.flashcard_id).where(Flashcard.unit_id == unit_id)).all())
        done_count = len(
            db.scalars(
                select(FlashcardProgress.flashcard_id)
                .where(
                    FlashcardProgress.student_id == student_id,
                    FlashcardProgress.stage_cleared >= 4,
                    FlashcardProgress.flashcard_id.in_(
                        select(Flashcard.flashcard_id).where(Flashcard.unit_id == unit_id)
                    ),
                )
            ).all()
        )
        review_count = len(
            db.scalars(
                select(FlashcardProgress.flashcard_id)
                .where(
                    FlashcardProgress.student_id == student_id,
                    FlashcardProgress.stage_cleared >= 4,
                    FlashcardProgress.next_review_date <= today,
                    FlashcardProgress.flashcard_id.in_(
                        select(Flashcard.flashcard_id).where(Flashcard.unit_id == unit_id)
                    ),
                )
            ).all()
        )
        sets.append({
            "unit_id": unit_id,
            "grade": grade,
            "grade_label": f"中{grade - 6}",
            "display_name": UNIT_DISPLAY_NAMES.get(unit_id, unit_id.replace("eng_", "").replace("_", " ").title()),
            "total": total_count,
            "done": done_count,
            "review": review_count,
        })

    # 全体進捗サマリー
    total_all = sum(s["total"] for s in sets)
    done_all = sum(s["done"] for s in sets)
    review_all = sum(s["review"] for s in sets)

    return templates.TemplateResponse(
        "student_flashcard_home.html",
        {
            "request": request,
            "student": student,
            "sets": sets,
            "total_all": total_all,
            "done_all": done_all,
            "review_all": review_all,
            "student_grade": student.grade,
            "is_student_view": True,
        },
    )


@router.get("/study", response_class=HTMLResponse)
def flashcard_study(
    request: Request,
    student_id: int,
    unit_id: str | None = None,
    grade: int | None = None,
    db: Session = Depends(get_db),
):
    """4段階学習画面。次のカードと現在のステージを決定して表示。"""
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth

    student = _get_student_or_404(db, student_id)
    card = _get_next_card(db, student_id, unit_id, grade)

    if card is None:
        # 全カード完了
        return templates.TemplateResponse(
            "student_flashcard_done.html",
            {"request": request, "student": student, "unit_id": unit_id, "is_student_view": True},
        )

    prog = _get_progress(db, student_id, card.flashcard_id)
    today = date.today().isoformat()

    # stage 決定: review(stage_cleared=4 & 期限) → stage2、それ以外 → stage_cleared+1
    if prog and prog.stage_cleared >= 4 and prog.next_review_date and prog.next_review_date <= today:
        stage = 2  # レビューは認識クイズのみ
        is_review = True
    else:
        stage = (prog.stage_cleared + 1) if prog else 1
        stage = min(stage, 4)
        is_review = False

    # 4択用の選択肢（Stage 2 / Stage 4）
    choices = []
    if stage in (2, 4):
        wrong = _pick_wrong_choices(db, card, n=3)
        choices = wrong + [card.japanese]
        random.shuffle(choices)

    return templates.TemplateResponse(
        "student_flashcard_study.html",
        {
            "request": request,
            "student": student,
            "card": card,
            "stage": stage,
            "is_review": is_review,
            "choices": choices,
            "unit_id": unit_id,
            "grade": grade,
            "is_student_view": True,
        },
    )


@router.post("/answer", response_class=HTMLResponse)
def flashcard_answer(
    request: Request,
    student_id: int,
    flashcard_id: int = Form(...),
    stage: int = Form(...),
    answer: str = Form(""),
    is_review: int = Form(0),
    unit_id: str | None = Form(None),
    grade: int | None = Form(None),
    db: Session = Depends(get_db),
):
    """各ステージの回答を受け取り、進捗を更新して次へ。"""
    auth = require_student_login(request, student_id)
    if auth is not None:
        return auth

    _get_student_or_404(db, student_id)
    card = db.get(Flashcard, flashcard_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Flashcard not found")

    prog = _ensure_progress(db, student_id, flashcard_id)

    if stage == 1:
        # インプット: 常に「見た」として通過
        prog.stage_cleared = max(prog.stage_cleared, 1)
        db.commit()
    elif stage == 2:
        # 認識: 4択で日本語を当てる
        is_correct = answer.strip() == card.japanese.strip()
        if is_correct:
            if bool(is_review):
                _sm2_update(prog, is_correct=True)
            else:
                prog.stage_cleared = max(prog.stage_cleared, 2)
            db.commit()
            # 次のステージへ
        else:
            if bool(is_review):
                # レビュー失敗 → Stage 1 から再学習
                prog.stage_cleared = 0
                _sm2_update(prog, is_correct=False)
            else:
                prog.stage_cleared = max(prog.stage_cleared, 0)
            db.commit()
            # 不正解フィードバック画面
            redirect = _build_study_url(student_id, unit_id, grade)
            return templates.TemplateResponse(
                "student_flashcard_wrong.html",
                {
                    "request": request,
                    "card": card,
                    "stage": stage,
                    "student_id": student_id,
                    "next_url": redirect,
                },
            )
    elif stage == 3:
        # 定着: キーボードタイピング（大文字小文字・前後スペース無視）
        is_correct = answer.strip().lower() == card.english.strip().lower()
        if is_correct:
            prog.stage_cleared = max(prog.stage_cleared, 3)
            db.commit()
        else:
            db.commit()
            redirect = _build_study_url(student_id, unit_id, grade)
            return templates.TemplateResponse(
                "student_flashcard_wrong.html",
                {
                    "request": request,
                    "card": card,
                    "stage": stage,
                    "student_id": student_id,
                    "next_url": redirect,
                },
            )
    elif stage == 4:
        # 実践: 音声のみ聞いて日本語4択
        is_correct = answer.strip() == card.japanese.strip()
        if is_correct:
            prog.stage_cleared = 4
            _sm2_update(prog, is_correct=True)
            db.commit()
        else:
            prog.stage_cleared = max(prog.stage_cleared, 0)
            _sm2_update(prog, is_correct=False)
            db.commit()
            redirect = _build_study_url(student_id, unit_id, grade)
            return templates.TemplateResponse(
                "student_flashcard_wrong.html",
                {
                    "request": request,
                    "card": card,
                    "stage": stage,
                    "student_id": student_id,
                    "next_url": redirect,
                },
            )

    # 次のカードへ
    redirect = _build_study_url(student_id, unit_id, grade)
    return RedirectResponse(url=redirect, status_code=303)


def _build_study_url(student_id: int, unit_id: str | None, grade: int | None) -> str:
    base = f"/students/{student_id}/flashcards/study"
    params = []
    if unit_id:
        params.append(f"unit_id={unit_id}")
    if grade:
        params.append(f"grade={grade}")
    return base + ("?" + "&".join(params) if params else "")


def count_due_flashcards(db: Session, student_id: int) -> int:
    """ホームバッジ用: 今日復習すべき単語数を返す。"""
    return _count_due_flashcards(db, student_id)
