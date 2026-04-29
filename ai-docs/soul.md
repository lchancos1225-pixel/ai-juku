# この世界の摂理

AI塾 QRelDo プロジェクトのコーディングスタイル、命名規則、設計美学を記述する。

---

## プロジェクト構造

```
ai-juku/
├── ai_school/              # Python FastAPI バックエンド
│   └── app/
│       ├── routers/        # APIエンドポイント
│       ├── services/       # ビジネスロジック層
│       ├── models.py       # SQLAlchemy ORM モデル
│       ├── schemas.py      # Pydantic スキーマ
│       ├── database.py     # データベース接続
│       └── templates/      # Jinja2 テンプレート
├── frontend/               # Next.js React フロントエンド
│   ├── app/                # Next.js App Router ページ
│   ├── components/         # React コンポーネント
│   └── lib/                # ユーティリティ（APIクライアント等）
└── data/                   # シードデータ
```

---

## Python (FastAPI) コーディング規約

### 命名規則

- **クラス**: `PascalCase`
  - `Classroom`, `Student`, `Teacher`, `UnifiedLoginRequest`
- **関数/メソッド**: `snake_case`
  - `login_unified`, `get_classroom_students`, `_require_student`
- **プライベート関数**: `_prefix`
  - `_redirect_for_authenticated`, `_render_public_template`
- **定数**: `UPPER_SNAKE_CASE`
  - `PBKDF2_ITERATIONS`, `SESSION_SECRET`
- **変数**: `snake_case`
  - `code_norm`, `ident`, `classroom`
- **ルーター**: `router = APIRouter(tags=["tagname"])`

### ファイル構成

- **routers/**: APIエンドポイント定義
  - 各ルーターは `APIRouter(tags=["..."])` でタグ付け
  - 依存注入は `Depends(get_db)` 等で行う
- **services/**: ビジネスロジック
  - データアクセスはサービス層に集約
  - 複雑な処理はサービス関数に抽出
- **models.py**: SQLAlchemy ORM モデル
  - `Mapped[型]` アノテーションを使用
  - リレーションは `relationship()` で定義
- **schemas.py**: Pydantic リクエスト/レスポンスモデル
  - `BaseModel` を継承
  - `model_validator` でカスタムバリデーション
- **database.py**: データベース接続設定
  - `get_db()` ジェネレータでセッション管理

### コーディングスタイル

- 型ヒントを必ず使用: `Mapped[int]`, `str | None`
- ロガー: `logger = logging.getLogger(__name__)`
- セキュリティ: `secrets` モジュールを優先（`random` は避ける）
- パスワードハッシュ: PBKDF2-SHA256
- セッション管理: カスタムクッキー (`ai_school_session`)
- エラーハンドリング: `HTTPException` で一貫性
- セクション区切り: `# ─── section name ───` コメント
- ドキュメント: 関数には docstring を使用

### インポート順序

1. 標準ライブラリ
2. サードパーティライブラリ
3. ローカルモジュール（相対インポート `from ..`）

---

## TypeScript/React (Next.js) コーディング規約

### 命名規則

- **コンポーネント**: `PascalCase`
  - `LoginPage`, `HintButton`, `QuestBar`
- **ファイル名**: `PascalCase.tsx`
  - `HintButton.tsx`, `QuestBar.tsx`
- **関数/変数**: `camelCase`
  - `handleClassroomSubmit`, `setStep`, `studentId`
- **インターフェース**: `PascalCase`
  - `StudentInfo`, `HomeData`, `Props`
- **型エイリアス**: `PascalCase`
  - `Step`, `SubmitResult`

### ファイル構成

- **app/**: Next.js App Router ページ
  - `[id]/page.tsx` 動的ルート
  - `layout.tsx` レイアウト
  - `page.tsx` トップページ
- **components/**: 再利用可能なコンポーネント
  - 各コンポーネントは独立したファイル
  - 小さなコンポーネントも分離
- **lib/**: ユーティリティ
  - `api.ts` APIクライアント
  - 共通関数を集約

### コーディングスタイル

- `"use client"` ディレクティブをクライアントコンポーネントに明記
- TypeScript strict mode
- Props は interface で定義
- 状態管理: React hooks (`useState`, `useEffect`, `useRef`)
- アニメーション: Framer Motion (`motion`, `AnimatePresence`)
- スタイリング: TailwindCSS
- API呼び出し: `lib/api.ts` の関数を使用
- エラーハンドリング: `try-catch` でユーザーに表示

### コンポーネント設計

- 単一責任: 各コンポーネントは1つの役割
- Props は明示的に型定義
- 条件レンダリング: 三項演算子より早期return
- ローディング状態: `loading` フラグで制御

---

## 設計パターン

### バックエンド

- **アーキテクチャ**: レイヤードアーキテクチャ
  - Router → Service → Model
- **認証**: セッションベース
  - カスタムクッキーでセッション管理
- **依存注入**: FastAPI `Depends()`
- **API設計**: RESTful
  - `/api/v1/` プレフィックス
  - 適切なHTTPステータスコード

### フロントエンド

- **アーキテクチャ**: コンポーネントベース
  - ページレベル + UIコンポーネント
- **状態管理**: React hooks
  - ローカル状態は `useState`
  - グローバル状態は必要に応じて Context
- **データフロー**: 単方向データフロー
  - Props down, Events up

---

## UI/UX 方針

- **言語**: 日本語優先（ユーザー向けメッセージ）
- **ゲーム化要素**: XP, Gold, Streak, Quest
- **アニメーション**: Framer Motion for smooth transitions
- **レスポンシブ**: TailwindCSS for mobile-first
- **アクセシビリティ**: ARIAラベル、適切なセマンティクス

---

## テスト方針

- **テストファイル**: `tests/` ディレクトリ
- **命名**: `test_*.py`
- **フレームワーク**: pytest

---

## コメント規約

- **関数**: docstring（三重引用符）
  ```python
  def get_classroom_students(code: str, db: Session = Depends(get_db)):
      """教室コードから生徒一覧を返す（ログイン画面の名前選択用）。"""
  ```
- **セクション**: `# ─── section ───`
  ```python
  # ─── auth endpoints ───────────────────────────────────────────────────────────
  ```
- **TODO**: 日本語で記述

---

## 環境設定

- **Python**: 3.12
- **仮想環境**: `.venv/`
- **起動コマンド**: `.venv/bin/uvicorn ai_school.app.main:app --host 127.0.0.1 --port 8000`
- **Next.js**: 16.2.4
- **React**: 19
- **TailwindCSS**: v4

---

## 禁止事項

- `random` モジュールの使用（`secrets` を使用）
- ハードコードされた認証情報（環境変数を使用）
- 未使用のインポート
- コメントアウトされたコードの残置（必要なら削除）
- マジックナンバー（定数として定義）

---

## 推奨事項

- 型ヒントを常に使用
- 小さな関数/コンポーネントを保つ
- 早めのリターン（guard clauses）
- 意味のある変数名
- 一貫した命名規則
- 適切なエラーハンドリング
- ログ出力 for debugging
