import asyncio
import os
import time
from datetime import datetime, timezone
import ccxt.async_support as ccxt
import pandas as pd
import requests
import ta

# ==================== CONFIGURATION ====================
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"  # Replace with BotFather Token
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"  # Replace with Chat ID
CSV_FILENAME = "signals_log.csv"
MIN_SCORE_FOR_ALERT = 50  # Score threshold for Alerts & Logging
# =======================================================


def send_telegram_alert(symbol, exchange_name, score, price, signal):
    """Sends a real-time signal notification to Telegram."""
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        return  # Skip if token not configured

    message = (
        f"🚨 <b>HIGH CONVICTION SIGNAL DETECTED</b> 🚨\n\n"
        f"<b>Exchange:</b> {exchange_name.upper()}\n"
        f"<b>Symbol:</b> {symbol}\n"
        f"<b>Price:</b> ${price}\n"
        f"<b>Score:</b> {score} / 100\n"
        f"<b>Signal:</b> {signal}\n"
        f"<b>Timestamp:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}

    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"⚠️ Failed to send Telegram alert for {symbol}: {e}")


def log_signals_to_csv(results):
    """Appends high-scoring setups into a local CSV file."""
    high_score_signals = [r for r in results if abs(r["Score"]) >= MIN_SCORE_FOR_ALERT]

    if not high_score_signals:
        return

    df = pd.DataFrame(high_score_signals)
    df["Timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    file_exists = os.path.isfile(CSV_FILENAME)
    df.to_csv(CSV_FILENAME, mode="a", index=False, header=not file_exists)
    print(
        f"💾 Saved {len(high_score_signals)} high-conviction signals to {CSV_FILENAME}"
    )


async def analyze_tf(exchange, symbol, timeframe):
    """Fetches candles and calculates RSI, MACD, and EMAs for a timeframe."""
    try:
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=210)
        if not ohlcv or len(ohlcv) < 200:
            return None

        df = pd.DataFrame(
            ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)

        # Technical Indicators
        df["RSI"] = ta.momentum.rsi(df["close"], window=14)

        macd_ind = ta.trend.MACD(
            df["close"], window_slow=26, window_fast=12, window_sign=9
        )
        df["MACD"] = macd_ind.macd()
        df["MACD_Signal"] = macd_ind.macd_signal()

        df["EMA_50"] = ta.trend.ema_indicator(df["close"], window=50)
        df["EMA_200"] = ta.trend.ema_indicator(df["close"], window=200)

        latest = df.iloc[-1]

        vol_sma = df["volume"].rolling(20).mean().iloc[-1]
        vol_spike = latest["volume"] > (vol_sma * 2)

        return {
            "close": latest["close"],
            "rsi": latest["RSI"],
            "macd": latest["MACD"],
            "macd_sig": latest["MACD_Signal"],
            "ema_50": latest["EMA_50"],
            "ema_200": latest["EMA_200"],
            "vol_spike": vol_spike,
        }
    except Exception:
        return None


async def fetch_and_analyze(exchange, symbol, semaphore):
    """Processes asset across timeframes and applies weighted scoring."""
    async with semaphore:
        try:
            # Fetch 15m and 1h data concurrently from the target exchange
            tf_15m, tf_1h = await asyncio.gather(
                analyze_tf(exchange, symbol, "15m"),
                analyze_tf(exchange, symbol, "1h"),
            )

            if not tf_15m or not tf_1h:
                return None

            score = 0

            # EMA 50 / 200 Trend Filter (Max ±20)
            if tf_1h["close"] > tf_1h["ema_50"] > tf_1h["ema_200"]:
                score += 20
            elif tf_1h["close"] < tf_1h["ema_50"] < tf_1h["ema_200"]:
                score -= 20

            # 1H Higher Timeframe Indicators (Max ±30)
            if pd.notnull(tf_1h["rsi"]):
                if tf_1h["rsi"] <= 30:
                    score += 15
                elif tf_1h["rsi"] >= 70:
                    score -= 15

            if pd.notnull(tf_1h["macd"]) and pd.notnull(tf_1h["macd_sig"]):
                if tf_1h["macd"] > tf_1h["macd_sig"]:
                    score += 15
                else:
                    score -= 15

            # 15M Lower Timeframe Indicators (Max ±30)
            if pd.notnull(tf_15m["rsi"]):
                if tf_15m["rsi"] <= 30:
                    score += 15
                elif tf_15m["rsi"] >= 70:
                    score -= 15

            if pd.notnull(tf_15m["macd"]) and pd.notnull(tf_15m["macd_sig"]):
                if tf_15m["macd"] > tf_15m["macd_sig"]:
                    score += 15
                else:
                    score -= 15

            # Volume Surge Component (Max ±20)
            if tf_15m["vol_spike"]:
                score += 20 if score > 0 else -20

            # Signal Formatting
            if score >= 50:
                signal = "STRONG BULLISH 🚀"
            elif 20 <= score < 50:
                signal = "BULLISH 📈"
            elif -20 < score < 20:
                signal = "NEUTRAL ➖"
            elif -50 < score <= -20:
                signal = "BEARISH 📉"
            else:
                signal = "STRONG BEARISH 🔴"

            # Trigger Telegram Notification if score hits threshold
            if score >= MIN_SCORE_FOR_ALERT:
                send_telegram_alert(
                    symbol,
                    exchange.id,
                    score,
                    tf_15m["close"],
                    signal,
                )

            return {
                "Exchange": exchange.id.upper(),
                "Symbol": symbol,
                "Price": tf_15m["close"],
                "Score": score,
                "Signal": signal,
                "RSI_15m": (
                    round(tf_15m["rsi"], 1) if pd.notnull(tf_15m["rsi"]) else None
                ),
                "RSI_1h": round(tf_1h["rsi"], 1) if pd.notnull(tf_1h["rsi"]) else None,
                "Vol_Spike": "YES 🔥" if tf_15m["vol_spike"] else "NO",
            }

        except Exception:
            return None


async def scan_exchange(exchange_class, exchange_id, max_coins=50):
    """Scans target exchange pairs concurrently."""
    exchange = exchange_class({"enableRateLimit": True})
    print(f"📡 Connecting to {exchange_id.upper()}...")

    try:
        markets = await exchange.load_markets()
        usdt_pairs = [
            symbol
            for symbol, market in markets.items()
            if symbol.endswith("/USDT")
            and market.get("spot", False)
            and not any(x in symbol for x in ["UP/", "DOWN/", "BEAR/", "BULL/"])
        ][:max_coins]

        semaphore = asyncio.Semaphore(15)
        tasks = [
            fetch_and_analyze(exchange, symbol, semaphore) for symbol in usdt_pairs
        ]
        results = await asyncio.gather(*tasks)

        return [r for r in results if r is not None]
    except Exception as e:
        print(f"⚠️ Error querying {exchange_id.upper()}: {e}")
        return []
    finally:
        await exchange.close()


async def main():
    print("🚀 Initializing Multi-Exchange Institutional Market Scanner...\n")
    start_time = time.time()

    # KuCoin, MEXC, and OKX (No Binance to avoid region block 451)
    exchanges = [
        (ccxt.kucoin, "kucoin"),
        (ccxt.mexc, "mexc"),
        (ccxt.okx, "okx"),
    ]

    exchange_tasks = [
        scan_exchange(ex_cls, ex_id, max_coins=50) for ex_cls, ex_id in exchanges
    ]
    all_results_nested = await asyncio.gather(*exchange_tasks)

    results = [item for sublist in all_results_nested for item in sublist]
    execution_time = round(time.time() - start_time, 2)

    if results:
        results_df = pd.DataFrame(results)
        results_df = results_df.sort_values(by="Score", ascending=False)

        print(f"\n⚡ Executed scan across 3 exchanges in {execution_time} seconds!")
        print(f"Total Processed Assets: {len(results_df)}\n")

        print("=== TOP QUANTITATIVE SIGNALS ===")
        print(results_df.head(25).to_string(index=False))

        log_signals_to_csv(results)
    else:
        print("No valid market data returned.")


if __name__ == "__main__":
    asyncio.run(main())