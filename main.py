import base64
import hashlib
import hmac
import json
import os
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, Response
import httpx

app = FastAPI()

# 替换为你小米平台的真实 API KEY
API_KEY = os.getenv("MIMO_API_KEY", "")
AUTH_USERNAME = os.getenv("TTS_AUTH_USERNAME", "")
AUTH_PASSWORD = os.getenv("TTS_AUTH_PASSWORD", "")
SESSION_SECRET = os.getenv("TTS_SESSION_SECRET", "")
SESSION_COOKIE_NAME = "tts_session"
V2_VOICE_ALIASES = {
    "en": "default_en",
    "english": "default_en",
    "default_en": "default_en",
    "mimo_en": "default_en",
    "zh": "default_zh",
    "chinese": "default_zh",
    "default_zh": "default_zh",
    "mimo_zh": "default_zh",
    "default": "mimo_default",
    "mimo_default": "mimo_default",
}
V2_VOICE_IDS = {"mimo_default", "default_zh", "default_en"}
V2_5_VOICE_ALIASES = {
    "en": "Mia",
    "english": "Mia",
    "default_en": "Mia",
    "mimo_en": "Mia",
    "zh": "冰糖",
    "chinese": "冰糖",
    "default_zh": "冰糖",
    "mimo_zh": "冰糖",
    "default": "mimo_default",
    "mimo_default": "mimo_default",
}
V2_5_VOICE_IDS = {
    "mimo_default",
    "冰糖",
    "茉莉",
    "苏打",
    "白桦",
    "Mia",
    "Chloe",
    "Milo",
    "Dean",
}
MODEL_V2_5 = "mimo-v2.5-tts"
MODEL_V2 = "mimo-v2-tts"
DEFAULT_ZH_SPEED = "变快"
DEFAULT_EN_SPEED = "Speed up"
CHINESE_LANGS = {"zh", "chinese", "default_zh", "mimo_zh", "zh-cn", "zh-hans", "zh-hant"}
ENGLISH_LANGS = {"en", "english", "default_en", "mimo_en", "en-us", "en-gb"}


def auth_enabled() -> bool:
    return bool(AUTH_USERNAME and AUTH_PASSWORD and SESSION_SECRET)


def create_session_token(username: str) -> str:
    signature = hmac.new(
        SESSION_SECRET.encode("utf-8"),
        username.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{username}:{signature}"


def validate_session_token(token: str) -> bool:
    if not token or ":" not in token:
        return False
    username, signature = token.split(":", 1)
    if username != AUTH_USERNAME:
        return False

    expected_signature = hmac.new(
        SESSION_SECRET.encode("utf-8"),
        username.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected_signature)


def validate_basic_auth(request: Request) -> bool:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        return False

    b64_value = auth_header[6:].strip()
    try:
        decoded = base64.b64decode(b64_value).decode("utf-8")
    except Exception:
        return False

    if ":" not in decoded:
        return False
    username, password = decoded.split(":", 1)
    return username == AUTH_USERNAME and password == AUTH_PASSWORD


def is_authorized(request: Request) -> bool:
    if not auth_enabled():
        return True

    session_token = request.cookies.get(SESSION_COOKIE_NAME, "")
    if validate_session_token(session_token):
        return True

    return validate_basic_auth(request)


def unauthorized_response() -> Response:
    response = Response(status_code=401, content="Unauthorized")
    response.headers["WWW-Authenticate"] = 'Basic realm="TTS Login"'
    return response


def build_messages(text: str, speed: str = "Speed up"):
    # 根据 MiMo 文档，<style> 标签可以控制语速和风格
    styled_text = f"<style>{speed}</style>{text}"
    return [
        {"role": "user", "content": "请自然朗读下面这段文本。"},
        {"role": "assistant", "content": styled_text},
    ]


def build_headers():
    if not API_KEY:
        raise RuntimeError("MIMO_API_KEY is not set")
    return {"api-key": API_KEY, "Content-Type": "application/json"}


def resolve_voice(lang: str, model: str) -> str:
    if not isinstance(lang, str) or not lang.strip():
        return "mimo_default"
    raw_value = lang.strip()
    if model == MODEL_V2_5:
        if raw_value in V2_5_VOICE_IDS:
            return raw_value
        normalized = raw_value.lower()
        return V2_5_VOICE_ALIASES.get(normalized, "mimo_default")
    if raw_value in V2_VOICE_IDS:
        return raw_value
    normalized = raw_value.lower()
    return V2_VOICE_ALIASES.get(normalized, "mimo_default")


def normalize_lang(lang: str) -> str:
    if not isinstance(lang, str):
        return ""
    return lang.strip().lower()


def is_chinese_lang(lang: str) -> bool:
    return normalize_lang(lang) in CHINESE_LANGS


def is_english_lang(lang: str) -> bool:
    return normalize_lang(lang) in ENGLISH_LANGS


def resolve_speed(lang: str, speed: str) -> str:
    # If caller explicitly provides speed, honor it.
    if isinstance(speed, str) and speed.strip():
        normalized = speed.strip().lower()
        if is_chinese_lang(lang) and normalized in {"speed up", "speedup", "speed-up"}:
            return DEFAULT_ZH_SPEED
        if is_english_lang(lang) and normalized in {DEFAULT_ZH_SPEED, DEFAULT_ZH_SPEED.lower()}:
            return DEFAULT_EN_SPEED
        return speed.strip()
    # Use language-appropriate default style tags when not provided.
    if is_chinese_lang(lang):
        return DEFAULT_ZH_SPEED
    if is_english_lang(lang):
        return DEFAULT_EN_SPEED
    return DEFAULT_EN_SPEED


def parse_flag(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"0", "false", "no", "off"}:
            return False
        return True
    return True


def resolve_model(data: dict) -> str:
    v2_value = data.get("v2")
    if v2_value is not None and parse_flag(v2_value):
        return MODEL_V2
    return MODEL_V2_5


async def parse_request_payload(request: Request):
    # Prefer JSON body; if client sends plain text or query params, fallback gracefully.
    raw = await request.body()
    if raw:
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            text_body = raw.decode("utf-8", errors="ignore").strip()
            if text_body:
                return {"text": text_body}

    return dict(request.query_params)


def extract_lang(data: dict) -> str:
    lang = data.get("lang") or data.get("locale") or data.get("voice")
    if isinstance(lang, str):
        return lang
    return ""


@app.get("/auth/login")
async def login_page():
    html = """
    <!doctype html>
    <html lang=\"en\">
    <head>
      <meta charset=\"utf-8\" />
      <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
      <title>TTS Login</title>
      <style>
        body { font-family: sans-serif; max-width: 420px; margin: 36px auto; padding: 0 12px; }
        label { display: block; margin-top: 12px; }
        input { width: 100%; padding: 8px; box-sizing: border-box; }
        button { margin-top: 14px; padding: 8px 14px; }
      </style>
    </head>
    <body>
      <h2>TTS Login</h2>
      <form method=\"post\" action=\"/auth/login\">
        <label>Username</label>
        <input type=\"text\" name=\"username\" required />
        <label>Password</label>
        <input type=\"password\" name=\"password\" required />
        <button type=\"submit\">Login</button>
      </form>
    </body>
    </html>
    """
    return Response(content=html, media_type="text/html")


@app.post("/auth/login")
async def login_submit(request: Request):
    if not auth_enabled():
        return Response(status_code=200, content="Auth disabled")

    raw_body = await request.body()
    form = parse_qs(raw_body.decode("utf-8", errors="ignore"))
    username = (form.get("username") or [""])[0]
    password = (form.get("password") or [""])[0]

    if username != AUTH_USERNAME or password != AUTH_PASSWORD:
        return Response(status_code=401, content="Invalid username or password")

    redirect_to = request.query_params.get("redirect", "/auth/check")
    response = Response(status_code=302)
    response.headers["Location"] = redirect_to
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=create_session_token(username),
        httponly=True,
        secure=(request.url.scheme == "https"),
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
        path="/",
    )
    return response


@app.get("/auth/check")
async def auth_check(request: Request):
    if is_authorized(request):
        return Response(status_code=200, content="OK")
    return unauthorized_response()


@app.get("/auth/logout")
async def auth_logout():
    response = Response(status_code=200, content="Logged out")
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response

@app.api_route("/tts", methods=["GET", "POST"])
async def mimo_tts(request: Request):
    try:
        if not is_authorized(request):
            return unauthorized_response()

        # 接收 Legado 传来的 JSON（也兼容纯文本和 query 参数）
        data = await parse_request_payload(request)
        text = data.get("text", "")
        
        if not text:
            return Response(status_code=400, content="No text provided")

        headers = build_headers()
        
        # 从请求参数获取语速。未传 speed 时，zh 默认“变快”，en 默认“Speed up”。
        lang = extract_lang(data)
        speed = resolve_speed(lang, data.get("speed", ""))
        voice = resolve_voice(lang, model)
        model = resolve_model(data)
        
        payload = {
            "model": model,
            # 参考官方文档：待合成文本应位于 assistant 角色消息中。
            "messages": build_messages(text, speed),
            "audio": {"voice": voice, "format": "wav"},
        }

        # 异步调用小米接口，设置 30 秒超时
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.xiaomimimo.com/v1/chat/completions", 
                headers=headers, 
                json=payload, 
                timeout=45.0
            )
            resp.raise_for_status()
            res_json = resp.json()

            # 提取并解码 Base64 音频数据
            choice = (res_json.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            audio = message.get("audio") or {}
            b64_audio = audio.get("data")

            if not b64_audio:
                return Response(
                    status_code=502,
                    content=f"MiMo response has no audio data: {res_json}",
                )

            audio_bytes = base64.b64decode(b64_audio)

            # 返回纯净的 WAV 流（与官方示例一致）
            return Response(content=audio_bytes, media_type="audio/wav")
            
    except Exception as e:
        print(f"Error: {e}")
        return Response(status_code=500, content=str(e))
