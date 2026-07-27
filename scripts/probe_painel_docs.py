"""Probe Painel Infinity docs/OpenAPI and save locally if auth works."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(".env"))

base = (os.getenv("PAINEL_API_BASE_URL") or "https://painel-infinity.vercel.app").rstrip("/")
token = os.getenv("PAINEL_API_TOKEN") or ""
# fallback: alguns setups reusam o token do relatório
if not token:
    token = os.getenv("RELATORIO_API_TOKEN") or ""

print("base=", base)
print("token=", "OK" if token else "VAZIO")
print("PAINEL_ENABLED=", os.getenv("PAINEL_ENABLED"))

headers_list: list[dict[str, str]] = [{}]
if token:
    headers_list.extend(
        [
            {"Authorization": f"Bearer {token}"},
            {"X-API-Key": token},
            {"X-Relatorio-Token": token},
            {"x-api-key": token},
        ]
    )

paths = [
    "/api/openapi.json",
    "/openapi.json",
    "/api/docs-json",
    "/api/docs/json",
    "/swagger/v1/swagger.json",
    "/api/docs",
    "/api/status/overview",
]

out_dir = Path("docs")
out_dir.mkdir(exist_ok=True)

for path in paths:
    for h in headers_list:
        auth = next(iter(h.keys()), "none")
        try:
            r = httpx.get(
                base + path,
                headers={**h, "Accept": "application/json, text/html, */*"},
                timeout=30.0,
                follow_redirects=True,
            )
        except Exception as e:
            print(f"ERR {path} auth={auth} {type(e).__name__}")
            continue
        ctype = r.headers.get("content-type", "")
        print(f"{r.status_code} {path} auth={auth} ctype={ctype} len={len(r.content)}")
        if r.status_code != 200:
            continue
        if "json" in ctype or path.endswith(".json") or "openapi" in path or "swagger" in path or "docs-json" in path:
            # may still be HTML swagger
            text_start = r.text[:40].lstrip()
            if text_start.startswith("{") or text_start.startswith("["):
                target = out_dir / "painel-openapi.json"
                target.write_bytes(r.content)
                print("SAVED", target)
                raise SystemExit(0)
        if path == "/api/docs" and len(r.content) > 200:
            (out_dir / "painel-docs-raw.html").write_bytes(r.content)
            print("SAVED docs/painel-docs-raw.html")

print("DONE_NO_OPENAPI")
