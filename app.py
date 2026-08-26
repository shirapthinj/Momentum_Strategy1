import streamlit as st
import pandas as pd
import json
import plotly.express as px
import yfinance as yf
import os

st.set_page_config(page_title="Momentum Strategy Dashboard", layout="wide")

STATE_FILE = "data/portfolio_state.json"
TRADE_LOG_FILE = "data/trade_log.csv"
EQUITY_FILE = "data/equity_history.csv"

BENCHMARKS = {
    'Nifty Midcap 100': 'NIFTY_MIDCAP_100.NS',
    'Nifty 500': '^CRSLDX',
    'Nifty 50': '^NSEI'
}

st.title("🚀 Mid/Smallcap Momentum Strategy Engine")

@st.cache_data(ttl=300)
def load_data():
    state = json.load(open(STATE_FILE)) if os.path.exists(STATE_FILE) else {"cash": 500000, "initial_capital": 500000, "holdings": {}}
    eq_df = pd.read_csv(EQUITY_FILE) if os.path.exists(EQUITY_FILE) else pd.DataFrame(columns=["Date", "Portfolio_Value", "Cash", "Holdings_Count"])
    trade_df = pd.read_csv(TRADE_LOG_FILE) if os.path.exists(TRADE_LOG_FILE) else pd.DataFrame(columns=["Date", "Ticker", "Action", "Price", "Shares", "Value", "PnL_Pct", "Reason"])
    return state, eq_df, trade_df

state, eq_df, trade_df = load_data()

# Portfolio Return Calculation
init_cap = state.get("initial_capital", 500000.0)
current_val = eq_df["Portfolio_Value"].iloc[-1] if not eq_df.empty else init_cap
tot_ret = ((current_val - init_cap) / init_cap) * 100

# Benchmark Calculations (Normalized to Initial Capital)
benchmark_returns = {}
benchmark_values = {}
bm_prices = pd.DataFrame()

if not eq_df.empty:
    start_date = eq_df['Date'].iloc[0]
    try:
        bm_tickers = list(BENCHMARKS.values())
        raw_bm = yf.download(bm_tickers, start=start_date, progress=False)
        
        if isinstance(raw_bm.columns, pd.MultiIndex):
            level0 = raw_bm.columns.levels[0]
            bm_prices = raw_bm['Close'] if 'Close' in level0 else raw_bm['Adj Close']
        else:
            bm_prices = raw_bm

        bm_prices = bm_prices.ffill().bfill()

        for name, sym in BENCHMARKS.items():
            if sym in bm_prices.columns and len(bm_prices[sym].dropna()) > 1:
                s = bm_prices[sym].dropna()
                pct_chg = ((s.iloc[-1] - s.iloc[0]) / s.iloc[0]) * 100
                benchmark_returns[name] = pct_chg
                benchmark_values[name] = init_cap * (1 + (pct_chg / 100.0))
            else:
                benchmark_returns[name] = 0.0
                benchmark_values[name] = init_cap
    except Exception:
        for name in BENCHMARKS:
            benchmark_returns[name] = 0.0
            benchmark_values[name] = init_cap
else:
    for name in BENCHMARKS:
        benchmark_returns[name] = 0.0
        benchmark_values[name] = init_cap

# Metric Cards (Normalized monetary values)
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Strategy Value", f"₹{current_val:,.0f}", f"{tot_ret:+.2f}%")
col2.metric("Nifty Midcap 100", f"₹{benchmark_values.get('Nifty Midcap 100', init_cap):,.0f}", f"{benchmark_returns.get('Nifty Midcap 100', 0.0):+.2f}%")
col3.metric("Nifty 500", f"₹{benchmark_values.get('Nifty 500', init_cap):,.0f}", f"{benchmark_returns.get('Nifty 500', 0.0):+.2f}%")
col4.metric("Nifty 50", f"₹{benchmark_values.get('Nifty 50', init_cap):,.0f}", f"{benchmark_returns.get('Nifty 50', 0.0):+.2f}%")
col5.metric("Active Positions", f"{len(state['holdings'])} / 15")

st.divider()

# Section 1: Comparative % Return Chart
st.subheader("📈 Performance % Comparison (Strategy vs Benchmarks)")
if not eq_df.empty:
    eq_df['Date'] = pd.to_datetime(eq_df['Date'])
    eq_df['Strategy %'] = ((eq_df['Portfolio_Value'] - init_cap) / init_cap) * 100
    
    perf_df = eq_df[['Date', 'Strategy %']].set_index('Date')
    
    if not bm_prices.empty:
        for name, sym in BENCHMARKS.items():
            if sym in bm_prices.columns:
                s = bm_prices[sym].dropna()
                norm_series = ((s - s.iloc[0]) / s.iloc[0]) * 100
                perf_df[name] = norm_series
    
    fig = px.line(perf_df, labels={"value": "Return (%)", "variable": "Asset / Strategy"})
    fig.update_layout(hovermode="x unified", yaxis_title="Percentage Change (%)")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No execution data recorded yet. Comparative chart will display after historical days accumulate.")

# Section 2: Active Holdings Table
st.subheader("📋 Active Holdings & Dynamic Stops")
if state["holdings"]:
    h_list = []
    for ticker, info in state["holdings"].items():
        h_list.append({
            "Ticker": ticker,
            "Entry Date": info.get("entry_date", "N/A"),
            "Entry Price (₹)": f"₹{info['entry_price']:.2f}",
            "Shares": info["shares"],
            "Peak Price (₹)": f"₹{info['peak']:.2f}",
            "Capital Allocated (₹)": f"₹{info['shares'] * info['entry_price']:,.2f}"
        })
    st.dataframe(pd.DataFrame(h_list), use_container_width=True)
else:
    st.warning("No open holdings currently active.")

# Section 3: Trade History
st.subheader("📜 Historical Execution Logs")
if not trade_df.empty:
    st.dataframe(trade_df.sort_values(by="Date", ascending=False), use_container_width=True)
else:
    st.info("No trades executed yet.")
