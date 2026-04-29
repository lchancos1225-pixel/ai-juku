import base64
import binascii
import logging
import os
import re
import subprocess
import tempfile
from urllib.parse import unquote_to_bytes

from .ai_service import get_ai_api_key, recognize_image_text
from .math_text_service import normalize_answer_for_grading

logger = logging.getLogger(__name__)

# 数式で使う文字だけ (全角括弧や sqrt 対応)
_ALLOWED_PATTERN = re.compile(r"^[A-Za-z0-9+\-*/^().]+$")

# AI が付けがちな余計なテキストを除去する
_AI_PREFIX_STRIP = re.compile(
    r"^(?:答え\s*[:：]\s*|answer\s*[:：]\s*|結果\s*[:：]\s*|→\s*|=\s*)",
    re.IGNORECASE,
)
_AI_CLEANUP = re.compile(r"[`「」\s]")


def _clean_ai_response(text: str) -> str:
    """AI Vision が返した応答から数式テキストだけを抽出する。"""
    text = text.strip()
    # コードブロック除去
    text = text.replace("```", "")
    # よくあるプレフィックス除去
    text = _AI_PREFIX_STRIP.sub("", text)
    # バッククォート・鉤括弧・空白除去
    text = _AI_CLEANUP.sub("", text)
    # 全角数字→半角
    for zc, hc in zip("０１２３４５６７８９", "0123456789"):
        text = text.replace(zc, hc)
    # 全角・特殊記号→半角
    text = text.replace("＋", "+").replace("－", "-").replace("−", "-")
    text = text.replace("×", "*").replace("÷", "/")
    text = text.replace("（", "(").replace("）", ")")
    return text.strip()


def normalize_ocr_text(text: str) -> str:
    normalized = str(text).replace("\n", "").replace("\r", "")
    normalized = normalized.replace("÷", "/").replace("×", "*")
    normalized = normalize_answer_for_grading(normalized)
    if re.fullmatch(r"\d+-\d+", normalized):
        return normalized.replace("-", "/", 1)
    if re.fullmatch(r"-\d+-\d+", normalized):
        return "-" + normalized[1:].replace("-", "/", 1)
    return normalized


def _decode_data_url(image_data_url: str) -> bytes:
    if not image_data_url.startswith("data:image/"):
        raise ValueError("Unsupported image format")
    header, _, payload = image_data_url.partition(",")
    if not payload:
        raise ValueError("Invalid data URL")
    if ";base64" in header:
        try:
            return base64.b64decode(payload)
        except binascii.Error as exc:
            raise ValueError("Invalid base64 data") from exc
    return unquote_to_bytes(payload)


class OCRResult:
    """OCR 処理の結果と失敗理由を保持する。"""
    __slots__ = ("text", "method", "error")

    def __init__(self, text: str = "", method: str = "", error: str = ""):
        self.text = text
        self.method = method
        self.error = error

    @property
    def ok(self) -> bool:
        return bool(self.text)


def recognize_handwritten_answer_detail(image_data_url: str) -> OCRResult:
    """OCR を実行し、認識結果と失敗時の理由を返す。"""
    try:
        image_bytes = _decode_data_url(image_data_url)
    except ValueError:
        return OCRResult(error="invalid_image")

    if not image_bytes:
        return OCRResult(error="empty_image")

    # --- 1st: AI Vision (GITHUB_TOKEN / OPENAI_API_KEY があれば使う) ---
    if get_ai_api_key():
        try:
            ai_result = recognize_image_text(image_data_url)
        except Exception:
            ai_result = None
        if ai_result:
            cleaned = _clean_ai_response(ai_result)
            normalized = normalize_ocr_text(cleaned)
            if normalized and _ALLOWED_PATTERN.fullmatch(normalized):
                return OCRResult(text=normalized, method="ai_vision")
            logger.info("AI Vision raw=%r cleaned=%r normalized=%r (rejected by pattern)", ai_result, cleaned, normalized)
    else:
        # API キー未設定
        logger.info("OCR: AI Vision skipped (no API key)")

    # --- 2nd: Tesseract (インストール済みの場合のフォールバック) ---
    tesseract_cmd = os.environ.get("AI_SCHOOL_TESSERACT_BIN", "tesseract")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(image_bytes)
        image_path = tmp.name

    tesseract_available = True
    try:
        configs = ["7", "8", "13"]
        whitelist = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-+./()*^"
        for psm in configs:
            try:
                result = subprocess.run(
                    [
                        tesseract_cmd,
                        image_path,
                        "stdout",
                        "--dpi",
                        "300",
                        "--psm",
                        psm,
                        "-c",
                        f"tessedit_char_whitelist={whitelist}",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=15,
                )
            except FileNotFoundError:
                tesseract_available = False
                break
            except subprocess.TimeoutExpired:
                continue
            if result.returncode != 0:
                continue
            recognized = normalize_ocr_text(result.stdout)
            if recognized and _ALLOWED_PATTERN.fullmatch(recognized):
                return OCRResult(text=recognized, method="tesseract")
    finally:
        try:
            os.remove(image_path)
        except OSError:
            pass

    # 両方失敗 — 理由を特定
    if not get_ai_api_key() and not tesseract_available:
        return OCRResult(error="no_ocr_backend")
    if not get_ai_api_key():
        return OCRResult(error="no_api_key")
    if not tesseract_available:
        return OCRResult(error="ai_vision_failed")
    return OCRResult(error="recognition_failed")


def recognize_handwritten_answer(image_data_url: str) -> str:
    """後方互換: 認識テキストだけ返す。"""
    return recognize_handwritten_answer_detail(image_data_url).text
