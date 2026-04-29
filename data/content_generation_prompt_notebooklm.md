# NotebookLM 問題生成プロンプト

以下を NotebookLM などの生成AIに渡してください。出力は **JSON のみ** に限定します。

```text
中学数学の正負の数（加法）について、easyレベルの問題を5問作成してください。

以下の条件に厳密に従ってください。

- 出力は JSON のみ
- JSON以外の文章を一切出力しないこと
- JSONの構造（カンマ・配列・括弧）を絶対に壊さないこと
- 日本語で生成
- 問題はオリジナルで作成
- 重複禁止
- 市販教材や既存教材のコピー禁止

- 各問題に必ず以下を含める:
  full_unit_id / hint_1 / hint_2 / explanation_base / error_pattern_candidates / intervention_candidates

- difficulty は "easy" 固定
- full_unit_id は "positive_negative_numbers_addition"
- unit_id は "positive_negative_numbers"
- sub_unit は "addition"
- correct_answer は数値文字列

- error_pattern_candidates は正式辞書から選択すること
- intervention_candidates も正式辞書から選択すること
- 新しい名前を勝手に作らないこと

JSONフォーマット:

{
  "problems": [
    {
      "full_unit_id": "positive_negative_numbers_addition",
      "unit_id": "positive_negative_numbers",
      "sub_unit": "addition",
      "difficulty": "easy",
      "question_text": "",
      "correct_answer": "",
      "hint_1": "",
      "hint_2": "",
      "explanation_base": "",
      "error_pattern_candidates": [],
      "intervention_candidates": []
    }
  ]
}
```
中学数学の正負の数（加法）について、normalレベルの問題を5問作成してください。
中学数学の正負の数（加法）について、hardレベルの問題を5問作成してください。


中学1年数学の「正負の数（加法）」について、問題を作成してください。

対象単元:
- full_unit_id: positive_negative_numbers_addition
- parent_unit: positive_negative_numbers
- sub_unit: addition

条件:
- 出力は JSON のみ
- JSON以外の文章を一切出力しないこと
- 日本語で生成
- 問題はオリジナルのみ
- 重複禁止
- 市販教材や既存教材のコピー禁止
- 正式辞書にある error_pattern_candidates だけを使うこと
- 正式辞書にある intervention_candidates だけを使うこと
- 新しい名前を勝手に作らないこと

問題数:
- easy 5問
- normal 5問
- hard 5問

各問題に必ず含める項目:
- unit_id
- sub_unit
- difficulty
- question_text
- correct_answer
- hint_1
- hint_2
- explanation_base
- error_pattern_candidates
- intervention_candidates

固定値:
- unit_id = "positive_negative_numbers"
- sub_unit = "addition"

JSONフォーマット:
{
  "problems": [
    {
      "unit_id": "positive_negative_numbers",
      "sub_unit": "addition",
      "difficulty": "",
      "question_text": "",
      "correct_answer": "",
      "hint_1": "",
      "hint_2": "",
      "explanation_base": "",
      "error_pattern_candidates": [],
      "intervention_candidates": []
    }
  ]
}




中学1年数学の「正負の数（減法）」について、問題を作成してください。

対象単元:
- full_unit_id: positive_negative_numbers_subtraction
- parent_unit: positive_negative_numbers
- sub_unit: subtraction

条件:
- 出力は JSON のみ
- JSON以外の文章を一切出力しないこと
- 日本語で生成
- 問題はオリジナルのみ
- 重複禁止
- 市販教材や既存教材のコピー禁止
- 正式辞書にある error_pattern_candidates だけを使うこと
- 正式辞書にある intervention_candidates だけを使うこと
- 新しい名前を勝手に作らないこと

問題数:
- easy 5問
- normal 5問
- hard 5問

各問題に必ず含める項目:
- full_unit_id
- unit_id
- sub_unit
- difficulty
- question_text
- correct_answer
- hint_1
- hint_2
- explanation_base
- error_pattern_candidates
- intervention_candidates

固定値:
- full_unit_id = "positive_negative_numbers_subtraction"
- unit_id = "positive_negative_numbers"
- sub_unit = "subtraction"

JSONフォーマット:
{
  "problems": [
    {
      "full_unit_id": "positive_negative_numbers_subtraction",
      "unit_id": "positive_negative_numbers",
      "sub_unit": "subtraction",
      "difficulty": "",
      "question_text": "",
      "correct_answer": "",
      "hint_1": "",
      "hint_2": "",
      "explanation_base": "",
      "error_pattern_candidates": [],
      "intervention_candidates": []
    }
  ]
}

中学1年数学の「正負の数（乗法）」について、問題を作成してください。

対象単元:
- full_unit_id: positive_negative_numbers_multiplication
- parent_unit: positive_negative_numbers
- sub_unit: multiplication

条件:
- 出力は JSON のみ
- JSON以外の文章を一切出力しないこと
- 日本語で生成
- 問題はオリジナルのみ
- 重複禁止
- 市販教材や既存教材のコピー禁止
- 正式辞書にある error_pattern_candidates だけを使うこと
- 正式辞書にある intervention_candidates だけを使うこと
- 新しい名前を勝手に作らないこと

問題数:
- easy 5問
- normal 5問
- hard 5問

各問題に必ず含める項目:
- full_unit_id
- unit_id
- sub_unit
- difficulty
- question_text
- correct_answer
- hint_1
- hint_2
- explanation_base
- error_pattern_candidates
- intervention_candidates

固定値:
- full_unit_id = "positive_negative_numbers_multiplication"
- unit_id = "positive_negative_numbers"
- sub_unit = "multiplication"

JSONフォーマット:
{
  "problems": [
    {
      "full_unit_id": "positive_negative_numbers_multiplication",
      "unit_id": "positive_negative_numbers",
      "sub_unit": "multiplication",
      "difficulty": "",
      "question_text": "",
      "correct_answer": "",
      "hint_1": "",
      "hint_2": "",
      "explanation_base": "",
      "error_pattern_candidates": [],
      "intervention_candidates": []
    }
  ]
}



中学1年数学の「正負の数（除法）」について、問題を作成してください。

対象単元:
- full_unit_id: positive_negative_numbers_division
- parent_unit: positive_negative_numbers
- sub_unit: division

条件:
- 出力は JSON のみ
- JSON以外の文章を一切出力しないこと
- 日本語で生成
- 問題はオリジナルのみ
- 重複禁止
- 市販教材や既存教材のコピー禁止
- 正式辞書にある error_pattern_candidates だけを使うこと
- 正式辞書にある intervention_candidates だけを使うこと
- 新しい名前を勝手に作らないこと

問題数:
- easy 5問
- normal 5問
- hard 5問

各問題に必ず含める項目:
- full_unit_id
- unit_id
- sub_unit
- difficulty
- question_text
- correct_answer
- hint_1
- hint_2
- explanation_base
- error_pattern_candidates
- intervention_candidates

固定値:
- full_unit_id = "positive_negative_numbers_division"
- unit_id = "positive_negative_numbers"
- sub_unit = "division"

JSONフォーマット:
{
  "problems": [
    {
      "full_unit_id": "positive_negative_numbers_division",
      "unit_id": "positive_negative_numbers",
      "sub_unit": "division",
      "difficulty": "",
      "question_text": "",
      "correct_answer": "",
      "hint_1": "",
      "hint_2": "",
      "explanation_base": "",
      "error_pattern_candidates": [],
      "intervention_candidates": []
    }
  ]
}

中学1年数学の「文字式（基本）」について、問題を作成してください。

対象単元:
- full_unit_id: algebraic_expressions_basic
- parent_unit: algebraic_expressions
- sub_unit: basic

条件:
- 出力は JSON のみ
- JSON以外の文章を一切出力しないこと
- 日本語で生成
- 問題はオリジナルのみ
- 重複禁止
- 市販教材や既存教材のコピー禁止
- 正式辞書にある error_pattern_candidates だけを使うこと
- 正式辞書にある intervention_candidates だけを使うこと
- 新しい名前を勝手に作らないこと

問題数:
- easy 5問
- normal 5問
- hard 5問

各問題に必ず含める項目:
- unit_id
- sub_unit
- difficulty
- question_text
- correct_answer
- hint_1
- hint_2
- explanation_base
- error_pattern_candidates
- intervention_candidates

固定値:
- unit_id = "algebraic_expressions"
- sub_unit = "basic"

JSONフォーマット:
{
  "problems": [
    {
      "unit_id": "algebraic_expressions",
      "sub_unit": "basic",
      "difficulty": "",
      "question_text": "",
      "correct_answer": "",
      "hint_1": "",
      "hint_2": "",
      "explanation_base": "",
      "error_pattern_candidates": [],
      "intervention_candidates": []
    }
  ]
}

中学1年数学の「文字式（同類項）」について、問題を作成してください。

対象単元:
- full_unit_id: algebraic_expressions_terms
- parent_unit: algebraic_expressions
- sub_unit: terms

条件:
- 出力は JSON のみ
- JSON以外の文章を一切出力しないこと
- 日本語で生成
- 問題はオリジナルのみ
- 重複禁止
- 市販教材や既存教材のコピー禁止
- 正式辞書にある error_pattern_candidates だけを使うこと
- 正式辞書にある intervention_candidates だけを使うこと
- 新しい名前を勝手に作らないこと

問題数:
- easy 5問
- normal 5問
- hard 5問

各問題に必ず含める項目:
- unit_id
- sub_unit
- difficulty
- question_text
- correct_answer
- hint_1
- hint_2
- explanation_base
- error_pattern_candidates
- intervention_candidates

固定値:
- unit_id = "algebraic_expressions"
- sub_unit = "terms"

JSONフォーマット:
{
  "problems": [
    {
      "unit_id": "algebraic_expressions",
      "sub_unit": "terms",
      "difficulty": "",
      "question_text": "",
      "correct_answer": "",
      "hint_1": "",
      "hint_2": "",
      "explanation_base": "",
      "error_pattern_candidates": [],
      "intervention_candidates": []
    }
  ]
}

中学1年数学の「一次方程式（基本）」について、問題を作成してください。

対象単元:
- full_unit_id: linear_equations_basic
- parent_unit: linear_equations
- sub_unit: basic

条件:
- 出力は JSON のみ
- JSON以外の文章を一切出力しないこと
- 日本語で生成
- 問題はオリジナルのみ
- 重複禁止
- 市販教材や既存教材のコピー禁止
- 正式辞書にある error_pattern_candidates だけを使うこと
- 正式辞書にある intervention_candidates だけを使うこと
- 新しい名前を勝手に作らないこと

問題数:
- easy 5問
- normal 5問
- hard 5問

各問題に必ず含める項目:
- unit_id
- sub_unit
- difficulty
- question_text
- correct_answer
- hint_1
- hint_2
- explanation_base
- error_pattern_candidates
- intervention_candidates

固定値:
- unit_id = "linear_equations"
- sub_unit = "basic"

JSONフォーマット:
{
  "problems": [
    {
      "unit_id": "linear_equations",
      "sub_unit": "basic",
      "difficulty": "",
      "question_text": "",
      "correct_answer": "",
      "hint_1": "",
      "hint_2": "",
      "explanation_base": "",
      "error_pattern_candidates": [],
      "intervention_candidates": []
    }
  ]
}

中学1年数学の「一次方程式（移項）」について、問題を作成してください。

対象単元:
- full_unit_id: linear_equations_transposition
- parent_unit: linear_equations
- sub_unit: transposition

条件:
- 出力は JSON のみ
- JSON以外の文章を一切出力しないこと
- 日本語で生成
- 問題はオリジナルのみ
- 重複禁止
- 市販教材や既存教材のコピー禁止
- 正式辞書にある error_pattern_candidates だけを使うこと
- 正式辞書にある intervention_candidates だけを使うこと
- 新しい名前を勝手に作らないこと

問題数:
- easy 5問
- normal 5問
- hard 5問

各問題に必ず含める項目:
- unit_id
- sub_unit
- difficulty
- question_text
- correct_answer
- hint_1
- hint_2
- explanation_base
- error_pattern_candidates
- intervention_candidates

固定値:
- unit_id = "linear_equations"
- sub_unit = "transposition"

JSONフォーマット:
{
  "problems": [
    {
      "unit_id": "linear_equations",
      "sub_unit": "transposition",
      "difficulty": "",
      "question_text": "",
      "correct_answer": "",
      "hint_1": "",
      "hint_2": "",
      "explanation_base": "",
      "error_pattern_candidates": [],
      "intervention_candidates": []
    }
  ]
}


中学2数学の以下の単元について、通常学習用問題を作成してください。

対象単元:
full_unit_id: simultaneous_equations_basic
parent_unit: simultaneous_equations
sub_unit: basic

full_unit_id: simultaneous_equations_elimination
parent_unit: simultaneous_equations
sub_unit: elimination

full_unit_id: simultaneous_equations_substitution
parent_unit: simultaneous_equations
sub_unit: substitution

full_unit_id: simultaneous_equations_application
parent_unit: simultaneous_equations
sub_unit: application

full_unit_id: linear_function_basic
parent_unit: linear_function
sub_unit: basic

full_unit_id: linear_function_graph
parent_unit: linear_function
sub_unit: graph

full_unit_id: linear_function_interpretation
parent_unit: linear_function
sub_unit: interpretation

full_unit_id: geometry_parallel_lines
parent_unit: geometry
sub_unit: parallel_lines

full_unit_id: geometry_congruence
parent_unit: geometry
sub_unit: congruence

full_unit_id: probability_basic
parent_unit: probability
sub_unit: basic

中学数学の以下の単元について、通常学習用問題を作成してください。

対象単元:
- full_unit_id: {FULL_UNIT_ID}
- parent_unit: {PARENT_UNIT}
- sub_unit: {SUB_UNIT}
full_unit_id: simultaneous_equations_basic
parent_unit: simultaneous_equations
sub_unit: basic

条件:
- 出力は JSON のみ
- JSON以外の文章を一切出力しないこと
- 日本語で生成
- 問題はオリジナルのみ
- 重複禁止
- 市販教材や既存教材のコピー禁止
- 正式辞書にある error_pattern_candidates だけを使うこと
- 正式辞書にある intervention_candidates だけを使うこと
- 新しい名前を勝手に作らないこと

問題数:
- easy 5問
- normal 5問
- hard 5問

重要（図形問題対応）:
- 図形が必要な問題には必ず "diagram" を付けること
- diagram はテキストベースで表現する（ASCIIまたは説明図）
- 座標・辺・角度・ラベルを明確にすること
- diagram が不要な問題は null にすること

各問題に必ず含める項目:
- full_unit_id
- unit_id
- sub_unit
- problem_type
- difficulty
- question_text
- diagram
- correct_answer
- hint_1
- hint_2
- explanation_base
- error_pattern_candidates
- intervention_candidates

固定値:
- full_unit_id = "{FULL_UNIT_ID}"
- unit_id = "{PARENT_UNIT}"
- sub_unit = "{SUB_UNIT}"
- problem_type = "practice"

JSONフォーマット:
{
  "problems": [
    {
      "full_unit_id": "{FULL_UNIT_ID}",
      "unit_id": "{PARENT_UNIT}",
      "sub_unit": "{SUB_UNIT}",
      "problem_type": "practice",
      "difficulty": "",
      "question_text": "",
      "diagram": null,
      "correct_answer": "",
      "hint_1": "",
      "hint_2": "",
      "explanation_base": "",
      "error_pattern_candidates": [],
      "intervention_candidates": []
    }
  ]
}



て

中学数学の以下の単元について、テスト問題を作成してください。

対象単元:
- full_unit_id: {FULL_UNIT_ID}
- parent_unit: {PARENT_UNIT}
- sub_unit: {SUB_UNIT}
- test_scope: {TEST_SCOPE}

固定値:
- full_unit_id = "{FULL_UNIT_ID}"
- unit_id = "{PARENT_UNIT}"
- sub_unit = "{SUB_UNIT}"
- test_scope = "{TEST_SCOPE}"

条件:
- 出力は JSON のみ
- JSON以外の文章を一切出力しないこと
- 日本語で生成
- 問題はオリジナルのみ
- 重複禁止
- 市販教材や既存教材のコピー禁止
- 正式辞書にある error_pattern_candidates だけを使うこと
- 正式辞書にある intervention_candidates だけを使うこと
- 新しい名前を勝手に作らないこと

問題数:
- mini_test 5問
- unit_test 10問

重要（図形問題対応）:
- 図形が必要な問題には必ず "diagram_required" を true にすること
- 図形が不要な問題は "diagram_required" を false にすること
- "diagram" フィールドは必須とするが、現フェーズでは null を許可する
- diagram_required = true の問題は、図なしでも意味が伝わるように問題文で条件を明確に記述すること
- ASCII図や簡易図は使用しないこと

ルール:
- テスト問題は総合問題にする
- hint は不要
- 難易度は混在させる
- 同じパターンを並べない

各問題に必ず含める項目:
- full_unit_id
- unit_id
- sub_unit
- problem_type
- test_scope
- difficulty
- question_text
- diagram
- correct_answer
- explanation_base
- error_pattern_candidates
- intervention_candidates


JSONフォーマット:
{
  "problems": [
    {
      "full_unit_id": "{FULL_UNIT_ID}",
      "unit_id": "{PARENT_UNIT}",
      "sub_unit": "{SUB_UNIT}",
      "problem_type": "",
      "test_scope": "{TEST_SCOPE}",
      "difficulty": "",
      "question_text": "",
      "diagram": null,
      "correct_answer": "",
      "explanation_base": "",
      "error_pattern_candidates": [],
      "intervention_candidates": []
    }
  ]
}

中学数学の以下の単元について、通常学習用問題を作成してください。


中3-8
対象単元:
- full_unit_id: sample_survey_basic
- parent_unit: sample_survey
- sub_unit: basic

固定値:
- full_unit_id = "sample_survey_basic"
- unit_id = "sample_survey"
- sub_unit = "basic"
- problem_type = "practice"


---

# NotebookLM テスト問題生成テンプレート

以下は `mini_test` / `unit_test` を作るときのコピペ用テンプレートです。
`{...}` の部分だけ置き換えて NotebookLM に渡してください。

```text
中学数学の以下の単元について、テスト問題を JSON で作成してください。

対象単元:
- full_unit_id: {FULL_UNIT_ID}
- unit_id: {UNIT_ID}
- sub_unit: {SUB_UNIT}
- test_scope: {TEST_SCOPE}

固定値:
- full_unit_id = "{FULL_UNIT_ID}"
- unit_id = "{UNIT_ID}"
- sub_unit = "{SUB_UNIT}"
- problem_type = "{PROBLEM_TYPE}"
- test_scope = "{TEST_SCOPE}"

出力条件:
- 出力は JSON のみ
- JSON以外の文章を一切出力しないこと
- JSONの構造（カンマ・配列・括弧）を絶対に壊さないこと
- 日本語で生成
- 問題はオリジナルのみ
- 重複禁止
- 市販教材や既存教材のコピー禁止

使用ルール:
- error_pattern_candidates は正式辞書にある値のみ使うこと
- intervention_candidates も正式辞書にある値のみ使うこと
- 新しい名前を勝手に作らないこと
- hint_1, hint_2 は含めないこと
- difficulty は easy / normal / hard のいずれかを使うこと
- 図が必要な問題だけ "diagram" に説明文を入れること
- 図が不要な問題は "diagram": null にすること
- 現行仕様では "diagram_required" は出力しないこと

テスト設計ルール:
- mini_test は単元の基本確認にする
- unit_test は単元全体の到達確認にする
- 難易度は easy / normal / hard を混在させる
- 同じ解法パターンを連続させない
- 語句穴埋めだけで埋めず、計算・読解・活用を混ぜる
- practice 問題の焼き直しではなく、テスト向けに少し総合化する

正式辞書:
- 使用可能な error_pattern_candidates:
  - careless_error
  - comprehension_gap
  - prerequisite_gap
  - formula_setup_error
  - arithmetic_error
  - sign_error
  - operation_confusion
  - variable_handling_error
  - unknown_error
- 使用可能な intervention_candidates:
  - reinforce_same_pattern
  - retry_with_hint
  - fallback_prerequisite
  - slow_down_and_confirm
  - explain_differently
  - teacher_intervention_needed
  - advance_with_confidence
  - monitor_only

問題数:
- {QUESTION_COUNT}問

各問題に必ず含める項目:
- full_unit_id
- unit_id
- sub_unit
- problem_type
- test_scope
- difficulty
- question_text
- diagram
- correct_answer
- explanation_base
- error_pattern_candidates
- intervention_candidates

JSONフォーマット:
{
  "problems": [
    {
      "full_unit_id": "{FULL_UNIT_ID}",
      "unit_id": "{UNIT_ID}",
      "sub_unit": "{SUB_UNIT}",
      "problem_type": "{PROBLEM_TYPE}",
      "test_scope": "{TEST_SCOPE}",
      "difficulty": "",
      "question_text": "",
      "diagram": null,
      "correct_answer": "",
      "explanation_base": "",
      "error_pattern_candidates": [],
      "intervention_candidates": []
    }
  ]
}
```

## 使い方

- `mini_test` を作る場合
  - `{PROBLEM_TYPE}` = `mini_test`
  - `{TEST_SCOPE}` = `mini_test`
  - `{QUESTION_COUNT}` = `5`

- `unit_test` を作る場合
  - `{PROBLEM_TYPE}` = `unit_test`
  - `{TEST_SCOPE}` = `unit_test`
  - `{QUESTION_COUNT}` = `10`

## そのまま使える短縮版

### mini_test 用

```text
中学数学の以下の単元について、mini_test 用問題を5問作成してください。

中3-8
対象単元:
- full_unit_id: sample_survey_basic
- parent_unit: sample_survey
- sub_unit: basic

固定値:
- full_unit_id = "sample_survey_basic"
- unit_id = "sample_survey"
- sub_unit = "basic"

- problem_type = "mini_test"
- test_scope = "mini_test"

条件:
- 出力は JSON のみ
- JSON以外の文章を一切出力しないこと
- 日本語で生成
- オリジナル問題のみ
- 重複禁止
- 市販教材や既存教材のコピー禁止
- problem_type は "mini_test" 固定
- test_scope は "mini_test" 固定
- hint_1, hint_2 は出力しないこと
- difficulty は easy / normal / hard を混在させる
- "diagram_required" は出力しないこと
- error_pattern_candidates / intervention_candidates は正式辞書の値だけを使うこと
- 使用可能な error_pattern_candidates は以下のみ:
  careless_error / comprehension_gap / prerequisite_gap / formula_setup_error / arithmetic_error / sign_error / operation_confusion / variable_handling_error / unknown_error
- 使用可能な intervention_candidates は以下のみ:
  reinforce_same_pattern / retry_with_hint / fallback_prerequisite / slow_down_and_confirm / explain_differently / teacher_intervention_needed / advance_with_confidence / monitor_only

JSONフォーマット:
{
  "problems": [
    {
      "full_unit_id": "{FULL_UNIT_ID}",
      "unit_id": "{UNIT_ID}",
      "sub_unit": "{SUB_UNIT}",
      "problem_type": "mini_test",
      "test_scope": "mini_test",
      "difficulty": "",
      "question_text": "",
      "diagram": null,
      "correct_answer": "",
      "explanation_base": "",
      "error_pattern_candidates": [],
      "intervention_candidates": []
    }
  ]
}
```

### unit_test 用

```text
中学数学の以下の単元について、unit_test 用問題を10問作成してください。

中3-8
対象単元:
- full_unit_id: sample_survey_basic
- parent_unit: sample_survey
- sub_unit: basic

固定値:
- full_unit_id = "sample_survey_basic"
- unit_id = "sample_survey"
- sub_unit = "basic"

- problem_type = "unit_test"
- test_scope = "unit_test"

条件:
- 出力は JSON のみ
- JSON以外の文章を一切出力しないこと
- 日本語で生成
- オリジナル問題のみ
- 重複禁止
- 市販教材や既存教材のコピー禁止
- problem_type は "unit_test" 固定
- test_scope は "unit_test" 固定
- hint_1, hint_2 は出力しないこと
- difficulty は easy / normal / hard を混在させる
- "diagram_required" は出力しないこと
- error_pattern_candidates / intervention_candidates は正式辞書の値だけを使うこと
- 使用可能な error_pattern_candidates は以下のみ:
  careless_error / comprehension_gap / prerequisite_gap / formula_setup_error / arithmetic_error / sign_error / operation_confusion / variable_handling_error / unknown_error
- 使用可能な intervention_candidates は以下のみ:
  reinforce_same_pattern / retry_with_hint / fallback_prerequisite / slow_down_and_confirm / explain_differently / teacher_intervention_needed / advance_with_confidence / monitor_only
- 単元全体の理解確認になるように、基本・標準・やや応用を混ぜること

JSONフォーマット:
{
  "problems": [
    {
      "full_unit_id": "{FULL_UNIT_ID}",
      "unit_id": "{UNIT_ID}",
      "sub_unit": "{SUB_UNIT}",
      "problem_type": "unit_test",
      "test_scope": "unit_test",
      "difficulty": "",
      "question_text": "",
      "diagram": null,
      "correct_answer": "",
      "explanation_base": "",
      "error_pattern_candidates": [],
      "intervention_candidates": []
    }
  ]
}
```




条件:
- 出力は JSON のみ
- JSON以外の文章を一切出力しないこと
- 日本語で生成
- 問題はオリジナルのみ
- 重複禁止
- 市販教材や既存教材のコピー禁止
- 正式辞書にある error_pattern_candidates だけを使うこと
- 正式辞書にある intervention_candidates だけを使うこと
- 新しい名前を勝手に作らないこと

問題数:
- easy 5問
- normal 5問
- hard 5問

重要（図形問題対応）:
- 図形が必要な問題には必ず "diagram_required" を true にすること
- 図形が不要な問題は "diagram_required" を false にすること
- "diagram" フィールドは必須とするが、現フェーズでは null を許可する
- diagram_required = true の問題は、図なしでも意味が伝わるように問題文で条件を明確に記述すること
- ASCII図や簡易図は使用しないこと

各問題に必ず含める項目:
- full_unit_id
- unit_id
- sub_unit
- problem_type
- difficulty
- question_text
- diagram
- correct_answer
- hint_1
- hint_2
- explanation_base
- error_pattern_candidates
- intervention_candidates


下記の修正

中1-1
対象単元:
- full_unit_id: positive_negative_numbers_addition
- parent_unit: positive_negative_numbers
- sub_unit: addition

固定値:
- full_unit_id = "positive_negative_numbers_addition"
- unit_id = "positive_negative_numbers"
- sub_unit = "addition"
- problem_type = "practice"

中1-2
対象単元:
- full_unit_id: positive_negative_numbers_subtraction
- parent_unit: positive_negative_numbers
- sub_unit: subtraction

固定値:
- full_unit_id = "positive_negative_numbers_subtraction"
- unit_id = "positive_negative_numbers"
- sub_unit = "subtraction"
- problem_type = "practice"

中1-3
対象単元:
- full_unit_id: positive_negative_numbers_multiplication
- parent_unit: positive_negative_numbers
- sub_unit: multiplication

固定値:
- full_unit_id = "positive_negative_numbers_multiplication"
- unit_id = "positive_negative_numbers"
- sub_unit = "multiplication"
- problem_type = "practice"

中1-4
対象単元:
- full_unit_id: positive_negative_numbers_division
- parent_unit: positive_negative_numbers
- sub_unit: division

固定値:
- full_unit_id = "positive_negative_numbers_division"
- unit_id = "positive_negative_numbers"
- sub_unit = "division"
- problem_type = "practice"

中1-5
対象単元:
- full_unit_id: algebraic_expressions_basic
- parent_unit: algebraic_expressions
- sub_unit: basic

固定値:
- full_unit_id = "algebraic_expressions_basic"
- unit_id = "algebraic_expressions"
- sub_unit = "basic"
- problem_type = "practice"

中1-6
対象単元:
- full_unit_id: algebraic_expressions_terms
- parent_unit: algebraic_expressions
- sub_unit: terms

固定値:
- full_unit_id = "algebraic_expressions_terms"
- unit_id = "algebraic_expressions"
- sub_unit = "terms"
- problem_type = "practice"

中1-7
対象単元:
- full_unit_id: algebraic_expressions_substitution
- parent_unit: algebraic_expressions
- sub_unit: substitution

固定値:
- full_unit_id = "algebraic_expressions_substitution"
- unit_id = "algebraic_expressions"
- sub_unit = "substitution"
- problem_type = "practice"

中1-8
対象単元:
- full_unit_id: linear_equations_basic
- parent_unit: linear_equations
- sub_unit: basic

固定値:
- full_unit_id = "linear_equations_basic"
- unit_id = "linear_equations"
- sub_unit = "basic"
- problem_type = "practice"

中1-9
対象単元:
- full_unit_id: linear_equations_transposition
- parent_unit: linear_equations
- sub_unit: transposition

固定値:
- full_unit_id = "linear_equations_transposition"
- unit_id = "linear_equations"
- sub_unit = "transposition"
- problem_type = "practice"

中1-10
対象単元:
- full_unit_id: linear_equations_word_problem
- parent_unit: linear_equations
- sub_unit: word_problem

固定値:
- full_unit_id = "linear_equations_word_problem"
- unit_id = "linear_equations"
- sub_unit = "word_problem"
- problem_type = "practice"

中2-1
対象単元:
- full_unit_id: simultaneous_equations_basic
- parent_unit: simultaneous_equations
- sub_unit: basic

固定値:
- full_unit_id = "simultaneous_equations_basic"
- unit_id = "simultaneous_equations"
- sub_unit = "basic"
- problem_type = "practice"

中2-2
対象単元:
- full_unit_id: simultaneous_equations_application
- parent_unit: simultaneous_equations
- sub_unit: application

固定値:
- full_unit_id = "simultaneous_equations_application"
- unit_id = "simultaneous_equations"
- sub_unit = "application"
- problem_type = "practice"

中2-3
対象単元:
- full_unit_id: linear_function_basic
- parent_unit: linear_function
- sub_unit: basic

固定値:
- full_unit_id = "linear_function_basic"
- unit_id = "linear_function"
- sub_unit = "basic"
- problem_type = "practice"

中2-4
対象単元:
- full_unit_id: linear_function_graph
- parent_unit: linear_function
- sub_unit: graph

固定値:
- full_unit_id = "linear_function_graph"
- unit_id = "linear_function"
- sub_unit = "graph"
- problem_type = "practice"

中2-5
対象単元:
- full_unit_id: geometry_parallel_congruence
- parent_unit: geometry_parallel_congruence
- sub_unit: basic

固定値:
- full_unit_id = "geometry_parallel_congruence"
- unit_id = "geometry_parallel_congruence"
- sub_unit = "basic"
- problem_type = "practice"

中2-6
対象単元:
- full_unit_id: probability_basic
- parent_unit: probability
- sub_unit: basic

固定値:
- full_unit_id = "probability_basic"
- unit_id = "probability"
- sub_unit = "basic"
- problem_type = "practice"

中3-1
対象単元:
- full_unit_id: quadratic_expressions_expansion
- parent_unit: quadratic_expressions
- sub_unit: expansion

固定値:
- full_unit_id = "quadratic_expressions_expansion"
- unit_id = "quadratic_expressions"
- sub_unit = "expansion"
- problem_type = "practice"

中3-2
対象単元:
- full_unit_id: factorization_basic
- parent_unit: factorization
- sub_unit: basic

固定値:
- full_unit_id = "factorization_basic"
- unit_id = "factorization"
- sub_unit = "basic"
- problem_type = "practice"

中3-3
対象単元:
- full_unit_id: quadratic_equations_basic
- parent_unit: quadratic_equations
- sub_unit: basic

固定値:
- full_unit_id = "quadratic_equations_basic"
- unit_id = "quadratic_equations"
- sub_unit = "basic"
- problem_type = "practice"

中3-4
対象単元:
- full_unit_id: quadratic_equations_application
- parent_unit: quadratic_equations
- sub_unit: application

固定値:
- full_unit_id = "quadratic_equations_application"
- unit_id = "quadratic_equations"
- sub_unit = "application"
- problem_type = "practice"

中3-5
対象単元:
- full_unit_id: functions_y_equals_ax2
- parent_unit: functions_y_equals_ax2
- sub_unit: basic

固定値:
- full_unit_id = "functions_y_equals_ax2"
- unit_id = "functions_y_equals_ax2"
- sub_unit = "basic"
- problem_type = "practice"

中3-6
対象単元:
- full_unit_id: geometry_similarity
- parent_unit: geometry_similarity
- sub_unit: basic

固定値:
- full_unit_id = "geometry_similarity"
- unit_id = "geometry_similarity"
- sub_unit = "basic"
- problem_type = "practice"

中3-7
対象単元:
- full_unit_id: circles_angles
- parent_unit: circles_angles
- sub_unit: basic

固定値:
- full_unit_id = "circles_angles"
- unit_id = "circles_angles"
- sub_unit = "basic"
- problem_type = "practice"

中3-8
対象単元:
- full_unit_id: sample_survey_basic
- parent_unit: sample_survey
- sub_unit: basic

固定値:
- full_unit_id = "sample_survey_basic"
- unit_id = "sample_survey"
- sub_unit = "basic"
- problem_type = "practice"
