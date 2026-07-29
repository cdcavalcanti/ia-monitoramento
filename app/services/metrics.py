"""Métricas operacionais da IA de monitoramento (SQLite local).

Contadores:
  - chamadas LLM (tokens estimados/reais, propósito)
  - reprocessamentos capturados vs enviados
  - heartbeats de pollers/fontes
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.config import get_settings

logger = logging.getLogger("monitor.metrics")

_lock = threading.Lock()
_initialized = False

CHARS_PER_TOKEN = 4.0
OPENAI_IN_PER_M = 2.50
OPENAI_OUT_PER_M = 10.00


def _db_path():
    s = get_settings()
    s.ensure_dirs()
    return s.data_dir / "metrics.db"


def _tz():
    try:
        return ZoneInfo(get_settings().report_timezone or "America/Sao_Paulo")
    except Exception:
        try:
            return ZoneInfo("America/Sao_Paulo")
        except Exception:
            return timezone(timedelta(hours=-3))


@contextmanager
def _conn():
    path = _db_path()
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init() -> None:
    global _initialized
    with _lock:
        with _conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS llm_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    estimated INTEGER NOT NULL DEFAULT 1,
                    cost_usd REAL NOT NULL DEFAULT 0,
                    ok INTEGER NOT NULL DEFAULT 1,
                    detail TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_llm_ts ON llm_calls(ts);

                CREATE TABLE IF NOT EXISTS reprocess_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    status TEXT,
                    detail TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_repro_ts ON reprocess_events(ts);

                CREATE TABLE IF NOT EXISTS heartbeats (
                    source TEXT PRIMARY KEY,
                    ts TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT
                );
                """
            )
        _initialized = True


def _ensure() -> None:
    if not _initialized:
        init()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_bounds_utc() -> tuple[str, str]:
    tz = _tz()
    agora = datetime.now(tz)
    start = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()


def estimar_tokens(texto: str) -> int:
    if not texto:
        return 0
    return max(1, int(len(texto) / CHARS_PER_TOKEN))


def record_llm(
    *,
    provider: str,
    purpose: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int | None = None,
    estimated: bool = True,
    cost_usd: float = 0.0,
    ok: bool = True,
    detail: str | None = None,
) -> None:
    _ensure()
    total = total_tokens if total_tokens is not None else (prompt_tokens + completion_tokens)
    with _lock:
        with _conn() as conn:
            conn.execute(
                """
                INSERT INTO llm_calls
                (ts, provider, purpose, prompt_tokens, completion_tokens, total_tokens,
                 estimated, cost_usd, ok, detail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _now_iso(),
                    provider,
                    purpose,
                    int(prompt_tokens),
                    int(completion_tokens),
                    int(total),
                    1 if estimated else 0,
                    float(cost_usd),
                    1 if ok else 0,
                    detail,
                ),
            )


def record_llm_from_texts(
    *,
    provider: str,
    purpose: str,
    prompt: str,
    completion: str,
    usage: dict[str, Any] | None = None,
    ok: bool = True,
) -> None:
    usage = usage or {}
    pt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    ct = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    tt = int(usage.get("total_tokens") or 0)
    estimated = True
    if pt or ct or tt:
        estimated = False
        if not tt:
            tt = pt + ct
    else:
        pt = estimar_tokens(prompt)
        ct = estimar_tokens(completion)
        tt = pt + ct

    cost = 0.0
    if provider == "openai":
        cost = (pt / 1_000_000) * OPENAI_IN_PER_M + (ct / 1_000_000) * OPENAI_OUT_PER_M

    record_llm(
        provider=provider,
        purpose=purpose,
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=tt,
        estimated=estimated,
        cost_usd=cost,
        ok=ok,
    )


def record_reprocess(*, kind: str, count: int, status: str, detail: str | None = None) -> None:
    _ensure()
    with _lock:
        with _conn() as conn:
            conn.execute(
                """
                INSERT INTO reprocess_events (ts, kind, count, status, detail)
                VALUES (?, ?, ?, ?, ?)
                """,
                (_now_iso(), kind, int(count), status, detail),
            )


def heartbeat(source: str, status: str, detail: dict | str | None = None) -> None:
    _ensure()
    detail_s = (
        detail
        if isinstance(detail, str)
        else (json.dumps(detail, ensure_ascii=False, default=str) if detail else None)
    )
    with _lock:
        with _conn() as conn:
            conn.execute(
                """
                INSERT INTO heartbeats (source, ts, status, detail)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    ts=excluded.ts, status=excluded.status, detail=excluded.detail
                """,
                (source, _now_iso(), status, detail_s),
            )


def snapshot() -> dict[str, Any]:
    _ensure()
    start, end = _today_bounds_utc()
    with _lock:
        with _conn() as conn:
            llm = conn.execute(
                """
                SELECT
                    COUNT(*) AS calls,
                    COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens),0) AS completion_tokens,
                    COALESCE(SUM(total_tokens),0) AS total_tokens,
                    COALESCE(SUM(cost_usd),0) AS cost_usd,
                    COALESCE(SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END),0) AS falhas
                FROM llm_calls
                WHERE ts >= ? AND ts < ?
                """,
                (start, end),
            ).fetchone()

            by_provider = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT provider,
                           COUNT(*) AS calls,
                           COALESCE(SUM(total_tokens),0) AS total_tokens,
                           COALESCE(SUM(cost_usd),0) AS cost_usd
                    FROM llm_calls
                    WHERE ts >= ? AND ts < ?
                    GROUP BY provider
                    """,
                    (start, end),
                ).fetchall()
            ]

            repro = conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN kind='captured' THEN count ELSE 0 END),0) AS capturados,
                    COALESCE(SUM(CASE WHEN kind='sent' THEN count ELSE 0 END),0) AS enviados,
                    COALESCE(SUM(CASE WHEN kind='stub' THEN count ELSE 0 END),0) AS stub,
                    COALESCE(SUM(CASE WHEN kind='erro' THEN count ELSE 0 END),0) AS erros
                FROM reprocess_events
                WHERE ts >= ? AND ts < ?
                """,
                (start, end),
            ).fetchone()

            recent_repro = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT ts, kind, count, status, detail
                    FROM reprocess_events
                    ORDER BY id DESC LIMIT 12
                    """
                ).fetchall()
            ]

            beats = [
                dict(r)
                for r in conn.execute(
                    "SELECT source, ts, status, detail FROM heartbeats ORDER BY source"
                ).fetchall()
            ]

    tz = _tz()
    return {
        "dia": datetime.now(tz).date().isoformat(),
        "timezone": str(tz),
        "llm_hoje": {
            "calls": int(llm["calls"] or 0),
            "prompt_tokens": int(llm["prompt_tokens"] or 0),
            "completion_tokens": int(llm["completion_tokens"] or 0),
            "total_tokens": int(llm["total_tokens"] or 0),
            "cost_usd": round(float(llm["cost_usd"] or 0), 4),
            "falhas": int(llm["falhas"] or 0),
            "por_provider": by_provider,
            "nota": "Lab = GPU própria (custo USD ~0). OpenAI = estimativa de tabela.",
        },
        "reprocess_hoje": {
            "capturados": int(repro["capturados"] or 0),
            "enviados": int(repro["enviados"] or 0),
            "stub": int(repro["stub"] or 0),
            "erros": int(repro["erros"] or 0),
        },
        "reprocess_recentes": recent_repro,
        "heartbeats": beats,
    }
