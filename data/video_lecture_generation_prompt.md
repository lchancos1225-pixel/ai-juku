# 動画講義生成プロンプト

## System Prompt（コピペ）

```
あなたは日本の中学生向け数学・英語動画講義のコンテンツ設計エキスパートです。
スライド同期型動画プレイヤー用のコンテンツをJSONとMarkdownで出力します。

【ルール】
- 有効なJSONを先に出力、その後Markdownナレーション原稿
- 1単元=5-7枚スライド、3-5分想定
- 各スライドにdifficulty_tag（easy/normal/hard/null）を付与
- 例題スライドは「問題文→解法ステップ→答え」の順で解説
- visual_descriptionは画像生成AI向けの具体的な指示
- ナレーションは話し言葉で平易な日本語
```

## User Promptテンプレート（コピペ）

```
【単元情報】
- 単元名: {UNIT_NAME}
- full_unit_id: {FULL_UNIT_ID}
- 対象学年: {GRADE}年生
- 学習目標: {LEARNING_OBJECTIVE}
- visual_type: {VISUAL_TYPE}

【難易度別問題】
[Easy] {EASY_Q} / 答え: {EASY_A} / 解説: {EASY_EXP}
[Normal] {NORMAL_Q} / 答え: {NORMAL_A} / 解説: {NORMAL_EXP}
[Hard] {HARD_Q} / 答え: {HARD_A} / 解説: {HARD_EXP}

【出力依頼】
1. JSON: 以下スキーマに従うスライド構造化データ
2. Markdown: ナレーション原稿（話し言葉、タイムスタンプ付き）
```

## JSONスキーマ（コピペ）

```json
{
  "unit_id": "string",
  "title": "単元名",
  "target_grade": 7,
  "total_duration_sec": 240,
  "learning_objective": "1文要約",
  "slides": [
    {
      "slide_number": 1,
      "title": "導入",
      "script": "ナレーション全文",
      "visual_description": "画像生成用プロンプト（背景色・配置・図形等を具体的に）",
      "visual_type": "number_line|fraction_bar|area_grid|pen_calc|text_only|chart|equation_flow",
      "duration_sec": 30,
      "difficulty_tag": null,
      "key_point": "核心メッセージ1文"
    },
    {
      "slide_number": 2,
      "title": "基礎概念",
      "script": "...",
      "visual_description": "...",
      "duration_sec": 45,
      "difficulty_tag": "easy",
      "key_point": "..."
    },
    {
      "slide_number": 3,
      "title": "例題1：基本",
      "script": "...",
      "visual_description": "...",
      "duration_sec": 60,
      "difficulty_tag": "easy",
      "example_problem": {
        "question": "問題文",
        "solution_steps": ["ステップ1", "ステップ2"],
        "answer": "答え",
        "common_mistake": "よくある間違いと指摘"
      }
    },
    {
      "slide_number": 4,
      "title": "例題2：標準",
      "difficulty_tag": "normal",
      "example_problem": { "question": "...", "solution_steps": ["..."], "answer": "...", "common_mistake": "..." }
    },
    {
      "slide_number": 5,
      "title": "例題3：発展",
      "difficulty_tag": "hard",
      "example_problem": { "question": "...", "solution_steps": ["..."], "answer": "...", "common_mistake": "..." }
    },
    {
      "slide_number": 6,
      "title": "まとめ",
      "script": "...",
      "duration_sec": 30,
      "difficulty_tag": null,
      "key_point": "...",
      "next_step_hint": "次の学習への導線"
    }
  ]
}
```

## Markdownナレーション原稿テンプレート（出力例）

```markdown
# 【{UNIT_NAME}】ナレーション原稿

## Slide 1: 導入（0:00-{DURATION}）
[画面: タイトルカード / 背景: {BG_COLOR} / 中央に単元名]
「こんにちは。今日は{UNIT_NAME}について学びます。{LEARNING_OBJECTIVE}ことができます。始めましょう。」

## Slide 2: 基礎概念（{START}-{END}）
[画面: {VISUAL_TYPE} / {VISUAL_DESC}]
「まず基本の考え方です。{CONCEPT}ポイントは{KEY_POINT}です。」

## Slide 3: 例題1 基本（{START}-{END}）★☆☆
[画面: 問題文 → ステップ解説]
「基本例題です。【問題】{Q} 解き方は{METHOD}。{STEP1} {STEP2} 答えは{A}です。」

## Slide 4: 例題2 標準（{START}-{END}）★★☆
「標準問題です。【問題】{Q} {METHOD}。{STEPS} 答えは{A}です。よくある間違いは{MISTAKE}です。」

## Slide 5: 例題3 発展（{START}-{END}）★★★
「発展問題です。【問題】{Q} {STEPS} 答えは{A}です。」

## Slide 6: まとめ（{START}-{END}）
「まとめです。{SUMMARY} 演習問題で実力を試しましょう。」
```

## 具体例：正負の数の加法

### 埋め込み変数

- UNIT_NAME: 正負の数の加法
- FULL_UNIT_ID: positive_negative_numbers_addition
- GRADE: 7
- LEARNING_OBJECTIVE: 正負の数を足し算できるようになる
- VISUAL_TYPE: number_line
- EASY_Q: (+3)+(+4)を計算しなさい / EASY_A: 7 / EASY_EXP: 同符号は絶対値を足して符号を継ぐ
- NORMAL_Q: (-5)+(+8)を計算しなさい / NORMAL_A: 3 / NORMAL_EXP: 異符号は大きい方から小さい方を引いて大きい方の符号
- HARD_Q: (-12)+(+7)+(-3)を計算しなさい / HARD_A: -8 / HARD_EXP: 順に計算、または正と負を分けてまとめる

### 生成コマンド例

上記のSystem Prompt + User Prompt（変数埋め込み済み）をClaude/GPT-4に送信すると、JSONとMarkdownが出力される。
