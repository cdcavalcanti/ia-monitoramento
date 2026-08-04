"""Auth da UI/API — login único via env + cookie HMAC (padrão da casa).

Sem AUTH_EMAIL/AUTH_PASSWORD/AUTH_SECRET no .env a auth fica DESLIGADA
(comportamento antigo — uso local via SSH port-forward). Em produção os
três são obrigatórios ANTES de expor com túnel; senha e secret devem ser
gerados na própria VPS (openssl), nunca transitar em chat.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from app.config import get_settings

COOKIE_NAME = "qa_session"


def _sign(payload: str) -> str:
    s = get_settings()
    return hmac.new(s.auth_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    s = get_settings()
    exp = int(time.time() + s.auth_session_hours * 3600)
    payload = str(exp)
    return f"{payload}.{_sign(payload)}"


def token_valido(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    payload, assinatura = token.rsplit(".", 1)
    if not hmac.compare_digest(_sign(payload), assinatura):
        return False
    try:
        return int(payload) > time.time()
    except ValueError:
        return False


def credenciais_ok(email: str, password: str) -> bool:
    s = get_settings()
    email_ok = hmac.compare_digest(email.strip().lower(), s.auth_email.strip().lower())
    senha_ok = hmac.compare_digest(password, s.auth_password)
    return email_ok and senha_ok


# Página standalone (CSS inline de propósito): /static fica atrás do login
# junto com o resto, então o /login não pode depender de asset externo.
LOGIN_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IA de Monitoramento — login</title>
<style>
  :root {
    --bg: #070b14; --panel: #111827; --line: rgba(148,163,184,.14);
    --text: #f1f5f9; --muted: #94a3b8; --blue: #38bdf8; --blue-strong: #0ea5e9;
    --red: #ef4444;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; display: grid; place-items: center;
    font-family: "IBM Plex Sans", system-ui, sans-serif;
    background: radial-gradient(1200px 600px at 50% -10%, #0c1220 0%, var(--bg) 60%);
    color: var(--text);
  }
  .card {
    width: min(360px, calc(100vw - 32px)); background: var(--panel);
    border: 1px solid var(--line); border-radius: 12px; padding: 28px;
  }
  h1 { font-size: 17px; margin: 0 0 4px; }
  p.sub { margin: 0 0 20px; color: var(--muted); font-size: 13px; }
  label { display: block; font-size: 12px; color: var(--muted); margin: 12px 0 4px; }
  input {
    width: 100%; padding: 10px 12px; border-radius: 8px; font-size: 14px;
    border: 1px solid var(--line); background: #0c1220; color: var(--text);
  }
  input:focus { outline: none; border-color: var(--blue-strong); }
  button {
    width: 100%; margin-top: 18px; padding: 10px; border: 0; border-radius: 8px;
    background: var(--blue-strong); color: #fff; font-size: 14px; font-weight: 600;
    cursor: pointer;
  }
  button:hover { background: var(--blue); }
  #erro { color: var(--red); font-size: 13px; margin: 10px 0 0; display: none; }
</style>
</head>
<body>
<form class="card" id="f">
  <h1>IA de Monitoramento Infinity</h1>
  <p class="sub">Acesso restrito ao time.</p>
  <label for="email">E-mail</label>
  <input id="email" type="email" autocomplete="username" required>
  <label for="password">Senha</label>
  <input id="password" type="password" autocomplete="current-password" required>
  <button type="submit">Entrar</button>
  <p id="erro">Credenciais inválidas.</p>
</form>
<script>
  document.getElementById("f").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const r = await fetch("/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: document.getElementById("email").value,
        password: document.getElementById("password").value,
      }),
    });
    if (r.ok) { location.href = "/"; return; }
    document.getElementById("erro").style.display = "block";
  });
</script>
</body>
</html>"""
