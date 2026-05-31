"""
Telegram Bot - 한글 명령어 + 회사명 검색 지원.
"""
import logging
import database as db
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from config import settings
from agent.stock_agent import agent
from utils.search import searcher

logging.basicConfig(level=logging.INFO)
_subscribed_chats: set[int] = set()


def _resolve_ticker(text: str) -> str:
    """Convert company name to ticker. If already a ticker, return as-is."""
    text = text.strip().upper()
    # If it looks like a ticker (all alpha or all digits), use as-is
    if text.isalpha() or text.isdigit():
        return text
    # Otherwise search by name
    result = searcher.search_one(text)
    if "error" in result:
        return text  # fallback
    return result["ticker"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 주식 AI 에이전트\n\n"
        "회사명으로 검색하세요. 띄어쓰기나 오타도 알아서 찾아드립니다.\n\n"
        "/분석 삼성전자\n"
        "/매수 애플\n"
        "/뉴스 sk하이닉스\n"
        "/기회  - 지금 괜찮은 종목 찾기\n"
        "/구독  - 자동 알림 받기\n\n"
        "예: /분석 삼성전자, /매수 apple, /뉴스 피자"
    )


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/분석 <회사명> - 차트+뉴스 통합 분석"""
    if not context.args:
        await update.message.reply_text("예: /분석 삼성전자")
        return

    query = " ".join(context.args)
    ticker = _resolve_ticker(query)
    await update.message.reply_text(f"🔍 {query} 분석 중...")

    try:
        result = agent.analyze_ticker(ticker)
        if "error" in result:
            await update.message.reply_text(f"❌ '{query}' 검색 결과: {result['error']}")
            return

        dec = result["decision"]
        tech = result["technical"]
        news = result["news"]
        price = result["price_data"]
        entry = result["entry_exit"]
        flag = "🇺🇸" if result["market"] == "US" else "🇰🇷"

        cs = dec.get("combined_score", 0)
        score_pct = int(((cs + 15) / 30) * 100)
        bar = "█" * (score_pct // 10) + "░" * (10 - score_pct // 10)

        targets = entry.get("targets", [0, 0, 0])
        stop_val = entry.get("stop_loss", 0)
        cur_price = price.get("price", 0)
        stop_pct = abs((cur_price - stop_val) / cur_price * 100) if cur_price and stop_val else 0

        ae = {"적극매수": "🟢🟢", "매수": "🟢", "관심매수": "✅", "관망": "⚪",
              "관망/부분익절": "🔶", "매도": "🔴", "적극매도": "🔴🔴"}

        if score_pct >= 70:
            entry_advice = f"지금 즉시 진입 가능 (추천 {score_pct}%)"
        elif score_pct >= 50:
            entry_advice = f"진입구간({entry.get('entry_zone_text', 'N/A')}) 도달시 분할 매수"
        else:
            entry_advice = f"관망 권장, 보유중인 경우 매도 고려"

        exit_advice = (
            f"1차 {targets[0]:,} → 50%% 익절\n"
            f"2차 {targets[1]:,} → 30%% 추가 (총 80%%)\n"
            f"3차 {targets[2]:,} → 나머지 20%% 청산"
        ) if targets[0] else "목표가 정보 없음"

        msg = (
            f"{flag} {result['name']} ({ticker})\n"
            f"현재가: {price['price']} ({price['change']:+.2f}%)\n"
            f"\n"
            f"📊 추천 강도: {score_pct}%\n"
            f"  {bar} ({score_pct}%)\n"
            f"  차트 {tech['signal']}({tech['score']:+d}) | 뉴스 {news.get('overall_score_pct', 50)}%\n"
            f"\n"
            f"⚖️ 판정: {ae.get(dec['action'], '')} {dec['action']}\n"
            f"📌 근거: {dec.get('reason', '')}\n"
            f"\n"
            f"🔥 실행 가이드\n"
            f"────────────────\n"
            f"✅ 진입: {entry_advice}\n"
            f"💰 구간: {entry.get('entry_zone_text', 'N/A')}\n"
            f"\n"
            f"🏁 익절:\n{exit_advice}\n"
            f"\n"
            f"🛑 손절: {entry.get('stop_loss_text', 'N/A')} 이하 (손실 {stop_pct:.1f}%% 이내)\n"
            f"⚖️ R/R: {entry.get('risk_reward_ratio', 'N/A')}"
        )

        if dec.get("chart_vs_news_conflict"):
            msg += f"\n\n⚠️ {dec['chart_vs_news_conflict']}"

        # 뉴스 % + 호재/악재 요약
        news_pct = news.get("overall_score_pct", 50)
        msg += f"\n\n📰 뉴스 강도: {news_pct}% ({news.get('bullish_count',0)}호재/{news.get('bearish_count',0)}악재)"
        bullish = news.get("bullish_summary", "")
        bearish = news.get("bearish_summary", "")
        if bullish and bullish != "없음":
            msg += f"\n  🟢 호재: {bullish[:60]}"
        if bearish and bearish != "없음":
            msg += f"\n  🔴 악재: {bearish[:60]}"

        db.save_analysis(
            ticker=ticker, name=result.get("name", ticker),
            market=result.get("market", "UNKNOWN"),
            action=dec.get("action", "관망"),
            score=dec.get("combined_score", 0), score_pct=score_pct,
            tech_score=dec.get("tech_score", 0),
            news_score=dec.get("news_score", 0),
            reason=dec.get("reason", ""),
            current_price=price.get("price", 0),
        )
        await update.message.reply_text(msg)

    except Exception as e:
        await update.message.reply_text(f"❌ 오류: {e}")


async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/매수 <회사명> - 매수 타이밍 분석"""
    if not context.args:
        await update.message.reply_text("예: /매수 삼성전자")
        return

    query = " ".join(context.args)
    ticker = _resolve_ticker(query)
    await update.message.reply_text(f"💰 {query} 매수 타이밍 분석 중...")

    try:
        result = agent.analyze_ticker(ticker)
        if "error" in result:
            await update.message.reply_text(f"❌ '{query}': {result['error']}")
            return

        dec = result["decision"]
        entry = result["entry_exit"]
        news = result["news"]
        price = result["price_data"]
        flag = "🇺🇸" if result["market"] == "US" else "🇰🇷"

        cs = dec.get("combined_score", 0)
        score_pct = int(((cs + 15) / 30) * 100)
        bar = "█" * (score_pct // 10) + "░" * (10 - score_pct // 10)

        targets = entry.get("targets", [0, 0, 0])
        stop_val = entry.get("stop_loss", 0)
        cur_price = price.get("price", 0)
        stop_pct = abs((cur_price - stop_val) / cur_price * 100) if cur_price and stop_val else 0

        ae = {"적극매수": "🟢🟢", "매수": "🟢", "관심매수": "✅", "관망": "⚪",
              "관망/부분익절": "🔶", "매도": "🔴", "적극매도": "🔴🔴"}

        msg = (
            f"{flag} {result['name']} ({ticker})\n"
            f"현재가: {price['price']} ({price['change']:+.2f}%)\n"
            f"\n"
            f"📊 추천 강도: {score_pct}%\n"
            f"  {bar} ({score_pct}%)\n"
            f"  차트 {dec.get('tech_score',0):+d} | 뉴스 {news.get('overall_score_pct', 50)}%\n"
            f"\n"
            f"⚖️ {ae.get(dec['action'], '')} {dec['action']} (확신도: {dec['conviction']})\n"
            f"\n"
            f"🔥 실행 가이드\n"
            f"────────────────\n"
            f"💰 진입구간: {entry.get('entry_zone_text', 'N/A')}\n"
            f"\n"
            f"🏁 익절:\n"
            f"  1차 {targets[0]:,} → 50% 익절\n"
            f"  2차 {targets[1]:,} → 30% 추가 (총 80%)\n"
            f"  3차 {targets[2]:,} → 나머지 20% 청산\n"
            f"\n"
            f"🛑 손절: {entry.get('stop_loss_text', 'N/A')} 이하 (손실 {stop_pct:.1f}% 이내)\n"
            f"⚖️ R/R: {entry.get('risk_reward_ratio', 'N/A')}"
        )

        if dec.get("chart_vs_news_conflict"):
            msg += f"\n\n⚠️ {dec['chart_vs_news_conflict']}"

        news_pct = news.get("overall_score_pct", 50)
        msg += f"\n\n📰 뉴스 강도: {news_pct}% ({news.get('bullish_count',0)}호재/{news.get('bearish_count',0)}악재)"
        bullish = news.get("bullish_summary", "")
        bearish = news.get("bearish_summary", "")
        if bullish and bullish != "없음":
            msg += f"\n  🟢 호재: {bullish[:60]}"
        if bearish and bearish != "없음":
            msg += f"\n  🔴 악재: {bearish[:60]}"

        db.save_analysis(
            ticker=ticker, name=result.get("name", ticker),
            market=result.get("market", "UNKNOWN"),
            action=dec.get("action", "관망"),
            score=dec.get("combined_score", 0), score_pct=score_pct,
            tech_score=dec.get("tech_score", 0),
            news_score=dec.get("news_score", 0),
            reason=dec.get("reason", ""),
            current_price=price.get("price", 0),
        )
        await update.message.reply_text(msg)

    except Exception as e:
        await update.message.reply_text(f"❌ 오류: {e}")


async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/뉴스 <회사명> - 뉴스 요약"""
    if not context.args:
        await update.message.reply_text("예: /뉴스 삼성전자")
        return

    query = " ".join(context.args)
    ticker = _resolve_ticker(query)

    from analysis.news_analyzer import news_analyzer
    result = news_analyzer.analyze_ticker_news(ticker)

    if not result or result.get("news_count", 0) == 0:
        await update.message.reply_text(f"'{query}' 관련 뉴스 없음")
        return

    flag = "🇺🇸" if result.get("ticker", "").isalpha() else "🇰🇷"

    bullish_sum = result.get("bullish_summary", "")
    bearish_sum = result.get("bearish_summary", "")
    pct = result.get("overall_score_pct", 50)

    msg = (
        f"{flag} {query} 뉴스\n"
        f"종합: {result['overall']} (강도: {pct}%)\n"
        f"🟢 호재 {result['bullish_count']} / 🔴 악재 {result['bearish_count']} / ⚪ 중립 "
        f"{result['news_count'] - result['bullish_count'] - result['bearish_count']} / 총 {result['news_count']}건\n"
    )
    if bullish_sum and bullish_sum != "없음":
        msg += f"\n🟢 호재 요약: {bullish_sum}"
    if bearish_sum and bearish_sum != "없음":
        msg += f"\n🔴 악재 요약: {bearish_sum}"
    msg += "\n\n"

    for h in result.get("headlines", [])[:6]:
        icon = {"호재": "🟢", "악재": "🔴", "중립": "⚪"}.get(h.get("class", "중립"), "⚪")
        msg += f"{icon} {h['title'][:70]}\n"
        if h.get("key_reason"):
            msg += f"  → {h['key_reason']}\n"

    await update.message.reply_text(msg)


async def cmd_opportunities(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/기회 - 지금 괜찮은 종목 찾기"""
    await update.message.reply_text(
        "🔍 한국 2000+ / 미국 500+ 종목 분석 중... (30~60초)")

    try:
        from scanner.opportunity_finder import finder
        opps = finder.find_opportunities(max_results=5)

        if not opps:
            await update.message.reply_text("😅 현재 눈에 띄는 기회 없음")
            return

        for opp in opps:
            await update.message.reply_text(opp.to_telegram_msg())

    except Exception as e:
        await update.message.reply_text(f"❌ 오류: {e}")


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/구독 - 자동 알림"""
    chat_id = update.effective_chat.id
    _subscribed_chats.add(chat_id)
    await update.message.reply_text(
        "✅ 구독 완료!\n"
        "30분마다 전체 종목 분석 후 괜찮은 종목만 알려드립니다."
    )


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/해지 - 알림 해지"""
    chat_id = update.effective_chat.id
    _subscribed_chats.discard(chat_id)
    await update.message.reply_text("❌ 알림 해지됨")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/도움 - 도움말"""
    await update.message.reply_text(
        "📚 명령어\n\n"
        "/분석 <회사명> - 차트+뉴스 분석\n"
        "/매수 <회사명> - 매수 타이밍 (진입가/목표가/손절가)\n"
        "/뉴스 <회사명> - 뉴스 요약\n"
        "/기회 - 지금 괜찮은 종목 찾기\n"
        "/구독 - 30분마다 자동 알림\n"
        "/해지 - 알림 해지\n\n"
        "💡 회사명은 띄어쓰기 오타 다 됨\n"
        "   예: /분석 삼전, /매수 apple, /뉴스 sk하이닉스\n"
        "   티커로 검색도 가능: /분석 005930"
    )


async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE):
    """30분 주기 자동 분석"""
    if not _subscribed_chats:
        return

    chat_ids = list(_subscribed_chats)
    try:
        from scanner.opportunity_finder import finder
        opps = finder.find_opportunities(max_results=5, save_db=True)
        if not opps:
            return
        for chat_id in chat_ids:
            for opp in opps:
                try:
                    await context.bot.send_message(chat_id=chat_id, text=opp.to_telegram_msg())
                except Exception:
                    continue
    except Exception:
        return


async def _korean_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route Korean /명령어 to the correct handler (CommandHandler doesn't support non-ASCII)."""
    text = update.message.text
    match = re.match(r"^/(\S+)(?:\s+(.+))?$", text)
    if not match:
        return
    cmd = match.group(1)
    args_text = match.group(2)
    context.args = args_text.split() if args_text else []
    handlers = {
        "분석": cmd_analyze, "매수": cmd_buy, "뉴스": cmd_news,
        "기회": cmd_opportunities, "구독": cmd_subscribe,
        "해지": cmd_unsubscribe, "도움": cmd_help, "시작": cmd_help,
    }
    handler = handlers.get(cmd)
    if handler:
        await handler(update, context)


def register_handlers(app):
    """Register all command handlers."""
    # Korean commands via MessageHandler+regex (filters.COMMAND doesn't match non-ASCII)
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r'^/(분석|매수|뉴스|기회|구독|해지|도움|시작)(\s.*)?$'),
        _korean_cmd))
    # English commands
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("buy", cmd_buy))
    app.add_handler(CommandHandler("news", cmd_news))
    app.add_handler(CommandHandler(["opps", "opportunities", "scan"], cmd_opportunities))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler(["help", "start"], cmd_help))

    # 스케줄러
    job_queue = app.job_queue
    if job_queue:
        interval = max(settings.scan_interval_minutes, 10) * 60
        job_queue.run_repeating(scheduled_scan, interval=interval, first=120)


def run_bot():
    if not settings.telegram_bot_token:
        print("❌ TELEGRAM_BOT_TOKEN 설정 필요")
        return

    app = Application.builder().token(settings.telegram_bot_token).build()
    register_handlers(app)

    print("🤖 주식 AI 에이전트 실행됨")
    print(f"   한글 명령어: /분석 /매수 /뉴스 /기회 /구독")
    print(f"   스캔 주기: {settings.scan_interval_minutes}분")
    print(f"   회사명 자동 검색 지원 (오타/띄어쓰기 무시)")

    app.run_polling(allowed_updates=Update.ALL_TYPES)
