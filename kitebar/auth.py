"""Kite login plumbing: token expiry, callback server, login result page."""

import html
from datetime import timedelta
from http.server import BaseHTTPRequestHandler
from string import Template
from urllib.parse import parse_qs, urlparse

from .constants import CALLBACK_PATH, TOKEN_EXPIRY_HOUR

def token_expiry(issued_at):
    """A Kite access token dies at the first 6:00 AM IST after it was issued."""
    expiry = issued_at.replace(hour=TOKEN_EXPIRY_HOUR, minute=0,
                               second=0, microsecond=0)
    if issued_at >= expiry:
        expiry += timedelta(days=1)
    return expiry


# Self-contained page shown in the browser tab Kite redirects to. No external
# assets (system fonts, inline SVG) so it renders instantly and offline. The
# kite glyph flies on success and droops on its string on failure.
LOGIN_PAGE = Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kite login · KiteBar</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🪁</text></svg>">
<style>
:root {
  --bg: #faf9f7; --ink: #1d1d1f; --dim: #71737a;
  --kite: #f6461a; --spar: rgba(255,255,255,.55);
  --string: #c9c6c0; --down: #9a9ca3;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #101013; --ink: #eceae6; --dim: #8f929b; --string: #3c3d43; }
}
* { margin: 0; box-sizing: border-box; }
html, body { height: 100%; }
body {
  display: grid; place-items: center;
  background: var(--bg); color: var(--ink);
  font: 15px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  -webkit-font-smoothing: antialiased;
}
main { max-width: 30rem; padding: 24px; text-align: center; }
.sky { display: flex; justify-content: center; margin-bottom: 6px; }
.sway { animation: sway 4.5s ease-in-out infinite alternate; }
.string { stroke-dasharray: 1 1; stroke-dashoffset: 1;
          animation: draw 1s .35s ease forwards; }
.fail .sway { animation: none; }
.fail .kite { transform: rotate(-18deg); transform-origin: 60px 96px; }
.fail .sail { fill: var(--down); }
h1 { font-size: clamp(28px, 5vw, 36px); font-weight: 700;
     letter-spacing: -.02em; margin-bottom: 10px; }
p { color: var(--dim); }
.wordmark { margin-top: 34px; color: var(--dim); opacity: .7;
            font: 11px/1 ui-monospace, "SF Mono", Menlo, monospace;
            letter-spacing: .14em; }
.rise { opacity: 0; transform: translateY(10px);
        animation: rise .55s cubic-bezier(.2,.7,.3,1) forwards; }
.d1 { animation-delay: .07s; }
.d2 { animation-delay: .14s; }
.d3 { animation-delay: .21s; }
@keyframes rise { to { opacity: 1; transform: none; } }
@keyframes sway {
  from { transform: translateY(0) rotate(-2deg); }
  to   { transform: translateY(-7px) rotate(2.5deg); }
}
@keyframes draw { to { stroke-dashoffset: 0; } }
@media (prefers-reduced-motion: reduce) {
  .sway, .string, .rise { animation: none; }
  .rise { opacity: 1; transform: none; }
  .string { stroke-dashoffset: 0; }
}
</style>
</head>
<body class="$state">
<main>
  <div class="sky rise" aria-hidden="true">
    <svg class="sway" width="120" height="150" viewBox="0 0 120 150" fill="none">
      <path class="string" pathLength="1" stroke="var(--string)"
            stroke-width="1.5" d="M60 96 C 50 116, 74 124, 58 146"/>
      <g class="kite">
        <path class="sail" d="M60 8 L94 48 L60 96 L26 48 Z" fill="var(--kite)"/>
        <path d="M60 8 L94 48 L60 96 Z" fill="rgba(0,0,0,.14)"/>
        <path d="M60 8 V96 M26 48 H94" stroke="var(--spar)" stroke-width="1.2"/>
      </g>
    </svg>
  </div>
  <h1 class="rise d1">$title</h1>
  <p class="rise d2">$message</p>
  <p class="wordmark rise d3">KITEBAR · KITE CONNECT</p>
</main>
</body>
</html>""")


def _login_page(ok, reason=None):
    if ok:
        return LOGIN_PAGE.substitute(
            state="ok",
            title="You’re in.",
            message=("KiteBar received your login and is fetching your "
                     "portfolio — you can close this tab."),
        )
    return LOGIN_PAGE.substitute(
        state="fail",
        title="Login didn’t complete",
        message=(f"Kite replied “{html.escape(reason or 'no request token')}” "
                 "instead of a request token. Open KiteBar in the menu "
                 "bar and click Login to try again."),
    )


class _CallbackHandler(BaseHTTPRequestHandler):
    """Catches Kite's redirect to http://127.0.0.1:8000/callback."""

    result = None  # class-level: {"request_token": ...} or {"error": ...}

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_error(404)
            return
        params = parse_qs(parsed.query)
        token = params.get("request_token", [None])[0]
        status = params.get("status", [None])[0]
        if token:
            _CallbackHandler.result = {"request_token": token}
            body = _login_page(ok=True)
        else:
            _CallbackHandler.result = {"error": status or "no request_token"}
            body = _login_page(ok=False, reason=status)
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # keep the console quiet
        pass
