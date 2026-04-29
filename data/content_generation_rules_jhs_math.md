# 中学数学教材生成ルール

## 対象
- Unit Map に存在する `full_unit_id` のみ生成する
- 地図にない単元は先に生成しない

## 通常問題
- `problem_type`: `practice`
- 1 `full_unit_id` ごとに `easy 5 / normal 5 / hard 5`
- 必須項目:
  - `unit_id`
  - `sub_unit`
  - `full_unit_id`
  - `problem_type`
  - `difficulty`
  - `question_text`
  - `correct_answer`
  - `hint_1`
  - `hint_2`
  - `explanation_base`
  - `error_pattern_candidates`
  - `intervention_candidates`

## テスト問題
- `problem_type`: `mini_test` または `unit_test`
- `mini_test`: 5問
- `unit_test`: 10問
- 必須項目:
  - `unit_id`
  - `sub_unit`
  - `full_unit_id`
  - `problem_type`
  - `test_scope`
  - `difficulty`
  - `question_text`
  - `correct_answer`
  - `explanation_base`
  - `error_pattern_candidates`
  - `intervention_candidates`
- `hint_1` と `hint_2` は空でよい

## 原則
- 通常問題は診断・介入向け
- テスト問題は到達確認向け
- 市販教材のコピーは禁止
- 出力は JSON 正本で統一する

## ヒント品質ルール
- `hint_1`: 考え方の入口だけを示す1文。**`correct_answer` の値を含めてはならない。**「〇〇します」のような曖昧な操作説明は禁止。代わりに「両辺を○○で割る」「移項する」など数学的用語で正確に記述する。
- `hint_2`: 解法の途中経過を1ステップ示す。**`correct_answer` の値をそのまま含めてはならない。** 途中式の形で示し、最終答えには至らないこと。
- `hint_1` も `hint_2` も **答えそのものを教えない**。ヒント2で答えが分かるものは不合格。
- 「片方を消す」「移動させる」など口語的・不正確な表現は使わない。
