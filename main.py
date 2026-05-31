"""
Stock AI Agent - 자동 분석 → 괜찮은 종목만 추천
==============================================
Usage:
    python main.py web       # 웹 대시보드 + 텔레그램 봇 + 자동 스캔 (통합 실행)
    python main.py opps      # 지금 기회되는 종목 찾기
    python main.py analyze <ticker>  # 특정 종목 분석
    python main.py news <ticker>     # 뉴스 분석
"""
import sys
import io
from datetime import datetime

# Fix Windows console encoding for emoji/unicode output
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    mode = sys.argv[1]

    if mode == "bot":
        from bot.telegram_bot import run_bot
        run_bot()

    elif mode == "web":
        from web.app import run
        run()

    elif mode == "analyze":
        if len(sys.argv) < 3:
            print("사용법: python main.py analyze <티커>")
            return
        ticker = sys.argv[2].upper()
        from agent.stock_agent import agent
        from rich.console import Console
        from rich.panel import Panel

        console = Console()
        console.print(f"[bold cyan]🔍 {ticker} 차트+뉴스 분석 중...[/bold cyan]")
        result = agent.analyze_ticker(ticker)
        if "error" in result:
            console.print(f"[red]❌ {result['error']}[/red]")
            return

        dec = result["decision"]
        tech = result["technical"]
        news = result["news"]
        price = result["price_data"]
        entry = result["entry_exit"]

        # Technical panel
        console.print(Panel(
            f"[bold]{result['name']} ({ticker})[/bold] | [{result['market']}]\n"
            f"가격: {price['price']} ({price['change']:+.2f}%)\n"
            f"RSI: {tech.get('rsi', 'N/A')} | MACD: {tech.get('macd', 'N/A')}\n"
            f"신호: [yellow]{tech['signal']}[/yellow] ({tech['score']}점)\n"
            + (f"근거: {', '.join(tech['reasons'][:3])}" if tech.get('reasons') else ""),
            title="📊 차트 분석"
        ))

        # News panel
        headlines = news.get("headlines", [])
        news_str = f"종합: {news.get('overall', '중립')} (점수: {news.get('overall_score', 0):+.1f})\n"
        news_str += f"호재 {news.get('bullish_count', 0)} / 악재 {news.get('bearish_count', 0)} / 총 {news.get('news_count', 0)}건\n"
        for h in headlines[:3]:
            icon = {"호재": "🟢", "악재": "🔴", "중립": "⚪"}.get(h.get("class", "중립"), "⚪")
            news_str += f"{icon} {h['title'][:70]}\n"

        console.print(Panel(news_str, title="📰 뉴스 분석"))

        # Combined decision
        ae = {"적극매수": "🟢🟢", "매수": "🟢", "관심매수": "✅", "관망": "⚪",
              "관망/부분익절": "🔶", "매도": "🔴", "적극매도": "🔴🔴"}
        ee = dec.get("entry_exit_ref", {})

        decision_str = (
            f"{ae.get(dec['action'], '')} [bold]{dec['action']}[/bold] (확신도: {dec['conviction']})\n"
            f"종합점수: {dec['combined_score']:+d} (차트 {dec['tech_score']:+d} / 뉴스 {dec['news_score']:+d})\n"
            f"{dec['tech_summary']} | {dec['news_summary']}\n"
        )

        if dec.get("chart_vs_news_conflict"):
            decision_str += f"\n[yellow]⚠️ {dec['chart_vs_news_conflict']}[/yellow]\n"

        decision_str += (
            f"\n[green]💰 진입:[/green] {ee.get('entry_zone', entry.get('entry_zone_text', 'N/A'))}\n"
            f"[cyan]🎯 목표:[/cyan] {ee.get('target', entry.get('target_text', 'N/A'))}\n"
            f"[red]🛑 손절:[/red] {ee.get('stop_loss', entry.get('stop_loss_text', 'N/A'))}\n"
            f"[yellow]⚖️ R/R:[/yellow] {ee.get('rr', entry.get('risk_reward_ratio', 'N/A'))}"
        )

        console.print(Panel(decision_str, title="⚖️ 종합 판정"))

    elif mode in ("opps", "opportunities"):
        from scanner.opportunity_finder import finder
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel

        console = Console()
        console.print("[bold cyan]🔍 한국 2000+ / 미국 500+ 종목 분석 중...[/bold cyan]")
        console.print("[dim]  1차 퀵스캔 → 2차 딥분석 → 필터링[/dim]")

        opps = finder.find_opportunities(max_results=5)

        if not opps:
            console.print("[yellow]😅 현재 눈에 띄는 기회가 없습니다.[/yellow]")
            return

        for opp in opps:
            ae = {"적극매수": "🟢🟢", "매수": "🟢", "관심매수": "✅", "관망": "⚪",
                  "관망/부분익절": "🔶", "매도": "🔴", "적극매도": "🔴🔴"}
            flag = "🇺🇸" if opp.market == "us" else "🇰🇷"

            console.print(Panel(
                f"{flag} [bold]{opp.name}[/bold] ({opp.ticker})\n\n"
                f"[bold]{ae.get(opp.action, '')} {opp.action}[/bold] (확신도: {opp.conviction})\n"
                f"점수: 차트 {opp.tech_score:+d} / 뉴스 {opp.news_score:+.1f} / 종합 [bold]{opp.score:+d}[/bold]\n"
                f"📊 {opp.reason}\n\n"
                f"[green]💰 진입:[/green] {opp.entry_zone}\n"
                f"[cyan]🎯 목표:[/cyan] {opp.target}\n"
                f"[red]🛑 손절:[/red] {opp.stop_loss}\n"
                f"[yellow]⚖️ R/R:[/yellow] {opp.rr}\n\n"
                f"📰 {opp.news_summary}",
                title=f"✅ 기회 발견",
                border_style="green"
            ))

    elif mode == "news":
        if len(sys.argv) < 3:
            print("사용법: python main.py news <티커>")
            return
        ticker = sys.argv[2].upper()
        from analysis.news_analyzer import news_analyzer
        from rich.console import Console
        from rich.panel import Panel

        console = Console()
        result = news_analyzer.analyze_ticker_news(ticker)
        if not result or result.get("news_count", 0) == 0:
            console.print(f"[yellow]'{ticker}' 관련 뉴스 없음[/yellow]")
            return

        msg = (
            f"종합: {result['overall']} (점수: {result['overall_score']:+.1f})\n"
            f"호재 {result['bullish_count']} / 악재 {result['bearish_count']} / 총 {result['news_count']}건\n\n"
        )
        for h in result.get("headlines", [])[:6]:
            icon = {"호재": "🟢", "악재": "🔴", "중립": "⚪"}.get(h.get("class", "중립"), "⚪")
            msg += f"{icon} {h['title']}\n"
            if h.get("key_reason"):
                msg += f"   → {h['key_reason']}\n"

        console.print(Panel(msg, title=f"📰 {ticker} 뉴스 분석"))

    elif mode == "init":
        from pathlib import Path
        example = Path(".env.example")
        env = Path(".env")
        if not env.exists() and example.exists():
            env.write_text(example.read_text())
            print("✅ .env 파일 생성됨")
        else:
            print(".env 이미 존재함")

    else:
        print(f"알 수 없는 명령어: {mode}")
        print(__doc__)


if __name__ == "__main__":
    main()
