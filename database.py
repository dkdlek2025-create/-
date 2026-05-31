"""
SQLite database for storing scan results, analysis history, and opportunities.
"""
import json
import sqlite3
import os
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "stock_agent.db"


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            total_scanned INTEGER DEFAULT 0,
            opportunities_found INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running'
        );

        CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER REFERENCES scans(id),
            ticker TEXT NOT NULL,
            name TEXT NOT NULL,
            market TEXT NOT NULL,
            action TEXT NOT NULL,
            score INTEGER NOT NULL,
            score_pct INTEGER NOT NULL,
            tech_score INTEGER NOT NULL,
            news_score REAL NOT NULL,
            news_score_pct INTEGER DEFAULT 50,
            conviction TEXT NOT NULL,
            reason TEXT,
            entry_zone TEXT,
            target TEXT,
            stop_loss TEXT,
            rr TEXT,
            current_price REAL,
            news_summary TEXT,
            news_bullish TEXT,
            news_bearish TEXT,
            conflict TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            name TEXT NOT NULL,
            market TEXT NOT NULL,
            action TEXT NOT NULL,
            score INTEGER NOT NULL,
            score_pct INTEGER NOT NULL,
            tech_score INTEGER NOT NULL,
            news_score REAL NOT NULL,
            reason TEXT,
            current_price REAL,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS news_cache (
            ticker TEXT PRIMARY KEY,
            overall_score REAL,
            overall_score_pct INTEGER,
            bullish_count INTEGER,
            bearish_count INTEGER,
            bullish_summary TEXT,
            bearish_summary TEXT,
            cached_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
    """)
    conn.commit()
    conn.close()


# -- Scans --

def save_scan_start() -> int:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO scans (started_at, status) VALUES (datetime('now', 'localtime'), 'running')"
    )
    scan_id = cur.lastrowid
    conn.commit()
    conn.close()
    return scan_id


def save_scan_end(scan_id: int, total: int, found: int, status: str = "completed"):
    conn = get_db()
    conn.execute(
        "UPDATE scans SET finished_at=datetime('now', 'localtime'), total_scanned=?, opportunities_found=?, status=? WHERE id=?",
        (total, found, status, scan_id),
    )
    conn.commit()
    conn.close()


# -- Opportunities --

def save_opportunities(scan_id: int, opps: list):
    conn = get_db()
    for o in opps:
        conn.execute(
            """INSERT INTO opportunities
            (scan_id, ticker, name, market, action, score, score_pct,
             tech_score, news_score, news_score_pct, conviction, reason,
             entry_zone, target, stop_loss, rr, current_price,
             news_summary, news_bullish, news_bearish, conflict)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                scan_id, o.ticker, o.name, o.market, o.action, o.score, o.score_pct,
                o.tech_score, o.news_score, o.news_score_pct, o.conviction, o.reason,
                o.entry_zone, o.target, o.stop_loss, str(o.rr), o.current_price,
                o.news_summary, o.news_bullish, o.news_bearish, o.conflict,
            ),
        )
    conn.commit()
    conn.close()


def get_latest_opportunities(limit: int = 20) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM opportunities ORDER BY created_at DESC, score DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_opportunities_by_score(min_score: int = 0, limit: int = 20) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM opportunities WHERE score >= ? ORDER BY score DESC, created_at DESC LIMIT ?",
        (min_score, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# -- Analyses --

def save_analysis(ticker: str, name: str, market: str, action: str,
                  score: int, score_pct: int, tech_score: int,
                  news_score: float, reason: str, current_price: float):
    conn = get_db()
    conn.execute(
        """INSERT INTO analyses
        (ticker, name, market, action, score, score_pct, tech_score, news_score, reason, current_price)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (ticker, name, market, action, score, score_pct, tech_score, news_score, reason, current_price),
    )
    conn.commit()
    conn.close()


def get_recent_analyses(limit: int = 30) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM analyses ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_analysis_by_ticker(ticker: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM analyses WHERE ticker=? ORDER BY created_at DESC", (ticker.upper(),)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# -- News cache --

def save_news_cache(ticker: str, result: dict):
    conn = get_db()
    conn.execute(
        """INSERT OR REPLACE INTO news_cache
        (ticker, overall_score, overall_score_pct, bullish_count, bearish_count,
         bullish_summary, bearish_summary)
        VALUES (?,?,?,?,?,?,?)""",
        (
            ticker, result.get("overall_score", 0), result.get("overall_score_pct", 50),
            result.get("bullish_count", 0), result.get("bearish_count", 0),
            result.get("bullish_summary", ""), result.get("bearish_summary", ""),
        ),
    )
    conn.commit()
    conn.close()


def get_all_news_cache() -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM news_cache ORDER BY overall_score_pct DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# -- Stats --

def get_stats() -> dict:
    conn = get_db()
    total_scans = conn.execute("SELECT COUNT(*) as c FROM scans").fetchone()["c"]
    total_opps = conn.execute("SELECT COUNT(*) as c FROM opportunities").fetchone()["c"]
    total_analyses = conn.execute("SELECT COUNT(*) as c FROM analyses").fetchone()["c"]
    last_scan = conn.execute(
        "SELECT * FROM scans ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return {
        "total_scans": total_scans,
        "total_opportunities": total_opps,
        "total_analyses": total_analyses,
        "last_scan": dict(last_scan) if last_scan else None,
    }


# Initialize on import
init_db()
