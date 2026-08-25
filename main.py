import os
import json
import urllib.request
import io
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

# ================= CONFIGURATION =================
STATE_FILE = "data/portfolio_state.json"
TRADE_LOG_FILE = "data/trade_log.csv"
EQUITY_FILE = "data/equity_history.csv"

TARGET_POSITIONS = 15
ATR_MULTIPLIER = 3.0
MIN_DAILY_TURNOVER = 30000000

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BENCHMARKS = {
    'Nifty Midcap 100': 'NIFTY_MIDCAP_100.NS',
    'Nifty 500': '^CRSLDX',
    'Nifty 50': '^NSEI'
}

def send_telegram_msg(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] Credentials missing. Skipping notification.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[Telegram Error] {e}")

def fetch_universe():
    headers = {'User-Agent': 'Mozilla/5.0'}
    urls = [
        "https://niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
        "https://niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv"
    ]
    tickers = set()
    for url in urls:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as resp:
                df = pd.read_csv(io.BytesIO(resp.read()))
                if 'Symbol' in df.columns:
                    for s in df['Symbol'].dropna():
                        tickers.add(f"{s.strip()}.NS")
        except Exception:
            pass
    return list(tickers) if tickers else ["SUZLON.NS", "PERSISTENT.NS", "COFORGE.NS"]

def run_daily_execution():
    if not os.path.exists(STATE_FILE):
        state = {"cash": 500000.0, "initial_capital": 500000.0, "holdings": {}}
    else:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)

    cash = state["cash"]
    holdings = state["holdings"]
    
    tickers = fetch_universe()
    all_tickers = list(set(tickers + list(BENCHMARKS.values())))
    
    print("Fetching market data...")
    data = yf.download(all_tickers, period="1y", progress=False)
    
    level0 = data.columns.levels[0] if isinstance(data.columns, pd.MultiIndex) else data.columns
    price_df = data['Close'] if 'Close' in level0 else data['Adj Close']
    high_df = data['High'] if 'High' in level0 else price_df
    low_df = data['Low'] if 'Low' in level0 else price_df
    volume_df = data['Volume'] if 'Volume' in level0 else None
    
    price_df = price_df.ffill().bfill()
    high_df = high_df.ffill().bfill()
    low_df = low_df.ffill().bfill()
    
    dt = price_df.index[-1]
    dt_str = dt.strftime("%Y-%m-%d")
    
    ema50_df = price_df.ewm(span=50, adjust=False).mean()
    sma200_df = price_df.rolling(200, min_periods=100).mean()
    ret3m_df = (price_df - price_df.shift(63)) / price_df.shift(63)
    ret6m_df = (price_df - price_df.shift(126)) / price_df.shift(126)
    vol63_df = price_df.pct_change().rolling(63, min_periods=30).std()

    tr_df = np.maximum(high_df - low_df, np.maximum((high_df - price_df.shift(1)).abs(), (low_df - price_df.shift(1)).abs()))
    atr14_df = tr_df.rolling(14, min_periods=5).mean()

    adt20_df = (price_df * volume_df.ffill().fillna(0)).rolling(20, min_periods=5).mean() if volume_df is not None else None

    trade_logs = []

    # 1. EXITS
    retained_holdings = {}
    for stk, info in holdings.items():
        if stk not in price_df.columns:
            retained_holdings[stk] = info
            continue
            
        cur_p = price_df.loc[dt, stk]
        ema_50 = ema50_df.loc[dt, stk]
        cur_atr = atr14_df.loc[dt, stk] if stk in atr14_df.columns else np.nan
        new_peak = max(info['peak'], cur_p)
        
        atr_stop_hit = cur_p < (new_peak - (ATR_MULTIPLIER * cur_atr)) if not np.isnan(cur_atr) and cur_atr > 0 else cur_p < (new_peak * 0.88)
        trend_broken = cur_p < ema_50
        
        if trend_broken or atr_stop_hit:
            proceeds = info['shares'] * cur_p
            cash += proceeds
            pnl = ((cur_p - info['entry_price']) / info['entry_price']) * 100
            reason = "50 EMA Breakdown" if trend_broken else "ATR Dynamic Stop"
            
            msg = f"🔴 <b>SELL SIGNAL EXECUTED</b>\n\n<b>Stock:</b> {stk}\n<b>Price:</b> ₹{cur_p:.2f}\n<b>Shares:</b> {info['shares']}\n<b>PnL:</b> {pnl:.2f}%\n<b>Reason:</b> {reason}"
            send_telegram_msg(msg)
            
            trade_logs.append({
                "Date": dt_str, "Ticker": stk, "Action": "SELL", "Price": cur_p,
                "Shares": info['shares'], "Value": proceeds, "PnL_Pct": pnl, "Reason": reason
            })
        else:
            retained_holdings[stk] = {"shares": info['shares'], "peak": new_peak, "entry_price": info['entry_price'], "entry_date": info.get('entry_date', dt_str)}

    holdings = retained_holdings

    # 2. MARKET REGIME CHECK (200 SMA Hard Gate)
    nifty_symbol = '^CRSLDX'
    nifty_p = price_df.loc[dt, nifty_symbol] if nifty_symbol in price_df.columns else np.nan
    nifty_sma = sma200_df.loc[dt, nifty_symbol] if nifty_symbol in sma200_df.columns else np.nan
    regime_bullish = nifty_p > nifty_sma if not np.isnan(nifty_p) and not np.isnan(nifty_sma) else True

    # 3. ENTRIES
    open_slots = TARGET_POSITIONS - len(holdings)
    if open_slots > 0 and cash > 5000 and regime_bullish:
        nifty_3m = ret3m_df.loc[dt, nifty_symbol] if nifty_symbol in ret3m_df.columns else 0.0
        scored_stocks = []
        
        for stk in tickers:
            if stk in holdings or stk not in price_df.columns:
                continue
            cur_p = price_df.loc[dt, stk]
            ret_3m = ret3m_df.loc[dt, stk]
            ret_6m = ret6m_df.loc[dt, stk]
            ema_50 = ema50_df.loc[dt, stk]
            sma_200 = sma200_df.loc[dt, stk]
            vol_63 = vol63_df.loc[dt, stk]
            
            if np.isnan(cur_p) or np.isnan(ret_3m) or np.isnan(ema_50) or np.isnan(sma_200):
                continue
            if adt20_df is not None and stk in adt20_df.columns:
                adt_val = adt20_df.loc[dt, stk]
                if not np.isnan(adt_val) and adt_val > 0 and adt_val < MIN_DAILY_TURNOVER:
                    continue
                    
            alpha_3m = ret_3m - (0.0 if np.isnan(nifty_3m) else nifty_3m)
            if cur_p > ema_50 and ema_50 > sma_200 and alpha_3m > 0:
                score = ((0.6 * alpha_3m) + (0.4 * (0.0 if np.isnan(ret_6m) else ret_6m))) / (0.02 if (np.isnan(vol_63) or vol_63 <= 0) else vol_63)
                scored_stocks.append({'Ticker': stk, 'Price': cur_p, 'Score': score})
                
        df_scored = pd.DataFrame(scored_stocks)
        if not df_scored.empty:
            top_candidates = df_scored.sort_values(by='Score', ascending=False).head(open_slots)
            alloc_per_stock = cash / len(top_candidates)
            
            for _, row in top_candidates.iterrows():
                stk, p = row['Ticker'], row['Price']
                shares = int(np.floor(alloc_per_stock / p))
                if shares > 0:
                    cost = shares * p
                    cash -= cost
                    holdings[stk] = {"shares": shares, "peak": p, "entry_price": p, "entry_date": dt_str}
                    
                    msg = f"🟢 <b>BUY SIGNAL EXECUTED</b>\n\n<b>Stock:</b> {stk}\n<b>Buy Price:</b> ₹{p:.2f}\n<b>Shares:</b> {shares}\n<b>Allocation:</b> ₹{cost:,.2f}"
                    send_telegram_msg(msg)
                    
                    trade_logs.append({
                        "Date": dt_str, "Ticker": stk, "Action": "BUY", "Price": p,
                        "Shares": shares, "Value": cost, "PnL_Pct": 0.0, "Reason": "Momentum Entry"
                    })

    state["cash"] = cash
    state["holdings"] = holdings
    state["last_updated"] = dt_str
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

    if trade_logs:
        df_new_logs = pd.DataFrame(trade_logs)
        if os.path.exists(TRADE_LOG_FILE):
            df_new_logs.to_csv(TRADE_LOG_FILE, mode='a', header=False, index=False)
        else:
            df_new_logs.to_csv(TRADE_LOG_FILE, index=False)

    holdings_val = sum(h["shares"] * price_df.loc[dt, s] for s, h in holdings.items() if s in price_df.columns)
    total_val = cash + holdings_val
    
    equity_row = pd.DataFrame([{"Date": dt_str, "Portfolio_Value": total_val, "Cash": cash, "Holdings_Count": len(holdings)}])
    if os.path.exists(EQUITY_FILE):
        df_eq = pd.read_csv(EQUITY_FILE)
        if dt_str not in df_eq['Date'].astype(str).values:
            equity_row.to_csv(EQUITY_FILE, mode='a', header=False, index=False)
    else:
        equity_row.to_csv(EQUITY_FILE, index=False)

    daily_msg = f"📊 <b>DAILY PORTFOLIO SUMMARY</b> ({dt_str})\n\n<b>Portfolio Value:</b> ₹{total_val:,.2f}\n<b>Cash Balance:</b> ₹{cash:,.2f}\n<b>Active Positions:</b> {len(holdings)}/15\n<b>Market Regime:</b> {'🟢 BULLISH' if regime_bullish else '🔴 BEARISH'}"
    send_telegram_msg(daily_msg)

if __name__ == "__main__":
    run_daily_execution()
