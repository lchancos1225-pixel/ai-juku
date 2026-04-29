import os
from typing import Any

import httpx
from dotenv import load_dotenv

# DeepSeek API (コスト最適・デフォルト推奨)
# OpenAI互換エンドポイントなのでそのまま流用可能
DEFAULT_AI_BASE_URL = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_AI_MODEL = "deepseek-chat"

# フォールバック設定 (GitHub Models / OpenAI)
FALLBACK_AI_BASE_URL = "https://models.inference.ai.azure.com/chat/completions"
FALLBACK_AI_MODEL = "gpt-4o-mini"

# Claude Haiku 4.5モデルIDをデフォルトに変更
DEFAULT_CLAUDE_MODEL = "claude-haiku-4-5"

load_dotenv()

def ai_conversation_enabled() -> bool:
    return os.getenv("AI_CONVERSATION_ENABLED", "false").lower() == "true"


def get_ai_model() -> str:
    """DeepSeek優先、環境変数で上書き可能"""
    return os.getenv("AI_MODEL", DEFAULT_AI_MODEL)


# 後方互換エイリアス
get_openai_model = get_ai_model


def get_ai_api_key() -> str | None:
    """DEEPSEEK_API_KEY を最優先、次に GITHUB_TOKEN、最後に OPENAI_API_KEY を使う。"""
    return (
        os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("GITHUB_TOKEN")
        or os.getenv("OPENAI_API_KEY")
        or None
    )


# 後方互換エイリアス
get_openai_api_key = get_ai_api_key


def _get_base_url() -> str:
    """DeepSeek優先、OPENAI_BASE_URL で上書き可能（後方互換）"""
    return os.getenv("OPENAI_BASE_URL", DEFAULT_AI_BASE_URL)


def _extract_output_text(payload: dict[str, Any]) -> str | None:
    """Chat Completions レスポンス形式からテキストを取り出す。"""
    # Chat Completions: choices[0].message.content
    choices = payload.get("choices")
    if choices and isinstance(choices, list):
        message = choices[0].get("message", {})
        text = message.get("content")
        if isinstance(text, str) and text.strip():
            return text.strip()

    # OpenAI Responses API 互換フォールバック (旧形式)
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    for item in payload.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return None


def generate_text_from_messages(messages: list[dict[str, Any]], max_output_tokens: int = 220) -> str | None:
    if not ai_conversation_enabled():
        return None

    api_key = get_ai_api_key()
    if not api_key:
        return None

    # Chat Completions 形式 (DeepSeek / GitHub Models / OpenAI 互換)
    request_payload: dict[str, Any] = {
        "model": get_ai_model(),
        "messages": messages,
        "max_tokens": max_output_tokens,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                _get_base_url(),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
            )
            response.raise_for_status()
            return _extract_output_text(response.json())
    except Exception:
        return None


def generate_text(system_prompt: str, user_prompt: str, max_output_tokens: int = 220) -> str | None:
    return generate_text_from_messages(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_output_tokens=max_output_tokens,
    )


def generate_text_direct(system_prompt: str, user_prompt: str, max_output_tokens: int = 800) -> str | None:
    """AI_CONVERSATION_ENABLED フラグを確認せず直接 API を呼ぶ（問題生成専用）。"""
    api_key = get_ai_api_key()
    if not api_key:
        return None
    request_payload: dict[str, Any] = {
        "model": get_ai_model(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_output_tokens,
        "temperature": 0.7,
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                _get_base_url(),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=request_payload,
            )
            response.raise_for_status()
            return _extract_output_text(response.json())
    except Exception:
        return None


def recognize_image_text(image_data_url: str) -> str | None:
    """画像内の手書き文字を AI Vision で読み取り、数式文字列を返す。

    ``AI_CONVERSATION_ENABLED`` フラグに関わらず、API キー
    (GITHUB_TOKEN / OPENAI_API_KEY) が設定されていれば呼び出せる。
    """
    api_key = get_ai_api_key()
    if not api_key:
        return None

    messages: list[dict] = [
        {
            "role": "system",
            "content": (
                "あなたは手書き数式画像の認識エンジンです。"
                "画像から数学の解答を正確に読み取り、テキスト化してください。\n"
                "出力ルール:\n"
                "- 数字、演算子（+ - * / ^）、括弧、小数点のみ出力\n"
                "- 負の数はマイナスを先頭に付ける: -6\n"
                "- 分数は a/b 形式: -1/3\n"
                "- 帯分数は整数と分数をスペースなしで: 1+2/3\n"
                "- ルートは sqrt(n) 形式\n"
                "- 余計な説明・文章・記号は一切付けない\n"
                "- 数式だけを1行で出力する"
            ),
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": image_data_url, "detail": "low"},
                },
                {
                    "type": "text",
                    "text": "この手書き画像の数学の答えを読み取ってください。数式のみ出力。",
                },
            ],
        },
    ]

    request_payload: dict = {
        "model": get_ai_model(),
        "messages": messages,
        "max_tokens": 60,
        "temperature": 0,
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                _get_base_url(),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
            )
            response.raise_for_status()
            return _extract_output_text(response.json())
    except Exception:
        return None


# =====================
# Claude API (Anthropic)
# =====================

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"


def get_claude_api_key() -> str | None:
    return os.getenv("CLAUDE_API_KEY") or None


# Claude API詳細エラー出力付き

def generate_claude_text_debug(system_prompt: str, user_prompt: str, max_output_tokens: int = 800, model: str = DEFAULT_CLAUDE_MODEL) -> str | None:
    """
    Claude API (Anthropic) 用のテキスト生成。デバッグ用にエラー詳細をprint出力。
    """
    api_key = get_claude_api_key()
    if not api_key:
        print("[ClaudeAPI] No API key")
        return None
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": max_output_tokens,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": user_prompt}
        ],
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(CLAUDE_API_URL, headers=headers, json=payload)
            print(f"[ClaudeAPI] status={response.status_code}")
            print(f"[ClaudeAPI] response={response.text}")
            response.raise_for_status()
            data = response.json()
            if "content" in data and isinstance(data["content"], list):
                for c in data["content"]:
                    if c.get("type") == "text" and c.get("text"):
                        return c["text"].strip()
            return None
    except Exception as e:
        print(f"[ClaudeAPI] Exception: {e}")
        return None

def generate_claude_text(system_prompt: str, user_prompt: str, max_output_tokens: int = 800, model: str = None) -> str | None:
    """
    Claude API (Anthropic) 用のテキスト生成。用途: 問題生成・解説生成・大量生成
    """
    api_key = get_claude_api_key()
    if not api_key:
        return None
    if not model:
        model = DEFAULT_CLAUDE_MODEL
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": max_output_tokens,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": user_prompt}
        ],
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(CLAUDE_API_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            if "content" in data and isinstance(data["content"], list):
                for c in data["content"]:
                    if c.get("type") == "text" and c.get("text"):
                        return c["text"].strip()
            return None
    except Exception:
        return None
