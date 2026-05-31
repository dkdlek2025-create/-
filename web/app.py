"""
Web dashboard for Stock AI Agent.
Runs FastAPI + Telegram bot + scheduled scanner in a single process.
"""
import asyncio
import logging
import time
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

import database as db
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Bot / Scanner references (set by lifespan) ---
telegram_app = None
scheduler = None

# --- Simple auth middleware ---
_REQUIRE_AUTH = bool(settings.web_api_key)
_SCAN_LAST_CALL = 0.0
_SCAN_MIN_INTERVAL = 30.0  # seconds

def _ticker_ok(t: str) -> bool:
    return bool(re.match(r'^[A-Za-z0-9]{1,10}$', t.strip()))

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not _REQUIRE_AUTH:
            return await call_next(request)
        # Allow /health without auth
        if request.url.path == "/health":
            return await call_next(request)
        key = request.query_params.get("key", "")
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            key = auth[7:]
        if key != settings.web_api_key:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        return await call_next(request)


def _kr_name(ticker: str) -> str:
    """Look up Korean stock name from universe cache."""
    try:
        from scanner.universe import universe
        for s in universe.get_all_kr():
            if s["ticker"] == ticker:
                return s.get("name", "")
    except Exception:
        pass
    return ""


def _fix_kr_names(opps: list[dict]) -> list[dict]:
    """Replace English/KR names with Korean names where available."""
    for opp in opps:
        if opp.get("market") == "korea":
            kr = _kr_name(opp["ticker"])
            if kr:
                opp["name"] = kr
    return opps


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start bot + scheduler on startup, stop on shutdown."""
    global telegram_app, scheduler

    # Start Telegram bot in background
    token = settings.telegram_bot_token
    if token:
        try:
            from telegram.ext import Application
            telegram_app = Application.builder().token(token).build()
            from bot.telegram_bot import register_handlers
            register_handlers(telegram_app)
            await telegram_app.initialize()
            await telegram_app.start()
            await telegram_app.updater.start_polling()
            logger.info("✅ Telegram bot started")
        except Exception as e:
            logger.error(f"❌ Telegram bot failed: {e}")

    # Start scheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler()
    interval = max(getattr(settings, 'scan_interval_minutes', 30), 10)
    scheduler.add_job(run_scan, 'interval', minutes=interval, id='scan')
    scheduler.start()
    logger.info(f"✅ Scheduler started (every {interval} min)")

    yield

    # Shutdown
    if scheduler:
        scheduler.shutdown(wait=False)
    if telegram_app:
        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()


app = FastAPI(title="Stock AI Agent", lifespan=lifespan)
app.add_middleware(AuthMiddleware)

# CORS: only allow same-origin
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=[],
)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _tech_label(score: int) -> str:
    """Convert -9~+9 tech score to readable label."""
    if score >= 5: return "매우긍정"
    if score >= 2: return "긍정"
    if score >= -1: return "중립"
    if score >= -4: return "부정"
    return "매우부정"


def _tech_color(score: int) -> str:
    if score >= 5: return "#3fb950"
    if score >= 2: return "#58a6ff"
    if score >= -1: return "#8b949e"
    if score >= -4: return "#d29922"
    return "#ff7b72"


templates.env.filters["tech_label"] = _tech_label
templates.env.filters["tech_color"] = _tech_color


# --- Scanner task ---

async def run_scan():
    """Run opportunity scan and save results."""
    try:
        from scanner.opportunity_finder import finder
        loop = asyncio.get_event_loop()
        # Save top 20 each market so recommendations page has enough data
        from concurrent.futures import TimeoutError as FutureTimeout
        kr_fut = loop.run_in_executor(
            None, lambda: finder.find_opportunities(market="korea", max_results=20, save_db=True)
        )
        us_fut = loop.run_in_executor(
            None, lambda: finder.find_opportunities(market="us", max_results=20, save_db=True)
        )
        try:
            opps_kr = await asyncio.wait_for(kr_fut, timeout=120)
        except FutureTimeout:
            logger.error("KR scan timed out after 120s")
            opps_kr = []
        try:
            opps_us = await asyncio.wait_for(us_fut, timeout=120)
        except FutureTimeout:
            logger.error("US scan timed out after 120s")
            opps_us = []
        opps = (opps_kr or []) + (opps_us or [])
        if opps:
            logger.info(f"✅ Scan: {len(opps)} opportunities found (kr:{len(opps_kr or [])} us:{len(opps_us or [])})")
            # Push to Telegram
            if telegram_app and settings.telegram_chat_id:
                for opp in opps[:5]:  # 텔레그램은 top 5만
                    msg = opp.to_telegram_msg()
                    try:
                        await telegram_app.bot.send_message(
                            chat_id=settings.telegram_chat_id,
                            text=msg,
                            disable_web_page_preview=True,
                        )
                        logger.info(f"  → Pushed {opp.name} to Telegram")
                    except Exception as e:
                        logger.error(f"  → Telegram push failed: {e}")
    except Exception as e:
        logger.error(f"❌ Scan failed: {e}")


# --- Web Routes ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    stats = db.get_stats()
    opps = _fix_kr_names(db.get_latest_opportunities(20))
    analyses = db.get_recent_analyses(10)
    return templates.TemplateResponse(request, "dashboard.html", {
        "stats": stats,
        "opportunities": opps,
        "analyses": analyses,
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.get("/opportunities", response_class=HTMLResponse)
async def opportunities_page(request: Request, min_score: int = Query(0, alias="score")):
    opps = _fix_kr_names(db.get_opportunities_by_score(min_score=min_score, limit=50))
    stats = db.get_stats()
    return templates.TemplateResponse(request, "opportunities.html", {
        "opportunities": opps,
        "stats": stats,
        "min_score": min_score,
    })


@app.get("/analyze", response_class=HTMLResponse)
async def analyze_page(request: Request, ticker: str = ""):
    result = None
    error = None
    if ticker:
        if not _ticker_ok(ticker):
            error = f"잘못된 티커 형식: {ticker}"
        else:
            try:
                from agent.stock_agent import agent
                from utils.search import searcher
                resolved = searcher.search_one(ticker)
                if resolved and "error" not in resolved:
                    ticker = resolved["ticker"]
                result = agent.analyze_ticker(ticker)
                if "error" not in result:
                    db.save_analysis(
                        ticker=result["ticker"],
                        name=result.get("name", ticker),
                        market=result.get("market", "UNKNOWN"),
                        action=result["decision"].get("action", "관망"),
                        score=result["decision"].get("combined_score", 0),
                        score_pct=int(((result["decision"].get("combined_score", 0) + 15) / 30) * 100),
                        tech_score=result["decision"].get("tech_score", 0),
                        news_score=result["decision"].get("news_score", 0),
                        reason=result["decision"].get("reason", ""),
                        current_price=result.get("price_data", {}).get("price", 0),
                    )
            except Exception as e:
                error = str(e)
    analyses = db.get_recent_analyses(20)
    return templates.TemplateResponse(request, "analyze.html", {
        "result": result,
        "error": error,
        "query": ticker,
        "analyses": analyses,
    })


@app.get("/news", response_class=HTMLResponse)
async def news_page(request: Request, ticker: str = ""):
    result = None
    error = None
    if ticker:
        if not _ticker_ok(ticker):
            error = f"잘못된 티커 형식: {ticker}"
        else:
            try:
                from analysis.news_analyzer import news_analyzer
                from utils.search import searcher
                resolved = searcher.search_one(ticker)
                if resolved and "error" not in resolved:
                    ticker = resolved["ticker"]
                result = news_analyzer.analyze_ticker_news(ticker)
                if result and result.get("news_count", 0) > 0:
                    db.save_news_cache(ticker, result)
            except Exception as e:
                error = str(e)
    all_news = db.get_all_news_cache()
    return templates.TemplateResponse(request, "news.html", {
        "result": result,
        "error": error,
        "query": ticker,
        "all_news": sorted(all_news, key=lambda x: x["overall_score_pct"], reverse=True),
    })


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    conn = db.get_db()
    scans = conn.execute(
        "SELECT * FROM scans ORDER BY started_at DESC LIMIT 30"
    ).fetchall()
    conn.close()
    analyses = db.get_recent_analyses(50)
    return templates.TemplateResponse(request, "history.html", {
        "scans": [dict(s) for s in scans],
        "analyses": analyses,
    })


@app.get("/recommendations", response_class=HTMLResponse)
async def recommendations_page(request: Request):
    """추천 종목: 국내 top 20, 미국 top 20"""
    all_opps = _fix_kr_names(db.get_opportunities_by_score(min_score=0, limit=100))
    korea = [o for o in all_opps if o.get("market") == "korea"][:20]
    us = [o for o in all_opps if o.get("market") == "us"][:20]
    stats = db.get_stats()
    return templates.TemplateResponse(request, "recommendations.html", {
        "korea": korea,
        "us": us,
        "stats": stats,
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


# --- API Routes ---

@app.get("/api/opportunities")
async def api_opportunities(limit: int = 10, min_score: int = 0):
    opps = _fix_kr_names(db.get_opportunities_by_score(min_score=min_score, limit=limit))
    return {"opportunities": opps, "count": len(opps)}


@app.get("/api/analyze/{ticker:str}")
async def api_analyze(ticker: str):
    if not _ticker_ok(ticker):
        return {"error": f"잘못된 티커 형식: {ticker}"}
    try:
        from agent.stock_agent import agent
        from utils.search import searcher
        resolved = searcher.search_one(ticker)
        if resolved and "error" not in resolved:
            ticker = resolved["ticker"]
        result = agent.analyze_ticker(ticker)
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/news/{ticker:str}")
async def api_news(ticker: str):
    if not _ticker_ok(ticker):
        return {"error": f"잘못된 티커 형식: {ticker}"}
    try:
        from analysis.news_analyzer import news_analyzer
        result = news_analyzer.analyze_ticker_news(ticker)
        return result or {"error": "No news found"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/scan")
async def api_scan():
    """Trigger a manual scan with rate limiting."""
    global _SCAN_LAST_CALL
    now = time.time()
    if now - _SCAN_LAST_CALL < _SCAN_MIN_INTERVAL:
        remaining = int(_SCAN_MIN_INTERVAL - (now - _SCAN_LAST_CALL))
        return {"status": "rate_limited", "retry_after_seconds": remaining}
    _SCAN_LAST_CALL = now
    asyncio.create_task(run_scan())
    return {"status": "started"}


@app.get("/api/scan/status")
async def api_scan_status():
    """Check latest scan status."""
    stats = db.get_stats()
    return {
        "last_scan": stats.get("last_scan"),
        "total_opportunities": stats.get("total_opportunities", 0),
    }


@app.get("/api/stats")
async def api_stats():
    return db.get_stats()


@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


def run():
    import uvicorn
    host = getattr(settings, 'web_host', '0.0.0.0')
    port = getattr(settings, 'web_port', 8000)
    logger.info(f"🌐 웹 대시보드: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
