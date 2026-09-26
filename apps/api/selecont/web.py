"""Minimal server-rendered HTTP surface for the closed selecont demo."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from html import escape
import hashlib
import hmac
import os
from pathlib import Path
from secrets import token_urlsafe
import time
from urllib.parse import parse_qs, urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.datastructures import UploadFile

from .auth import AuthenticationFailed, AuthStore, RateLimited
from .core import (
    InvalidInput,
    MAX_COMMENT_DEPTH,
    MAX_COMMENTS_PER_THREAD,
    MAX_PRIVATE_CIRCLES,
    NotFound,
    Store,
)
from .media import MAX_INPUT_BYTES, PhotoRejected, PhotoStore, StorageLimitExceeded


SESSION_COOKIE = "selecont_session"
LOGIN_CSRF_COOKIE = "selecont_login_csrf"
FORM_LIMIT = 16 * 1024
POST_FIELD_LIMIT = 64 * 1024
LOGIN_CSRF_TTL = 10 * 60
UPLOAD_REQUEST_LIMIT = MAX_INPUT_BYTES + 256 * 1024


class RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Bound form and multipart streams before buffering or spooling."""

    def __init__(self, app, *, limit):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
        ):
            await self.app(scope, receive, send)
            return
        limit = self.limit if scope["path"] in ("/settings/avatar", "/posts") else FORM_LIMIT
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        length = headers.get(b"content-length")
        try:
            declared_length = int(length) if length is not None else None
        except ValueError:
            response = Response("Invalid Content-Length", status_code=400, media_type="text/plain")
            await response(scope, receive, send)
            return
        if declared_length is not None and declared_length > limit:
            response = Response(
                "Request body is too large", status_code=413, media_type="text/plain"
            )
            await response(scope, receive, send)
            return

        consumed = 0

        async def limited_receive():
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > limit:
                    raise RequestBodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLarge:
            response = Response(
                "Request body is too large", status_code=413, media_type="text/plain"
            )
            await response(scope, receive, send)


@dataclass(frozen=True)
class Settings:
    database: Path
    secret_key: bytes
    cookie_secure: bool = False
    session_ttl: int = 8 * 60 * 60
    media_root: Path | None = None

    @classmethod
    def from_environment(cls):
        default_db = Path(__file__).resolve().parents[1] / "var" / "selecont.sqlite3"
        database = Path(os.environ.get("SELECONT_DATABASE", default_db))
        media_root = Path(os.environ.get("SELECONT_MEDIA_ROOT", database.parent / "media"))
        secure = os.environ.get("SELECONT_COOKIE_SECURE", "0") == "1"
        supplied = os.environ.get("SELECONT_SECRET_KEY")
        if secure and not supplied:
            raise RuntimeError("SELECONT_SECRET_KEY is required when secure cookies are enabled")
        if supplied and len(supplied.encode("utf-8")) < 32:
            raise RuntimeError("SELECONT_SECRET_KEY must contain at least 32 bytes")
        # Local development may restart sessions; a fresh secret only invalidates
        # CSRF values already rendered in an old page. Deployment requires an env secret.
        secret = supplied.encode("utf-8") if supplied else os.urandom(32)
        return cls(
            database=database,
            secret_key=secret,
            cookie_secure=secure,
            media_root=media_root,
        )


def _signature(settings, purpose, value):
    return hmac.new(
        settings.secret_key, f"{purpose}\0{value}".encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _matches_signature(submitted, expected):
    # compare_digest(str, str) raises on non-ASCII untrusted form/query input.
    return isinstance(submitted, str) and submitted.isascii() and hmac.compare_digest(submitted, expected)


def _new_login_challenge(settings):
    nonce = f"{int(time.time())}.{token_urlsafe(24)}"
    return nonce, _signature(settings, "login", nonce)


def _valid_login_challenge(settings, nonce, submitted):
    if not nonce or not submitted:
        return False
    timestamp, dot, _ = nonce.partition(".")
    if not dot or len(timestamp) > 12 or not timestamp.isascii() or not timestamp.isdigit():
        return False
    age = int(time.time()) - int(timestamp)
    return 0 <= age <= LOGIN_CSRF_TTL and _matches_signature(
        submitted, _signature(settings, "login", nonce)
    )


def _session_csrf(settings, token):
    return _signature(settings, "session", token)


def _access_proof(settings, kind, viewer_id, resource_id, context_id):
    value = f"{viewer_id}\0{resource_id}\0{context_id}"
    return _signature(settings, f"access:{kind}", value)


def _safe_next(value):
    return value if isinstance(value, str) and len(value) <= 256 and value.startswith("/") and not value.startswith("//") else "/u/grigory"


async def _form(request):
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Expected a form submission")
    body = await request.body()
    if len(body) > FORM_LIMIT:
        raise HTTPException(413, "Form is too large")
    try:
        parsed = parse_qs(body.decode("utf-8", "strict"), keep_blank_values=True, max_num_fields=12)
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(400, "Invalid form")
    if any(len(values) != 1 for values in parsed.values()):
        raise HTTPException(400, "Duplicate form field")
    return {key: values[0] for key, values in parsed.items()}


STYLE = """
:root{font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#173b67;background:#eef4f8}
*{box-sizing:border-box}body{margin:0;min-height:100vh;padding:24px}
main{width:min(940px,100%);margin:22px auto;background:#fff;border:1px solid #b9dcfa;border-radius:28px;padding:clamp(26px,5vw,52px);box-shadow:0 24px 70px #173b6714}
.brand{font-size:24px;letter-spacing:-.04em}.dot{color:#4aa4f0}h1{font-size:clamp(38px,7vw,68px);line-height:1;letter-spacing:-.05em;font-weight:500;margin:64px 0 18px}
.bio{font-size:22px;line-height:1.5;white-space:pre-wrap;color:#23364d}.meta{color:#61758b;line-height:1.5}.row{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}
a{color:#1769aa}label{display:block;margin:22px 0 8px;color:#334b64}input,select,textarea{width:100%;font:inherit;padding:13px 15px;border:1px solid #9db8d0;border-radius:12px;background:#fff}textarea{min-height:110px;resize:vertical;line-height:1.5}
button,.button{display:inline-block;border:0;border-radius:999px;background:#173b67;color:#fff;padding:12px 20px;font:inherit;text-decoration:none;cursor:pointer}
.quiet{background:transparent;color:#173b67;border:1px solid #9db8d0}.error{background:#fff0f0;color:#8d1a1a;padding:12px 14px;border-radius:12px}form.inline{display:inline}.footer{margin-top:56px;border-top:1px solid #dce7ef;padding-top:20px}
.avatar{display:block;width:144px;height:144px;object-fit:cover;border-radius:50%;border:1px solid #b9dcfa;margin:40px 0 20px;background:#eaf4fc}
.avatar.small{width:72px;height:72px;margin:0}.stack{display:grid;gap:18px;margin-top:28px}.card{border:1px solid #d5e5f2;border-radius:20px;padding:22px;background:#fbfdff}.card h2{font-weight:550;margin:0}.pill{display:inline-block;padding:5px 10px;border-radius:999px;background:#eaf4fc;color:#1769aa;font-size:13px}.member{display:grid;grid-template-columns:minmax(110px,1fr) minmax(190px,2fr);gap:16px;align-items:end}.member label{margin-top:0}.actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:16px}.section-title{margin:46px 0 8px;font-size:28px;font-weight:550}.post-card{overflow:hidden;padding:0}.post-photo{display:block;width:100%;max-height:520px;object-fit:cover;background:#eaf4fc}.post-copy{padding:22px}.post-copy p{white-space:pre-wrap;line-height:1.55;color:#23364d}.post-link{color:inherit;text-decoration:none}.choice{display:flex;gap:12px;align-items:flex-start;margin:0;padding:17px;border:1px solid #d5e5f2;border-radius:16px;background:#fbfdff}.choice input{width:auto;margin:4px 0 0}.choice strong,.choice span{display:block}.choice span{margin-top:4px;color:#61758b;font-size:14px}.audiences{display:grid;gap:12px;margin:14px 0 26px}.danger{background:#9e2a2b}.circle-picker{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0 24px}.circle-picker a{display:inline-block;padding:10px 16px;border:1px solid #9db8d0;border-radius:999px;text-decoration:none}.circle-picker a.active{background:#173b67;color:#fff;border-color:#173b67}.people-list{display:grid;gap:10px}.person-row{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 0;border-bottom:1px solid #dce7ef}.person-row:last-child{border-bottom:0}.person-row strong,.person-row span{display:block}.person-row .meta{margin-top:3px}.letter-heading{margin:26px 0 4px;color:#4b83b1;font-size:14px;letter-spacing:.12em;text-transform:uppercase}@media(max-width:560px){.member{grid-template-columns:1fr}.person-row{align-items:flex-start;flex-direction:column}main{padding:26px 20px}}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}.tab{display:inline-block;padding:10px 16px;border:1px solid #9db8d0;border-radius:999px;text-decoration:none;color:#173b67}.tab.active{background:#173b67;color:#fff;border-color:#173b67}.comments{display:grid;gap:12px;margin-top:18px}.comment{border-left:3px solid #b9dcfa;border-radius:0 14px 14px 0;padding:14px 16px;background:#f7fbfe}.comment p{white-space:pre-wrap;line-height:1.45;margin:8px 0}.comment-head{display:flex;gap:10px;justify-content:space-between;align-items:center}.comment-actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.comment-actions button{padding:7px 12px;font-size:13px}.like{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:24px 0}.reaction-list{margin:10px 0 0;padding-left:20px;color:#334b64}.composer{margin-top:24px}.composer textarea{min-height:88px}
.site-header{width:min(940px,100%);margin:0 auto;display:flex;align-items:center;justify-content:space-between;gap:18px;flex-wrap:wrap}.site-header .brand{font-weight:600;color:#173b67;text-decoration:none}.main-nav{display:flex;gap:7px;flex-wrap:wrap}.main-nav a{padding:9px 13px;border-radius:999px;color:#334b64;text-decoration:none}.main-nav a:hover,.main-nav a:focus{background:#dff0fd;color:#173b67}.eyebrow{font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:#4b83b1;font-weight:650}.notice{padding:18px 20px;border-radius:18px;background:#eaf4fc;border:1px solid #b9dcfa;line-height:1.5;margin:24px 0}.notice strong{display:block;margin-bottom:4px}.steps{display:grid;gap:14px;counter-reset:guide}.step{display:grid;grid-template-columns:42px 1fr;gap:14px;align-items:start;padding:18px;border:1px solid #d5e5f2;border-radius:18px;background:#fbfdff}.step:before{counter-increment:guide;content:counter(guide);display:grid;place-items:center;width:36px;height:36px;border-radius:50%;background:#173b67;color:#fff;font-weight:650}.step h2{margin:4px 0 6px;font-size:20px}.step p{margin:0;color:#61758b;line-height:1.5}.deleted-comment{opacity:.72;border-left-style:dashed}.deleted-copy{font-style:italic;color:#61758b}.context-help{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:20px 0}.context-help .card{padding:16px}.context-help strong{display:block;margin-bottom:5px}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:24px}.page-lead{font-size:18px;line-height:1.55;color:#4f6579;max-width:720px}
@media(max-width:650px){body{padding:14px}.site-header{align-items:flex-start}.main-nav{width:100%}.main-nav a{padding:8px 10px}main{padding:26px 20px;margin-top:16px}.member,.context-help{grid-template-columns:1fr}.comment{margin-left:0!important}h1{margin-top:38px}}
"""


ACCESS_WATCH_JS = """
(() => {
  const root = document.body;
  const checkUrl = root.dataset.accessCheck;
  const fallbackUrl = root.dataset.accessFallback;
  if (!checkUrl) return;

  let checking = false;
  let cleared = false;

  function hidePrivateContent(message) {
    if (cleared) return;
    cleared = true;
    document.title = "Доступ изменён · selecont";
    const panel = document.createElement("main");
    const brand = document.createElement("div");
    brand.className = "brand";
    brand.textContent = "selecont.";
    const heading = document.createElement("h1");
    heading.textContent = message;
    const note = document.createElement("p");
    note.className = "meta";
    note.textContent = "Проверяем текущий доступ…";
    panel.append(brand, heading, note);
    root.replaceChildren(panel);
  }

  async function verifyAccess() {
    if (checking || document.hidden) return;
    checking = true;
    const controller = new AbortController();
    const deadline = window.setTimeout(() => {
      hidePrivateContent("Проверяем соединение");
      controller.abort();
    }, 2000);
    try {
      const response = await fetch(checkUrl, {
        signal: controller.signal,
        cache: "no-store",
        credentials: "same-origin",
        headers: {"Accept": "application/vnd.selecont.access-check"}
      });
      if (response.status === 204) {
        if (cleared) window.location.reload();
        return;
      }
      hidePrivateContent("Доступ изменён");
      window.location.replace(fallbackUrl || "/");
    } catch (_error) {
      hidePrivateContent("Соединение потеряно");
    } finally {
      window.clearTimeout(deadline);
      checking = false;
    }
  }

  window.addEventListener("pagehide", () => hidePrivateContent("Проверяем текущий доступ"));
  window.addEventListener("pageshow", verifyAccess);
  window.addEventListener("online", verifyAccess);
  window.addEventListener("offline", () => hidePrivateContent("Соединение потеряно"));
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) hidePrivateContent("Проверяем текущий доступ");
    else verifyAccess();
  });
  window.setInterval(verifyAccess, 800);
  verifyAccess();
})();
"""


def _page(title, body, *, access_check=None, access_fallback=None):
    watch_attributes = ""
    watch_script = ""
    if access_check is not None:
        watch_attributes = (
            f' data-access-check="{escape(access_check, quote=True)}"'
            f' data-access-fallback="{escape(access_fallback or "/", quote=True)}"'
        )
        watch_script = '<script src="/assets/access-watch.js" defer></script>'
    navigation = """<header class="site-header">
      <a class="brand" href="/u/grigory">selecont<span class="dot">.</span></a>
      <nav class="main-nav" aria-label="Основная навигация">
        <a href="/u/grigory">Профиль</a><a href="/demo-guide">Как проверить</a>
        <a href="/settings/contexts">Круги</a><a href="/settings/posts">Посты</a>
        <a href="/posts/new">Создать пост</a>
      </nav></header>"""
    return "<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>" + escape(title) + " · selecont</title><style>" + STYLE + "</style></head><body" + watch_attributes + ">" + navigation + "<main>" + body + "</main>" + watch_script + "</body></html>"


def _post_cards(posts, photo_keys):
    cards = []
    for post in posts:
        post_id = escape(post["id"], quote=True)
        photo_key = photo_keys.get(post["id"])
        photo = (
            f'<img class="post-photo" src="/media/{escape(photo_key, quote=True)}" alt="">'
            if photo_key else ""
        )
        cards.append(
            f'<article class="card post-card"><a class="post-link" href="/p/{post_id}">'
            f'{photo}<div class="post-copy"><p>{escape(post["body"])}</p>'
            f'<span class="meta">Открыть публикацию и обсуждение →</span></div></a></article>'
        )
    return "".join(cards) or '<p class="meta">Здесь пока нет доступных публикаций.</p>'


def _discussion_path(post_id, branch_field, branch_value, reply_to=None):
    params = {branch_field: branch_value}
    if reply_to is not None:
        params["reply_to"] = reply_to
    return f"/p/{post_id}?{urlencode(params)}"


def _comment_tree(comments, *, post_id, csrf, viewer_id, post_author_id,
                  branch_field, branch_value, reply_to):
    """Render a bounded tree without recursive Python calls."""
    by_id = {comment["id"]: comment for comment in comments}
    children = {comment_id: [] for comment_id in by_id}
    roots = []
    for comment in comments:
        parent_id = comment["parent_id"]
        if parent_id is None or parent_id not in by_id:
            roots.append(comment["id"])
        else:
            children[parent_id].append(comment["id"])

    rendered = {}
    stack = [(comment_id, 0, False) for comment_id in reversed(roots)]
    while stack:
        comment_id, depth, expanded = stack.pop()
        comment = by_id[comment_id]
        if not expanded:
            stack.append((comment_id, depth, True))
            for child_id in reversed(children[comment_id]):
                stack.append((child_id, depth + 1, False))
            continue
        deleted = comment["deleted_at"] is not None
        controls = []
        if not deleted:
            reply_url = _discussion_path(
                post_id, branch_field, branch_value, comment_id
            )
            controls.append(f'<a href="{escape(reply_url, quote=True)}">Ответить</a>')
        if not deleted and viewer_id is not None and (
            viewer_id == comment["commenter_id"] or viewer_id == post_author_id
        ):
            controls.append(
                f'<form class="inline" method="post" action="/comments/{escape(comment_id, quote=True)}/delete">'
                f'<input type="hidden" name="csrf" value="{csrf}">'
                f'<input type="hidden" name="{branch_field}" value="{escape(branch_value, quote=True)}">'
                '<button class="quiet" type="submit">Удалить комментарий</button></form>'
            )
        selected = ' <span class="pill">Ответ будет здесь</span>' if reply_to == comment_id else ""
        child_html = "".join(rendered[child_id] for child_id in children[comment_id])
        if deleted:
            heading = '<span class="deleted-copy">Комментарий удалён</span>'
            copy = ""
        else:
            heading = f'<strong>@{escape(comment["handle"])}</strong>{selected}'
            copy = f'<p>{escape(comment["body"])}</p>'
        rendered[comment_id] = (
            f'<article class="comment{" deleted-comment" if deleted else ""}" style="margin-left:{min(depth, 5) * 18}px">'
            f'<div class="comment-head">{heading}</div>{copy}'
            f'<div class="comment-actions">{"".join(controls)}</div>{child_html}</article>'
        )
    return "".join(rendered[root_id] for root_id in roots)


def _comment_form(csrf, post_id, branch_field, branch_value, *, parent_id=None):
    parent = (
        f'<input type="hidden" name="parent_id" value="{escape(parent_id, quote=True)}">'
        if parent_id is not None else ""
    )
    label = "Написать ответ" if parent_id is not None else "Добавить комментарий"
    return f"""<form class="card composer" method="post" action="/p/{escape(post_id, quote=True)}/comments">
      <input type="hidden" name="csrf" value="{csrf}">
      <input type="hidden" name="{branch_field}" value="{escape(branch_value, quote=True)}">
      {parent}<label for="comment-body">{label}</label>
      <textarea id="comment-body" name="body" maxlength="2000" required></textarea>
      <p class="meta">Можно отвечать на ответы. Технический предел: {MAX_COMMENT_DEPTH} уровней и {MAX_COMMENTS_PER_THREAD} комментариев в одной ветке.</p>
      <button type="submit">Опубликовать</button>
    </form>"""


def _login_response(settings, *, next_url="/u/grigory", error=None, status=200):
    nonce, csrf = _new_login_challenge(settings)
    message = f'<p class="error" role="alert">{escape(error)}</p>' if error else ""
    body = f"""
    <div class="eyebrow">Закрытое демо</div>
    <h1>Вход в selecont</h1>
    <p class="page-lead">Войди под одной из тестовых ролей. Аккаунты создаются локальным оператором, публичной регистрации пока нет.</p>
    <p><a href="/demo-guide">Сначала открыть инструкцию по проверке</a></p>
    {message}
    <form method="post" action="/login">
      <input type="hidden" name="csrf" value="{csrf}">
      <input type="hidden" name="next" value="{escape(_safe_next(next_url), quote=True)}">
      <label for="username">Логин</label><input id="username" name="username" autocomplete="username" required maxlength="30">
      <label for="password">Пароль</label><input id="password" name="password" type="password" autocomplete="current-password" required maxlength="256">
      <p><button type="submit">Войти</button></p>
    </form>"""
    response = HTMLResponse(_page("Вход", body), status_code=status)
    response.set_cookie(
        LOGIN_CSRF_COOKIE, nonce, max_age=LOGIN_CSRF_TTL, httponly=True,
        secure=settings.cookie_secure, samesite="lax", path="/",
    )
    return response


def create_app(settings=None):
    settings = settings or Settings.from_environment()
    settings.database.parent.mkdir(parents=True, exist_ok=True)
    media_root = settings.media_root or settings.database.parent / "media"

    @asynccontextmanager
    async def lifespan(_app):
        store = PhotoStore(settings.database, media_root)
        store.close()
        yield

    app = FastAPI(title="selecont closed demo", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.media_root = media_root
    app.add_middleware(RequestBodyLimitMiddleware, limit=UPLOAD_REQUEST_LIMIT)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    def current_session(request):
        token = request.cookies.get(SESSION_COOKIE)
        with AuthStore(settings.database, session_ttl=settings.session_ttl) as auth:
            return token, auth.session(token)

    async def authenticated_form(request):
        token, session = current_session(request)
        if session is None:
            raise HTTPException(401, "Sign in required")
        data = await _form(request)
        submitted = data.get("csrf")
        if not isinstance(submitted, str) or not _matches_signature(
            submitted, _session_csrf(settings, token)
        ):
            raise HTTPException(403, "Invalid form")
        return token, session, data

    def sign_in_redirect(request, next_url):
        token, session = current_session(request)
        if session is not None:
            return token, session, None
        response = RedirectResponse(f"/login?next={next_url}", status_code=303)
        if token:
            response.delete_cookie(SESSION_COOKIE, path="/")
        return token, None, response

    @app.get("/", response_class=HTMLResponse)
    async def home():
        return RedirectResponse("/u/grigory", status_code=302)

    @app.get("/demo-guide", response_class=HTMLResponse)
    async def demo_guide(request: Request):
        _, session = current_session(request)
        if session is None:
            current = "Сейчас открыт анонимный режим: видна только публичная часть."
            account_action = '<a class="button" href="/login?next=/demo-guide">Войти в тестовый аккаунт</a>'
        else:
            current = f'Сейчас выполнен вход как @{escape(session.handle)}.'
            account_action = '<a class="button" href="/u/grigory">Открыть профиль Георгия</a>'
        body = f"""
        <div class="eyebrow">Инструкция по проверке</div>
        <h1>Пять шагов, чтобы понять selecont</h1>
        <p class="page-lead">Один профиль Георгия выглядит по-разному для друзей, семьи и публичных посетителей. Для одновременной проверки ролей используй разные браузеры или приватное окно.</p>
        <div class="notice"><strong>Текущая роль</strong>{current}</div>
        <div class="steps">
          <section class="step"><div><h2>Посмотри Public</h2><p>Открой профиль без входа. Должны быть только публичные био и публикации.</p></div></section>
          <section class="step"><div><h2>Сравни два аккаунта</h2><p>Войди по очереди в два тестовых аккаунта. URL профиля один и тот же, но био, фотографии и приватные публикации зависят от круга.</p></div></section>
          <section class="step"><div><h2>Проверь один пост</h2><p>Открой общий пост. General — публичное обсуждение, если пост опубликован Public. For you — обсуждение, доступное тебе.</p></div></section>
          <section class="step"><div><h2>Ответь и удали</h2><p>Можно отвечать на любой обычный комментарий. После удаления текст заменяется пометкой, а ответы остаются на месте.</p></div></section>
          <section class="step"><div><h2>Стань автором</h2><p>В своём аккаунте открой «Круги»: выбери нужный круг, проверь участников и добавь человека из алфавитного списка. Затем настрой био и фотографию. При создании поста фотография необязательна, но аудиторию нужно выбрать явно.</p></div></section>
        </div>
        <div class="actions">{account_action}<a class="button quiet" href="/settings/contexts">Управление кругами</a></div>
        <p class="meta">Аноним может только читать Public. Подписка, лайки и комментарии требуют входа.</p>"""
        return HTMLResponse(_page("Как проверить демо", body))

    @app.get("/healthz")
    async def healthz():
        store = Store(settings.database)
        try:
            store.db.execute("SELECT 1").fetchone()
            if not media_root.is_dir() or not os.access(media_root, os.W_OK):
                return Response(status_code=503)
        finally:
            store.close()
        return Response(status_code=204)

    @app.get("/assets/access-watch.js")
    async def access_watch_script():
        return Response(ACCESS_WATCH_JS, media_type="text/javascript")

    @app.get("/access/u/{handle}/private")
    async def check_private_profile_access(
        handle: str, request: Request, proof: str = ""
    ):
        token, session = current_session(request)
        if session is None:
            response = Response(status_code=404)
            if token:
                response.delete_cookie(SESSION_COOKIE, path="/")
            return response
        store = Store(settings.database)
        try:
            try:
                author_id = store.user_id_for_handle(handle)
                context_id = store.viewer_private_context(author_id, session.user_id)
                expected = _access_proof(
                    settings, "profile", session.user_id, author_id, context_id
                )
                if not _matches_signature(proof, expected):
                    raise NotFound()
            except NotFound:
                return Response(status_code=404)
        finally:
            store.close()
        return Response(status_code=204)

    @app.get("/access/p/{post_id}/private")
    async def check_private_post_access(
        post_id: str, request: Request, proof: str = ""
    ):
        token, session = current_session(request)
        if session is None:
            response = Response(status_code=404)
            if token:
                response.delete_cookie(SESSION_COOKIE, path="/")
            return response
        store = Store(settings.database)
        try:
            try:
                value = store.post(post_id, session.user_id)
                if "private" not in value["channels"]:
                    raise NotFound()
                author_id = store.user_id_for_handle(value["author_handle"])
                context_id = store.viewer_private_context(author_id, session.user_id)
                expected = _access_proof(
                    settings, "post", session.user_id, post_id, context_id
                )
                if not _matches_signature(proof, expected):
                    raise NotFound()
            except NotFound:
                return Response(status_code=404)
        finally:
            store.close()
        return Response(status_code=204)

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(next: str = "/u/grigory"):
        return _login_response(settings, next_url=next)

    @app.post("/login")
    async def login(request: Request):
        data = await _form(request)
        nonce = request.cookies.get(LOGIN_CSRF_COOKIE)
        if not _valid_login_challenge(settings, nonce, data.get("csrf")):
            raise HTTPException(403, "Invalid or expired form")
        client_key = request.client.host if request.client else "unknown"
        try:
            with AuthStore(settings.database, session_ttl=settings.session_ttl) as auth:
                token = auth.authenticate(data.get("username", ""), data.get("password", ""), client_key)
        except RateLimited as error:
            response = _login_response(settings, next_url=data.get("next", ""), error="Too many attempts. Try again later.", status=429)
            response.headers["Retry-After"] = str(error.retry_after)
            return response
        except AuthenticationFailed:
            return _login_response(settings, next_url=data.get("next", ""), error="Incorrect username or password.", status=401)
        response = RedirectResponse(_safe_next(data.get("next")), status_code=303)
        response.set_cookie(
            SESSION_COOKIE, token, max_age=settings.session_ttl, httponly=True,
            secure=settings.cookie_secure, samesite="lax", path="/",
        )
        response.delete_cookie(LOGIN_CSRF_COOKIE, path="/")
        return response

    @app.post("/logout")
    async def logout(request: Request):
        data = await _form(request)
        token, session = current_session(request)
        if session is None:
            raise HTTPException(401, "Sign in required")
        expected = _session_csrf(settings, token)
        if not data.get("csrf") or not _matches_signature(data["csrf"], expected):
            raise HTTPException(403, "Invalid form")
        with AuthStore(settings.database, session_ttl=settings.session_ttl) as auth:
            auth.logout(token)
        response = RedirectResponse("/u/grigory", status_code=303)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.get("/settings")
    async def settings_home():
        return RedirectResponse("/settings/contexts", status_code=302)

    @app.get("/settings/contexts", response_class=HTMLResponse)
    async def context_settings(request: Request, circle: str | None = None):
        token, session, redirect = sign_in_redirect(request, "/settings/contexts")
        if redirect is not None:
            return redirect
        store = Store(settings.database)
        try:
            variants = store.author_profile_variants(session.user_id, session.user_id)
            followers = store.author_followers(session.user_id, session.user_id)
        finally:
            store.close()
        csrf = _session_csrf(settings, token)
        private = [row for row in variants if row["kind"] == "private"]
        if circle is not None:
            selected_circle = next((row for row in private if row["id"] == circle), None)
            if selected_circle is None:
                raise HTTPException(404, "Circle not found")
        else:
            selected_circle = private[0] if private else None

        variant_cards = []
        for row in variants:
            context_id = escape(row["id"], quote=True)
            name = escape(row["name"])
            kind = "Public" if row["kind"] == "public" else "Скрытый круг"
            avatar = (
                f'<img class="avatar small" src="/media/{escape(row["asset_key"], quote=True)}" alt="">'
                if row["asset_key"]
                else '<div class="avatar small" aria-hidden="true"></div>'
            )
            variant_cards.append(
                f"""<section class="card">
                <div class="row"><div><span class="pill">{kind}</span><h2>{name}</h2></div>{avatar}</div>
                <form method="post" action="/settings/profile">
                  <input type="hidden" name="csrf" value="{csrf}">
                  <input type="hidden" name="context_id" value="{context_id}">
                  <label for="bio-{context_id}">Описание профиля для этой аудитории</label>
                  <textarea id="bio-{context_id}" name="bio" maxlength="500">{escape(row['bio'])}</textarea>
                  <div class="actions"><button type="submit">Сохранить описание</button>
                  <a class="button quiet" href="/settings/avatar?context_id={context_id}">Сменить фото</a>
                  <a href="/settings/preview/{context_id}">Посмотреть глазами аудитории</a></div>
                </form></section>"""
            )

        circle_picker = "".join(
            f'<a class="{"active" if selected_circle and row["id"] == selected_circle["id"] else ""}" '
            f'href="/settings/contexts?circle={escape(row["id"], quote=True)}">{escape(row["name"])}</a>'
            for row in private
        )
        member_html = candidate_html = ""
        if selected_circle is not None:
            selected_id = selected_circle["id"]
            selected_name = selected_circle["name"]
            members = sorted(
                (row for row in followers if row["context_id"] == selected_id),
                key=lambda row: row["handle"].casefold(),
            )
            candidates = sorted(
                (row for row in followers if row["context_id"] != selected_id),
                key=lambda row: row["handle"].casefold(),
            )
            member_rows = []
            for follower in members:
                member_rows.append(
                    f"""<div class="person-row"><div><strong>@{escape(follower['handle'])}</strong></div>
                    <form class="inline" method="post" action="/settings/membership">
                      <input type="hidden" name="csrf" value="{csrf}">
                      <input type="hidden" name="follower_id" value="{escape(follower['follower_id'], quote=True)}">
                      <input type="hidden" name="context_id" value="">
                      <input type="hidden" name="return_circle" value="{escape(selected_id, quote=True)}">
                      <button class="quiet" type="submit">Убрать из круга</button>
                    </form></div>"""
                )
            member_html = "".join(member_rows) or '<p class="meta">В этом круге пока никого нет.</p>'

            grouped = {}
            for follower in candidates:
                first = follower["handle"][:1].upper()
                letter = first if first.isalpha() else "#"
                grouped.setdefault(letter, []).append(follower)
            candidate_groups = []
            for letter in sorted(grouped):
                rows = []
                for follower in grouped[letter]:
                    current = follower["context_name"] or "Только Public"
                    rows.append(
                        f"""<div class="person-row"><div><strong>@{escape(follower['handle'])}</strong>
                        <span class="meta">Сейчас: {escape(current)}</span></div>
                        <form class="inline" method="post" action="/settings/membership">
                          <input type="hidden" name="csrf" value="{csrf}">
                          <input type="hidden" name="follower_id" value="{escape(follower['follower_id'], quote=True)}">
                          <input type="hidden" name="context_id" value="{escape(selected_id, quote=True)}">
                          <input type="hidden" name="return_circle" value="{escape(selected_id, quote=True)}">
                          <button type="submit">Добавить</button>
                        </form></div>"""
                    )
                candidate_groups.append(
                    f'<h3 class="letter-heading">{escape(letter)}</h3><div class="people-list">{"".join(rows)}</div>'
                )
            candidate_html = "".join(candidate_groups) or '<p class="meta">Все подписчики уже находятся в этом круге.</p>'
            follower_management = f"""
            <div class="circle-picker">{circle_picker}</div>
            <section class="card"><h2>Участники · {escape(selected_name)}</h2>
              <div class="people-list">{member_html}</div></section>
            <h3 class="section-title">Добавить людей</h3>
            <p class="meta">Показаны остальные подписчики по алфавиту. Если человек уже в другом круге, добавление перенесёт его сюда.</p>
            {candidate_html}"""
        else:
            follower_management = '<p class="meta">Сначала создай скрытый круг, затем сюда можно будет добавить подписчиков.</p>'
        body = f"""
        <div class="toolbar"><span class="pill">Вы вошли как автор @{escape(session.handle)}</span><a href="/u/{escape(session.handle, quote=True)}">Открыть профиль</a></div>
        <div class="eyebrow">Панель автора</div><h1>Круги и версии профиля</h1>
        <p class="page-lead">Здесь три последовательных действия: создай скрытый круг, настрой для него профиль, затем назначь подписчика. Названия и состав кругов видишь только ты.</p>
        <div class="notice"><strong>Главное правило MVP</strong>Один подписчик может находиться максимум в одном скрытом круге этого автора. «Только Public» немедленно закрывает весь частный доступ.</div>
        <h2 class="section-title">1. Создай скрытый круг</h2>
        <form class="card" method="post" action="/settings/circles">
          <input type="hidden" name="csrf" value="{csrf}">
          <label for="circle-name">Название, например «Друзья»</label><input id="circle-name" name="name" maxlength="60" required>
          <p class="meta">До {MAX_PRIVATE_CIRCLES} скрытых кругов в этом демо.</p>
          <button type="submit">Создать круг</button>
        </form>
        <h2 class="section-title">2. Настрой версии профиля</h2>
        <p class="meta">Public видят все. Каждый скрытый круг получает своё описание и фотографию.</p>
        <div class="stack">{''.join(variant_cards)}</div>
        <h2 class="section-title">3. Распредели подписчиков</h2>
        <p class="meta">Сначала выбери круг. Здесь виден его состав и остальные подписчики, которых можно добавить.</p>
        {follower_management}"""
        return HTMLResponse(_page("Круги и версии профиля", body))

    @app.post("/settings/circles")
    async def create_circle(request: Request):
        _, session, data = await authenticated_form(request)
        try:
            store = Store(settings.database)
            try:
                circle_id = store.create_circle(session.user_id, data.get("name"))
            finally:
                store.close()
        except InvalidInput as error:
            raise HTTPException(400, str(error))
        return RedirectResponse(f"/settings/contexts?{urlencode({'circle': circle_id})}", status_code=303)

    @app.post("/settings/profile")
    async def update_profile(request: Request):
        _, session, data = await authenticated_form(request)
        context_id, bio = data.get("context_id"), data.get("bio")
        if not isinstance(context_id, str) or not isinstance(bio, str):
            raise HTTPException(400, "Invalid profile form")
        store = Store(settings.database)
        try:
            try:
                store.set_profile_bio(session.user_id, context_id, bio=bio)
            except NotFound:
                raise HTTPException(404, "Profile context not found")
            except InvalidInput as error:
                raise HTTPException(400, str(error))
        finally:
            store.close()
        return RedirectResponse("/settings/contexts", status_code=303)

    @app.post("/settings/membership")
    async def update_membership(request: Request):
        _, session, data = await authenticated_form(request)
        follower_id, context_id = data.get("follower_id"), data.get("context_id")
        return_circle = data.get("return_circle")
        if not isinstance(follower_id, str) or not isinstance(context_id, str):
            raise HTTPException(400, "Invalid membership form")
        store = Store(settings.database)
        try:
            try:
                if context_id:
                    store.assign(session.user_id, follower_id, context_id)
                else:
                    store.revoke(session.user_id, follower_id)
            except NotFound:
                raise HTTPException(404, "Follower or circle not found")
            except InvalidInput as error:
                raise HTTPException(400, str(error))
        finally:
            store.close()
        target_circle = context_id or return_circle
        target = (
            f"/settings/contexts?{urlencode({'circle': target_circle})}"
            if isinstance(target_circle, str) and target_circle else "/settings/contexts"
        )
        return RedirectResponse(target, status_code=303)

    @app.get("/settings/preview/{context_id}", response_class=HTMLResponse)
    async def preview_profile(context_id: str, request: Request):
        _, session, redirect = sign_in_redirect(request, f"/settings/preview/{context_id}")
        if redirect is not None:
            return redirect
        store = Store(settings.database)
        try:
            try:
                variants = store.author_profile_variants(session.user_id, session.user_id)
                context = next(row for row in variants if row["id"] == context_id)
                value = store.profile(
                    session.user_id,
                    session.user_id,
                    preview_context=context_id,
                )
            except (NotFound, StopIteration):
                return HTMLResponse(
                    _page("Not found", '<h1>Preview not found</h1>'), status_code=404
                )
        finally:
            store.close()
        photos = PhotoStore(settings.database, media_root, cleanup_on_open=False)
        try:
            try:
                avatar_key = photos.profile_avatar_key(
                    session.user_id,
                    session.user_id,
                    preview_context=context_id,
                )
            except NotFound:
                avatar_key = None
        finally:
            photos.close()
        avatar = (
            f'<img class="avatar" src="/media/{escape(avatar_key, quote=True)}" alt="">'
            if avatar_key
            else ""
        )
        body = f"""
        <div class="row"><span class="pill">Предпросмотр: {escape(context['name'])}</span><a href="/settings/contexts">Вернуться к кругам</a></div>
        {avatar}<h1>@{escape(value['handle'])}</h1>
        <div class="bio">{escape(value['bio'])}</div>
        <div class="footer meta">Это режим чтения: он показывает выбранную версию профиля, но не превращает тебя в подписчика.</div>"""
        return HTMLResponse(_page(f"Предпросмотр @{value['handle']}", body))

    @app.get("/settings/avatar", response_class=HTMLResponse)
    async def avatar_form(request: Request):
        token, session, redirect = sign_in_redirect(request, "/settings/avatar")
        if redirect is not None:
            return redirect
        store = Store(settings.database)
        try:
            contexts = store.author_profile_variants(session.user_id, session.user_id)
        finally:
            store.close()
        requested_context = request.query_params.get("context_id")
        if requested_context is not None and not any(
            row["id"] == requested_context for row in contexts
        ):
            return HTMLResponse(_page("Not found", '<h1>Profile context not found</h1>'), status_code=404)
        options = "".join(
            f'<option value="{escape(row["id"], quote=True)}"'
            + (" selected" if row["id"] == requested_context else "")
            + f'>{escape(row["name"])}</option>'
            for row in contexts
        )
        body = f"""
        <div class="toolbar"><span class="pill">Автор @{escape(session.handle)}</span><a href="/settings/contexts">Вернуться к кругам</a></div>
        <h1>Фотография профиля</h1>
        <p class="page-lead">Выбери, для какой аудитории будет показана фотография. Поддерживаются JPEG, PNG и WebP, один файл до 10 МБ.</p>
        <form method="post" action="/settings/avatar" enctype="multipart/form-data">
          <input type="hidden" name="csrf" value="{_session_csrf(settings, token)}">
          <label for="context_id">Аудитория профиля</label><select id="context_id" name="context_id" required>{options}</select>
          <label for="photo">Фотография</label><input id="photo" name="photo" type="file" accept="image/jpeg,image/png,image/webp" required>
          <p><button type="submit">Сохранить фотографию</button></p>
        </form>"""
        return HTMLResponse(_page("Фотография профиля", body))

    @app.post("/settings/avatar")
    async def upload_avatar(request: Request):
        token, session = current_session(request)
        if session is None:
            raise HTTPException(401, "Sign in required")
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "multipart/form-data":
            raise HTTPException(415, "Expected a photo form")
        async with request.form(
            max_files=1, max_fields=2, max_part_size=FORM_LIMIT
        ) as form:
            if any(
                len(form.getlist(name)) != 1 for name in ("csrf", "context_id", "photo")
            ):
                raise HTTPException(400, "Invalid photo form")
            csrf = form.get("csrf")
            context_id = form.get("context_id")
            upload = form.get("photo")
            if not isinstance(csrf, str) or not _matches_signature(
                csrf, _session_csrf(settings, token)
            ):
                raise HTTPException(403, "Invalid form")
            if not isinstance(context_id, str) or not isinstance(upload, UploadFile):
                raise HTTPException(400, "Invalid photo form")
            photos = PhotoStore(settings.database, media_root, cleanup_on_open=False)
            asset = None
            try:
                asset = photos.store_photo(
                    session.user_id,
                    upload.file,
                    declared_content_type=upload.content_type,
                    original_name=upload.filename,
                )
                photos.attach_profile_avatar(session.user_id, context_id, asset.key)
            except NotFound:
                if asset is not None:
                    photos.discard_owned(session.user_id, asset.key)
                raise HTTPException(404, "Profile context not found")
            except StorageLimitExceeded as error:
                raise HTTPException(507, str(error))
            except PhotoRejected as error:
                status = 413 if "exceeds" in str(error).lower() else 400
                raise HTTPException(status, str(error))
            finally:
                photos.close()
        return RedirectResponse("/settings/contexts", status_code=303)

    @app.get("/posts/new", response_class=HTMLResponse)
    async def new_post_form(request: Request):
        token, session, redirect = sign_in_redirect(request, "/posts/new")
        if redirect is not None:
            return redirect
        store = Store(settings.database)
        try:
            contexts = store.author_contexts(session.user_id, session.user_id)
        finally:
            store.close()
        public = next(row for row in contexts if row["kind"] == "public")
        private = [row for row in contexts if row["kind"] == "private"]
        public_choice = f"""<label class="choice" for="audience-public">
          <input id="audience-public" name="audience" type="checkbox" value="{escape(public['id'], quote=True)}">
          <span><strong>Public</strong><span>Публикацию и General сможет увидеть любой посетитель.</span></span>
        </label>"""
        private_choices = "".join(
            f"""<label class="choice" for="audience-{escape(row['id'], quote=True)}">
              <input id="audience-{escape(row['id'], quote=True)}" name="audience" type="checkbox" value="{escape(row['id'], quote=True)}">
              <span><strong>{escape(row['name'])}</strong><span>Публикацию и отдельную ветку увидят только текущие участники круга.</span></span>
            </label>"""
            for row in private
        ) or '<p class="meta">Сначала создай хотя бы один скрытый круг.</p>'
        body = f"""
        <div class="toolbar"><span class="pill">Автор @{escape(session.handle)}</span><a href="/settings/posts">Вернуться к публикациям</a></div>
        <div class="eyebrow">Новая публикация</div><h1>Что и кому показать?</h1>
        <p class="page-lead">Добавь текст, при желании фотографию, затем явно отметь каждую аудиторию. Если никого не выбрать, публикация не создастся — это защищает от случайной отправки не тем людям.</p>
        <form method="post" action="/posts" enctype="multipart/form-data">
          <input type="hidden" name="csrf" value="{_session_csrf(settings, token)}">
          <label for="post-body">Текст публикации</label><textarea id="post-body" name="body" maxlength="5000" required></textarea>
          <label for="post-photo">Фотография <span class="meta">(необязательно, максимум одна)</span></label><input id="post-photo" name="photo" type="file" accept="image/jpeg,image/png,image/webp">
          <h2 class="section-title">Кто увидит публикацию?</h2>
          <div class="audiences">{public_choice}</div>
          <h3>Скрытые круги</h3><div class="audiences">{private_choices}</div>
          <button type="submit">Опубликовать</button>
        </form>"""
        return HTMLResponse(_page("Новая публикация", body))

    @app.post("/posts")
    async def create_post(request: Request):
        token, session = current_session(request)
        if session is None:
            raise HTTPException(401, "Sign in required")
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "multipart/form-data":
            raise HTTPException(415, "Expected a post form")
        async with request.form(
            max_files=1, max_fields=24, max_part_size=POST_FIELD_LIMIT
        ) as form:
            if (
                len(form.getlist("csrf")) != 1
                or len(form.getlist("body")) != 1
                or len(form.getlist("photo")) > 1
                or any(name not in {"csrf", "body", "photo", "audience"} for name in form)
            ):
                raise HTTPException(400, "Invalid post form")
            csrf = form.get("csrf")
            body = form.get("body")
            upload = form.get("photo")
            audiences = form.getlist("audience")
            if not isinstance(csrf, str) or not _matches_signature(
                csrf, _session_csrf(settings, token)
            ):
                raise HTTPException(403, "Invalid form")
            if (
                not isinstance(body, str)
                or not audiences
                or any(not isinstance(value, str) for value in audiences)
                or (upload is not None and not isinstance(upload, UploadFile))
            ):
                raise HTTPException(400, "Invalid post form")
            photos = PhotoStore(settings.database, media_root, cleanup_on_open=False)
            asset = None
            try:
                if isinstance(upload, UploadFile) and upload.filename:
                    asset = photos.store_photo(
                        session.user_id,
                        upload.file,
                        declared_content_type=upload.content_type,
                        original_name=upload.filename,
                    )
                store = Store(settings.database)
                try:
                    post_id = store.publish(
                        session.user_id,
                        body,
                        audiences,
                        photo_key=asset.key if asset is not None else None,
                    )
                finally:
                    store.close()
            except NotFound:
                if asset is not None:
                    photos.discard_owned(session.user_id, asset.key)
                raise HTTPException(404, "Audience not found")
            except InvalidInput as error:
                if asset is not None:
                    photos.discard_owned(session.user_id, asset.key)
                raise HTTPException(400, str(error))
            except StorageLimitExceeded as error:
                raise HTTPException(507, str(error))
            except PhotoRejected as error:
                status = 413 if "exceeds" in str(error).lower() else 400
                raise HTTPException(status, str(error))
            finally:
                photos.close()
        return RedirectResponse(f"/p/{post_id}", status_code=303)

    @app.get("/settings/posts", response_class=HTMLResponse)
    async def manage_posts(request: Request):
        token, session, redirect = sign_in_redirect(request, "/settings/posts")
        if redirect is not None:
            return redirect
        store = Store(settings.database)
        try:
            posts = store.author_posts(session.user_id, session.user_id)
            details = {
                post["id"]: store.author_post(session.user_id, post["id"])
                for post in posts
            }
        finally:
            store.close()
        csrf = _session_csrf(settings, token)
        cards = []
        for post in posts:
            detail = details[post["id"]]
            labels = "".join(
                f'<span class="pill">{escape(audience["name"])}</span> '
                for audience in detail["audiences"]
            )
            photo = (
                f'<img class="post-photo" src="/media/{escape(post["asset_key"], quote=True)}" alt="">'
                if post["asset_key"] else ""
            )
            post_id = escape(post["id"], quote=True)
            cards.append(
                f"""<article class="card post-card">{photo}<div class="post-copy">
                <div>{labels}</div><p>{escape(post['body'])}</p>
                <div class="actions"><a href="/p/{post_id}">Открыть обсуждение</a>
                <form class="inline" method="post" action="/p/{post_id}/delete">
                  <input type="hidden" name="csrf" value="{csrf}">
                  <button class="danger" type="submit">Удалить публикацию</button>
                </form></div></div></article>"""
            )
        body = f"""
        <div class="toolbar"><span class="pill">Автор @{escape(session.handle)}</span><a href="/u/{escape(session.handle, quote=True)}">Открыть профиль</a></div>
        <div class="eyebrow">Панель автора</div><h1>Все публикации</h1>
        <p class="page-lead">Здесь автор видит аудитории каждой публикации. В MVP аудитории нельзя изменить после публикации.</p>
        <div class="actions"><a class="button" href="/posts/new">Создать публикацию</a><a class="button quiet" href="/settings/contexts">Настроить круги</a></div>
        <div class="stack">{''.join(cards) or '<p class="meta">Публикаций пока нет.</p>'}</div>"""
        return HTMLResponse(_page("Все публикации", body))

    @app.get("/p/{post_id}", response_class=HTMLResponse)
    async def view_post(
        post_id: str,
        request: Request,
        thread: str | None = None,
        audience: str | None = None,
        reply_to: str | None = None,
    ):
        token, session = current_session(request)
        viewer_id = session.user_id if session else None
        store = Store(settings.database)
        try:
            try:
                value = store.post(post_id, viewer_id)
                photo_key = store.post_photo_key(post_id, viewer_id)
                post_author_id = store.user_id_for_handle(value["author_handle"])
                is_author = viewer_id == post_author_id

                if is_author:
                    if thread is not None:
                        raise NotFound()
                    detail = store.author_post(viewer_id, post_id)
                    allowed = {row["id"]: row for row in detail["audiences"]}
                    if audience is None:
                        selected = next(
                            (row for row in detail["audiences"] if row["kind"] == "public"),
                            detail["audiences"][0],
                        )
                    else:
                        selected = allowed.get(audience)
                        if selected is None:
                            raise NotFound()
                    branch_field, branch_value = "audience", selected["id"]
                    discussion = store.thread(
                        post_id, viewer_id, author_context=selected["id"]
                    )
                    discussion_context_id = selected["id"]
                    tab_rows = [
                        (row["name"], row["id"]) for row in detail["audiences"]
                    ]
                    branch_label = selected["name"]
                    identities = store.author_reactions(viewer_id, post_id)
                else:
                    if audience is not None:
                        raise NotFound()
                    channels = value["channels"]
                    selected_channel = thread or (
                        "private" if "private" in channels else "public"
                    )
                    if selected_channel not in ("public", "private") or selected_channel not in channels:
                        raise NotFound()
                    branch_field, branch_value = "thread", selected_channel
                    if selected_channel == "private":
                        discussion, discussion_context_id = store.thread_with_context(
                            post_id, viewer_id, channel=selected_channel
                        )
                    else:
                        discussion = store.thread(
                            post_id, viewer_id, channel=selected_channel
                        )
                        discussion_context_id = None
                    tab_rows = [
                        ("General" if channel == "public" else "For you", channel)
                        for channel in channels
                    ]
                    branch_label = "General" if selected_channel == "public" else "For you"
                    identities = []

                if reply_to is not None and reply_to not in {
                    comment["id"] for comment in discussion["comments"]
                    if comment["deleted_at"] is None
                }:
                    raise NotFound()
                reacted = (
                    store.has_reacted(viewer_id, post_id)
                    if viewer_id is not None else False
                )
            except NotFound:
                response = HTMLResponse(
                    _page("Not found", '<h1>Post not found</h1><p class="meta">This post is unavailable.</p>'),
                    status_code=404,
                )
                if token and session is None:
                    response.delete_cookie(SESSION_COOKIE, path="/")
                return response
        finally:
            store.close()
        account = (
            f'Вы вошли как <strong>@{escape(session.handle)}</strong>'
            if session else "Анонимный просмотр Public"
        )
        photo = (
            f'<img class="post-photo" src="/media/{escape(photo_key, quote=True)}" alt="">'
            if photo_key else ""
        )
        tabs = "".join(
            f'<a class="tab{" active" if tab_value == branch_value else ""}" '
            f'href="{escape(_discussion_path(post_id, branch_field, tab_value), quote=True)}">'
            f'{escape(label)}</a>'
            for label, tab_value in tab_rows
        )
        csrf = _session_csrf(settings, token) if session else ""
        comments = _comment_tree(
            discussion["comments"],
            post_id=post_id,
            csrf=csrf,
            viewer_id=viewer_id,
            post_author_id=post_author_id,
            branch_field=branch_field,
            branch_value=branch_value,
            reply_to=reply_to,
        )
        if session:
            composer = _comment_form(
                csrf, post_id, branch_field, branch_value, parent_id=reply_to
            )
            reaction = f"""<form class="inline" method="post" action="/p/{escape(post_id, quote=True)}/reaction">
              <input type="hidden" name="csrf" value="{csrf}">
              <input type="hidden" name="{branch_field}" value="{escape(branch_value, quote=True)}">
              <input type="hidden" name="active" value="{'0' if reacted else '1'}">
              <button class="{'quiet' if reacted else ''}" type="submit">{'Убрать лайк' if reacted else 'Поставить лайк'}</button>
            </form>"""
        else:
            composer = '<p class="notice">Чтобы комментировать и ставить лайки, войди в тестовый аккаунт.</p>'
            reaction = f'<a class="button" href="/login?next={escape(_discussion_path(post_id, branch_field, branch_value), quote=True)}">Войти</a>'
        identity_html = ""
        if is_author:
            items = "".join(
                f'<li>@{escape(row["handle"])} · {escape(row["context_name"])}</li>'
                for row in identities
            )
            identity_html = (
                '<section class="card"><strong>Кто поставил лайк</strong>'
                f'<ul class="reaction-list">{items}</ul></section>'
                if items else '<p class="meta">У этой публикации пока нет лайков.</p>'
            )
        if is_author:
            branch_explanation = f'<div class="notice"><strong>Режим автора</strong>Сейчас показано обсуждение аудитории «{escape(branch_label)}». Переключай вкладки ниже, чтобы проверить другие ветки.</div>'
            privacy_note = '<p class="meta">Каждый новый запрос заново проверяет доступ. Названия и состав скрытых кругов доступны только автору.</p>'
        elif branch_value == "public":
            branch_explanation = '<div class="notice"><strong>General</strong>Эту ветку видят все, кому доступна публичная публикация. Частные комментарии сюда автоматически не попадают.</div>'
            privacy_note = ""
        else:
            branch_explanation = ""
            privacy_note = ""
        body = f"""
        <div class="toolbar"><span class="pill">{account}</span><a href="/u/{escape(value['author_handle'], quote=True)}">Вернуться к профилю @{escape(value['author_handle'])}</a></div>
        <div class="eyebrow">Публикация</div><h1>Один пост, разные разговоры</h1>
        <article class="card post-card">{photo}<div class="post-copy"><p>{escape(value['body'])}</p></div></article>
        <div class="like"><strong>Лайков: {discussion['reaction_count']}</strong>{reaction}</div>
        {identity_html}
        <h2 class="section-title">Выбери обсуждение</h2>
        <nav class="tabs" aria-label="Обсуждения">{tabs}</nav>
        {branch_explanation}
        <h2 class="section-title">Комментарии · {escape(branch_label)}</h2>
        <div class="comments">{comments or '<p class="meta">В этом обсуждении пока нет комментариев.</p>'}</div>
        {composer}
        {privacy_note}"""
        if not is_author and branch_value == "private":
            proof = _access_proof(
                settings,
                "post",
                viewer_id,
                post_id,
                discussion_context_id,
            )
            access_check = f"/access/p/{post_id}/private?{urlencode({'proof': proof})}"
            access_fallback = f"/p/{post_id}"
        else:
            access_check = access_fallback = None
        return HTMLResponse(
            _page(
                "Публикация",
                body,
                access_check=access_check,
                access_fallback=access_fallback,
            )
        )

    @app.post("/p/{post_id}/comments")
    async def add_post_comment(post_id: str, request: Request):
        _, session, data = await authenticated_form(request)
        channel = data.get("thread")
        author_context = data.get("audience")
        if (channel is None) == (author_context is None):
            raise HTTPException(400, "Choose one discussion")
        if channel is not None and channel not in ("public", "private"):
            raise HTTPException(400, "Invalid discussion")
        parent_id = data.get("parent_id") or None
        store = Store(settings.database)
        try:
            try:
                store.add_comment(
                    session.user_id,
                    post_id,
                    data.get("body"),
                    channel=channel or "public",
                    author_context=author_context,
                    parent_id=parent_id,
                )
            except NotFound:
                raise HTTPException(404, "Post or discussion not found")
            except InvalidInput as error:
                raise HTTPException(400, str(error))
        finally:
            store.close()
        return RedirectResponse(
            _discussion_path(
                post_id,
                "audience" if author_context is not None else "thread",
                author_context if author_context is not None else channel,
            ),
            status_code=303,
        )

    @app.post("/p/{post_id}/reaction")
    async def set_post_reaction(post_id: str, request: Request):
        _, session, data = await authenticated_form(request)
        if data.get("active") not in ("0", "1"):
            raise HTTPException(400, "Invalid reaction")
        if ("thread" in data) == ("audience" in data):
            raise HTTPException(400, "Choose one discussion")
        store = Store(settings.database)
        try:
            try:
                if "audience" in data:
                    detail = store.author_post(session.user_id, post_id)
                    allowed = {row["id"] for row in detail["audiences"]}
                    branch_field, branch_value = "audience", data["audience"]
                    if branch_value not in allowed:
                        raise NotFound()
                elif data.get("thread") in ("public", "private"):
                    value = store.post(post_id, session.user_id)
                    branch_field, branch_value = "thread", data["thread"]
                    if branch_value not in value["channels"]:
                        raise NotFound()
                else:
                    raise InvalidInput("Invalid discussion")
                store.react(session.user_id, post_id, active=data["active"] == "1")
            except NotFound:
                raise HTTPException(404, "Post or discussion not found")
            except InvalidInput as error:
                raise HTTPException(400, str(error))
        finally:
            store.close()
        return RedirectResponse(
            _discussion_path(post_id, branch_field, branch_value), status_code=303
        )

    @app.post("/comments/{comment_id}/delete")
    async def delete_post_comment(comment_id: str, request: Request):
        _, session, _ = await authenticated_form(request)
        store = Store(settings.database)
        try:
            try:
                result = store.delete_comment(session.user_id, comment_id)
            except NotFound:
                raise HTTPException(404, "Comment not found")
        finally:
            store.close()
        if result["post_author_id"] == session.user_id:
            branch_field, branch_value = "audience", result["context_id"]
        else:
            branch_field, branch_value = "thread", result["channel"]
        return RedirectResponse(
            _discussion_path(result["post_id"], branch_field, branch_value),
            status_code=303,
        )

    @app.post("/p/{post_id}/delete")
    async def delete_post(post_id: str, request: Request):
        _, session, _ = await authenticated_form(request)
        store = Store(settings.database)
        try:
            try:
                storage_name = store.delete_post(session.user_id, post_id)
            except NotFound:
                raise HTTPException(404, "Post not found")
        finally:
            store.close()
        if storage_name is not None:
            photos = PhotoStore(settings.database, media_root, cleanup_on_open=False)
            try:
                photos.remove_orphan(storage_name)
            finally:
                photos.close()
        return RedirectResponse("/settings/posts", status_code=303)

    @app.get("/media/{key}")
    async def media(key: str, request: Request):
        token, session = current_session(request)
        viewer_id = session.user_id if session else None
        photos = PhotoStore(settings.database, media_root, cleanup_on_open=False)
        try:
            asset, payload = photos.read_for_viewer(viewer_id, key)
        except NotFound:
            response = Response(status_code=404)
            if token and session is None:
                response.delete_cookie(SESSION_COOKIE, path="/")
            return response
        finally:
            photos.close()
        response = Response(payload, media_type=asset.content_type)
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Vary"] = "Cookie"
        return response

    @app.post("/u/{handle}/follow")
    async def follow_profile(handle: str, request: Request):
        _, session, _ = await authenticated_form(request)
        store = Store(settings.database)
        try:
            try:
                author_id = store.user_id_for_handle(handle)
                store.follow(session.user_id, author_id)
            except NotFound:
                raise HTTPException(404, "Profile not found")
            except InvalidInput as error:
                raise HTTPException(400, str(error))
        finally:
            store.close()
        return RedirectResponse(f"/u/{handle}", status_code=303)

    @app.post("/u/{handle}/unfollow")
    async def unfollow_profile(handle: str, request: Request):
        _, session, _ = await authenticated_form(request)
        store = Store(settings.database)
        try:
            try:
                author_id = store.user_id_for_handle(handle)
                store.unfollow(session.user_id, author_id)
            except NotFound:
                raise HTTPException(404, "Profile not found")
        finally:
            store.close()
        return RedirectResponse(f"/u/{handle}", status_code=303)

    @app.get("/u/{handle}", response_class=HTMLResponse)
    async def profile(handle: str, request: Request):
        token, session = current_session(request)
        viewer_id = session.user_id if session else None
        store = Store(settings.database)
        try:
            author_id = store.user_id_for_handle(handle)
            value, profile_channel, profile_context_id = store.profile_with_channel(
                author_id, viewer_id
            )
            following = (
                store.is_following(session.user_id, author_id)
                if session and session.user_id != author_id
                else None
            )
            posts = store.list_posts(author_id, viewer_id)
            post_photos = {
                post["id"]: store.post_photo_key(post["id"], viewer_id)
                for post in posts
            }
        except NotFound:
            return HTMLResponse(_page("Not found", '<h1>Profile not found</h1><p class="meta">This profile is unavailable.</p>'), status_code=404)
        finally:
            store.close()
        photos = PhotoStore(settings.database, media_root, cleanup_on_open=False)
        try:
            avatar_key = photos.profile_avatar_key(author_id, viewer_id)
        finally:
            photos.close()
        if session:
            csrf = _session_csrf(settings, token)
            account = f"""<span>Вы вошли как <strong>@{escape(session.handle)}</strong></span>
            <form class="inline" method="post" action="/logout"><input type="hidden" name="csrf" value="{csrf}"><button class="quiet" type="submit">Выйти</button></form>"""
            if session.user_id == author_id:
                action = '<div class="actions"><a class="button" href="/posts/new">Создать публикацию</a><a class="button quiet" href="/settings/contexts">Настроить круги и профили</a><a href="/settings/posts">Все публикации</a></div>'
                note = "Это твой публичный вариант. Другие варианты открываются через предпросмотр в разделе «Круги»."
            else:
                follow_action = "unfollow" if following else "follow"
                follow_label = "Отписаться" if following else "Подписаться"
                follow_class = "quiet" if following else ""
                action = f"""<form method="post" action="/u/{escape(handle, quote=True)}/{follow_action}">
                <input type="hidden" name="csrf" value="{csrf}"><button class="{follow_class}" type="submit">{follow_label}</button></form>"""
                note = ""
        else:
            account = f'<span>Анонимный просмотр Public</span><a class="button" href="/login?next=/u/{escape(handle, quote=True)}">Войти</a>'
            action = ""
            note = "Без входа доступна только публичная часть. Для подписки, комментариев и лайков нужен аккаунт."
        avatar = (
            f'<img class="avatar" src="/media/{escape(avatar_key, quote=True)}" alt="">'
            if avatar_key
            else ""
        )
        body = f"""
        <div class="toolbar">{account}</div>
        <div class="eyebrow">Профиль автора</div>
        {avatar}
        <h1>@{escape(value['handle'])}</h1>
        <div class="bio">{escape(value['bio'])}</div>
        <div class="footer">{f'<p class="meta">{escape(note)}</p>' if note else ''}{action}</div>
        <h2 class="section-title">Доступные публикации</h2>
        <p class="meta">Список уже отфильтрован по твоей текущей аудитории.</p>
        <div class="stack">{_post_cards(posts, post_photos)}</div>"""
        if profile_channel == "private" and viewer_id != author_id:
            proof = _access_proof(
                settings, "profile", viewer_id, author_id, profile_context_id
            )
            access_check = f"/access/u/{handle}/private?{urlencode({'proof': proof})}"
        else:
            access_check = None
        response = HTMLResponse(
            _page(
                f"@{value['handle']}",
                body,
                access_check=access_check,
                access_fallback=f"/u/{handle}",
            )
        )
        if token and session is None:
            response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    return app


app = create_app()
