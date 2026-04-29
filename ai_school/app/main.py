from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# プロジェクトルートの .env を自動読み込み
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_FILE)

from .database import Base, DATA_DIR, SessionLocal, engine
from .routers import auth, classroom, english, feedback, flashcard, listening, owner, student, teacher
from .routers import api_students
from .services.auth_service import check_startup_security
from .services.problem_service import ensure_runtime_schema, seed_initial_data

_APP_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _APP_DIR.parents[1]
_STATIC_DIR = _APP_DIR / "static"
_LP_HTML = _REPO_ROOT / "lp.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_startup_security()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (Path(__file__).resolve().parent / 'static' / 'audio').mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_runtime_schema(db)
        seed_initial_data(db)
    yield


app = FastAPI(
    title="AI塾 QRelDo",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
app.include_router(api_students.router)
app.include_router(api_students.auth_router)
app.include_router(auth.router)
app.include_router(student.router)
app.include_router(english.router)
app.include_router(listening.router)
app.include_router(teacher.router)
app.include_router(classroom.router)
app.include_router(owner.router)
app.include_router(feedback.router)
app.include_router(flashcard.router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/lp")


@app.get("/lp", include_in_schema=False)
def lp():
    return FileResponse(_LP_HTML, media_type="text/html")

from fastapi.responses import JSONResponse
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

# コンタクト受信メールアドレス
CONTACT_RECIPIENT_EMAIL = "zionjuku@gmail.com"
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")


@app.post("/api/contact", include_in_schema=False)
async def contact_form(request: Request):
    """LP からのコンタクトフォーム送信を処理"""
    try:
        form = await request.form()
        inquiry_type = form.get("inquiry_type", "")
        company_name = form.get("company_name", "")
        name = form.get("name", "")
        email = form.get("email", "")
        phone = form.get("phone", "")
        scale = form.get("scale", "")
        message = form.get("message", "")
        
        # メール本文を作成
        body = f"""
【LP コンタクトフォーム】

【お申し込み種別】
{inquiry_type}

【塾・学校名】
{company_name}

【お名前】
{name}

【メールアドレス】
{email}

【電話番号】
{phone}

【生徒数・教室規模】
{scale}

【ご質問・ご要望】
{message}
"""
        
        # メール送信（SMTP設定がある場合）
        if SMTP_USER and SMTP_PASSWORD:
            try:
                msg = MIMEMultipart()
                msg["From"] = SMTP_USER
                msg["To"] = CONTACT_RECIPIENT_EMAIL
                msg["Subject"] = f"【QRelDo LP】コンタクト: {name} 様"
                msg.attach(MIMEText(body, "plain", "utf-8"))
                
                with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                    server.starttls()
                    server.login(SMTP_USER, SMTP_PASSWORD)
                    server.send_message(msg)
            except Exception as e:
                print(f"メール送信エラー: {e}")
        
        return JSONResponse({"success": True, "message": "送信完了"})
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)


if __name__ == "__main__":
    import uvicorn

    # リポジトリルートで: python -m ai_school.app.main
    # http://localhost:8765/ と http://127.0.0.1:8765/ の両方で LP（/ から /lp へリダイレクト）
    uvicorn.run(app, host="0.0.0.0", port=8765)
