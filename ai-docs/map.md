# AI-Juku Architecture Map

## Phase 2: ゲームUI再設計 (2026-04-26)

### Phase 2-A: ホーム画面のゲームUI再設計
**目的:** 問題画面にすごろくボードのミニプレビュー、進捗バー、ゴールドカウンターを追加

| ファイル | 変更内容 |
|---|---|
| `ai_school/app/routers/student.py:12` | `UnitMastery` をインポートに追加 |
| `ai_school/app/routers/student.py:277-288` | `mini_board_cells`（直近14件）と `mastery_pct`（習熟度%）をクエリしてコンテキストに追加 |
| `ai_school/app/routers/student.py:310-311` | `mini_board_cells`, `mastery_pct` をテンプレートコンテキストに渡す |
| `ai_school/app/templates/student_home.html:56` | トップバーにゴールドチップ `🪙 XG` を追加（常時表示） |
| `ai_school/app/templates/student_home.html:106-132` | ミニボードブロック追加（単元名、習熟度プログレスバー、直近14マス、ヒント文） |
| `ai_school/app/static/style.css:5714-5801` | `.home-mini-board` 系スタイルと `.state-chip--gold` を追加 |

### Phase 2-B: レベルアップ・バッジ獲得の全画面セレブレーション
**目的:** レベルアップ時とバッジ獲得時に全画面エフェクトで演出を強化

| ファイル | 変更内容 |
|---|---|
| `ai_school/app/routers/student.py:719-732` | `mastery_score_before` をマスタリー更新前に記録（ユニットクリア検出用） |
| `ai_school/app/routers/student.py:877-881` | `xp_before`, `level_before` でレベルアップ検出 → `level_up: bool` |
| `ai_school/app/routers/student.py:918-925` | `unit_clear` 検出（mastery_score が 0.55 閾値を初めて越えた場合） |
| `ai_school/app/routers/student.py:984-987` | `level_up`, `new_level`, `xp_earned`, `unit_clear` をコンテキストに追加 |
| `ai_school/app/templates/student_result.html:4-20` | バッジ全画面 overlay（`.badge-overlay`）追加、2秒後にフェードアウト |
| `ai_school/app/templates/student_result.html:28-33` | 正解 overlay に `unit_clear` バナー、`level_up` バナーを追加 |
| `ai_school/app/templates/student_result.html:39` | `totalMs` をレベルアップ時 2500ms、通常 1500ms に変更 |
| `ai_school/app/templates/student_result.html:528-533` | レベルアップ時の追加 confetti バースト（金色 200 粒） |
| `ai_school/app/templates/student_result.html:498-512` | バッジ overlay 自動消去 JS（2秒後） |
| `ai_school/app/templates/student_result.html:53-62` | 旧 `.badge-earned-toast` を削除（全画面 overlay に置換） |
| `ai_school/app/static/style.css:5795-5870` | `.badge-overlay` 系スタイル、`.correct-overlay__levelup`, `.correct-overlay__unit-clear` を追加 |

### Phase 2-C: ショップを日常動線に入れる
**目的:** ショップボタンをヘッダーに常時表示し、100G 到達時に通知バナーを表示

| ファイル | 変更内容 |
|---|---|
| `ai_school/app/templates/student_home.html:59` | ヘッダーにショップボタン `🏪 ショップ（XG）` を追加（progress ページへリンク） |
| `ai_school/app/templates/student_home.html:106-118` | 100G 到達時のショップ誘導バナー（`.shop-nudge-banner`）を追加 |
| `ai_school/app/static/style.css:5880-5938` | `.progress-chip-btn--shop`, `.shop-nudge-banner` 系スタイルを追加 |

## データフロー図

### 回答送信時 (submit_answer)
```
student.py submit_answer()
  → mastery_score_before 記録
  → apply_practice_attempt_to_unit_mastery()
  → db.flush()
  → xp_before, level_before 記録
  → state.total_xp 更新
  → level_up 検出
  → db.commit()
  → unit_clear 検出 (mastery_score_before < 0.55 && after >= 0.55)
  → TemplateResponse(student_result.html)
    → context: level_up, new_level, xp_earned, unit_clear, new_badges
```

### ホーム表示時 (student_home)
```
student.py student_home()
  → mini_board_cells クエリ (StudentBoardCell 直近14件)
  → UnitMastery クエリ
  → mastery_pct 計算 (mastery_score / 0.55 * 100)
  → TemplateResponse(student_home.html)
    → context: mini_board_cells, mastery_pct, state.gold
```

## 依存関係

### Phase 2-A
- `StudentBoardCell` モデル（すごろくボードセル）
- `UnitMastery` モデル（習熟度）
- `student_home` ルーター

### Phase 2-B
- `StudentBoardCell` モデル（ボードセル追加）
- `UnitMastery` モデル（習熟度閾値検出）
- `submit_answer` ルーター
- Canvas Confetti CDN（外部ライブラリ）

### Phase 2-C
- `state.gold`（ゴールド残高）
- `student_progress.html`（ショップページ）

## 技術的負債

- `COMPOSER2_INSTRUCTIONS.md` に null bytes が含まれており読み込み不可

## Phase 3: AI Meinコーチ統合 (2026-04-26)

### Phase 3-A: Meinの「ひとこと」AI生成
**目的:** 問題表示前に Mein が学習状況に応じたセリフを吹き出しで表示

| ファイル | 変更内容 |
|---|---|
| `ai_school/app/routers/student.py:21` | `generate_text` を ai_service からインポート（soul.md準拠: 全インポートをファイル先頭に集約） |
| `ai_school/app/routers/student.py:34-41` | `routing_service` から定数・関数をインポート（soul.md準拠: ローカルインポート削除） |
| `ai_school/app/routers/student.py:80-104` | `_generate_mein_message()` 関数追加（キャッシュ付きAI生成、インポート後に配置） |
| `ai_school/app/routers/student.py:317-323` | `student_home` で `mein_message` を生成 |
| `ai_school/app/routers/student.py:347` | `mein_message` をテンプレートコンテキストに追加 |
| `ai_school/app/templates/student_home.html:164-172` | Mein吹き出しブロック追加（英語以外で表示） |
| `ai_school/app/static/style.css:5880-5921` | `.mein-speech-section` / `.mein-speech-char` / `.mein-speech-bubble` スタイル追加 |

**AI生成ロジック:**
- キャッシュキー: `streak_{streak}_mastery_{mastery_pct:.0f}`（同じ文脈なら同じメッセージ）
- System Prompt: Meinキャラ設定（20文字以内、絵文字1つ）
- User Prompt: 連続学習日数、単元習熟度、単元名
- Max Tokens: 60

### Phase 3-B: 適応学習の可視化
**目的:** 推奨ルートと弱点単元を視覚的に表示して学習の方向性を示す

| ファイル | 変更内容 |
|---|---|
| `ai_school/app/routers/student.py:306` | `student_home` で `get_recommended_route()` を呼び出し |
| `ai_school/app/routers/student.py:330-333` | `recommended_route`, `ADVANCE_ROUTE`, `REINFORCE_ROUTE`, `FALLBACK_ROUTE` をコンテキストに追加 |
| `ai_school/app/templates/student_home.html:106-117` | 推奨ルートバッジ追加（ADVANCE: 🚀次の単元に進もう、FALLBACK: 📚基礎を復習しよう） |
| `ai_school/app/templates/student_home.html:183-185` | Mein吹き出しに弱点単元提案追加（`state.weak_unit` かつ `FALLBACK_ROUTE` のとき） |
| `ai_school/app/static/style.css:5880-5906` | `.route-badge` / `.route-badge--advance` / `.route-badge--fallback` スタイル追加 |

**ルート判定ロジック（routing_service.py `get_recommended_route`）:**
- `ADVANCE_ROUTE`: 習熟度 >= 55%、正解数 >= 3、直近正解 >= 3 → 次の単元へ
- `FALLBACK_ROUTE`: 習熟度 < 40%、直近不正解 >= 3 → 前提単元へ
- `REINFORCE_ROUTE`: 上記以外 → 現在の単元を強化

## Phase 4: 問題画面React Island (2026-04-26)

### Phase 4-1: OCR API クライアント追加
**目的:** 既存の `/students/{id}/ocr` エンドポイントを React から利用可能にする

| ファイル | 変更内容 |
|---|---|
| `frontend/lib/api.ts:154-172` | `OCRRequest`, `OCRResponse` インターフェース追加 |
| `frontend/lib/api.ts:166-172` | `recognizeHandwriting()` 関数追加 |

### Phase 4-3: 手書きキャンバス（Canvas API）
**目的:** Canvas API で手書き入力を可能にし、OCR でテキスト認識

| ファイル | 変更内容 |
|---|---|
| `frontend/components/HandwritingCanvas.tsx` | **新規作成** - Canvas 描画、タッチ対応、OCR 呼び出し |

### Phase 4-4: 数学構造化キーパッド
**目的:** 数式入力キーパッド（数字、演算子、括弧、分数、ルート）

| ファイル | 変更内容 |
|---|---|
| `frontend/components/MathKeypad.tsx` | **新規作成** - グリッドキーパッド、バックスペース、クリア |

### Phase 4-5: sort型問題（タイルDnD）
**目的:** タイルのドラッグ＆ドロップで並べ替え問題を実装

| ファイル | 変更内容 |
|---|---|
| `frontend/components/SortTiles.tsx` | **新規作成** - Framer Motion アニメーション、DnD ロジック |

### Phase 4-7-1: page.tsx 統合
**目的:** 新コンポーネントを学生ページに統合

| ファイル | 変更内容 |
|---|---|
| `frontend/app/students/[id]/page.tsx:11-13` | `HandwritingCanvas`, `MathKeypad`, `SortTiles` インポート |
| `frontend/app/students/[id]/page.tsx:134-157` | 回答フォームに新コンポーネント統合（sort → SortTiles、numeric → MathKeypad、text → HandwritingCanvas） |

**コンポーネント対応表:**
| `answer_type` | コンポーネント |
|---|---|
| `choice` | `ChoiceGrid`（既存） |
| `sort` | `SortTiles`（新規） |
| `numeric` | `MathKeypad`（新規） |
| `text` | `input` + `HandwritingCanvas`（新規） |

