import streamlit as st
import pandas as pd
import json
import plotly.express as px
import yfinance as yf
import os

st.set_page_config(page_title="Momentum Strategy Dashboard", layout="wide")

# Custom CSS for HTML Tables (Bold, 16px Centered Headers & Centered Cells)
st.markdown("""
<style>
    .table-wrapper {
        width: 100%;
        overflow-x: auto;
        margin-bottom: 20px;
    }
    .custom-table {
        width: 100%;
        border-collapse: collapse;
        font-family: inherit;
    }
    .custom-table th {
        font-size: 16px !important;
        font-weight: 800 !important;
        text-align: center !important;
        padding: 12px 10px;
        border-bottom: 2px solid rgba(128, 128, 128, 0.4);
        background-color: rgba(128, 128, 128, 0.1);
    }
    .custom-table td {
        font-size: 14px !important;
        text-align: center !important;
        padding: 10px 8px;
        border-bottom: 1px solid rgba(128, 128, 128, 0.2);
    }
</style>
""", unsafe_allow_html=True)

def display_custom_table(df):
    html_table = df.to_html(index=False, escape=False, classes="custom-table")
    st.markdown(f'<div class="table-wrapper">{html_table}</div>', unsafe_allow_html=True)

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

# Metric Cards
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Strategy Value", f"₹{current_val:,.0f}", f"{tot_ret:+.2f}%")
col2.metric("Nifty Midcap 100", f"₹{benchmark_values.get('Nifty Midcap 100', init_cap):,.0f}", f"{benchmark_returns.get('Nifty Midcap 100', 0.0):+.2f}%")
col3.metric("Nifty 500", f"₹{benchmark_values.get('Nifty 500', init_cap):,.0f}", f"{benchmark_returns.get('Nifty 500', 0.0):+.2f}%")
col4.metric("Nifty 50", f"₹{benchmark_values.get('Nifty 50', init_cap):,.0f}", f"{benchmark_returns.get('Nifty 50', 0.0):+.2f}%")
col5.metric("Active Positions", f"{len(state['holdings'])} / 15")

st.divider()

# Section 1: Performance Comparison Chart
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
    st.info("No execution data recorded yet.")

st.divider()

# Section 2: Active Holdings Table & Graph
st.subheader("📋 Active Holdings Performance & Dynamic Stops")
if state["holdings"]:
    tickers_list = list(state["holdings"].keys())
    
    try:
        live_data = yf.download(tickers_list, period="5d", progress=False)
        if isinstance(live_data.columns, pd.MultiIndex):
            level0 = live_data.columns.levels[0]
            live_prices = live_data['Close'] if 'Close' in level0 else live_data['Adj Close']
        else:
            live_prices = live_data
        live_prices = live_prices.ffill().bfill()
        latest_p = live_prices.iloc[-1]
    except Exception:
        latest_p = {}

    h_list = []
    for ticker, info in state["holdings"].items():
        entry_p = info["entry_price"]
        shares = info["shares"]
        
        if isinstance(latest_p, pd.Series) and ticker in latest_p and not pd.isna(latest_p[ticker]):
            cur_p = float(latest_p[ticker])
        elif isinstance(latest_p, (int, float)) and not pd.isna(latest_p):
            cur_p = float(latest_p)
        else:
            cur_p = entry_p

        pnl_pct = ((cur_p - entry_p) / entry_p) * 100
        unrealized_pnl = (cur_p - entry_p) * shares
        cur_val = cur_p * shares

        h_list.append({
            "Ticker": ticker,
            "Entry Date": info.get("entry_date", "N/A"),
            "Entry Price (₹)": entry_p,
            "Current Price (₹)": cur_p,
            "Shares": shares,
            "Peak Price (₹)": info["peak"],
            "Current Value (₹)": cur_val,
            "Unrealized PnL (₹)": unrealized_pnl,
            "PnL (%)": pnl_pct
        })

    df_h = pd.DataFrame(h_list)
    df_h = df_h.sort_values(by="PnL (%)", ascending=False).reset_index(drop=True)

    # Performance Bar Chart
    fig_holdings = px.bar(
        df_h,
        x="Ticker",
        y="PnL (%)",
        color="PnL (%)",
        color_continuous_scale=["#FF4B4B", "#00CC96"],
        color_continuous_midpoint=0,
        text_auto='.2f',
        title="Unrealized PnL % per Holding (Highest to Lowest)"
    )
    fig_holdings.update_layout(
        xaxis_title="Stock Ticker",
        yaxis_title="Unrealized PnL (%)",
        coloraxis_showscale=False,
        hovermode="x"
    )
    st.plotly_chart(fig_holdings, use_container_width=True)

    # Formatted HTML Table
    df_display = df_h.copy()
    df_display["Entry Price (₹)"] = df_display["Entry Price (₹)"].apply(lambda x: f"₹{x:,.2f}")
    df_display["Current Price (₹)"] = df_display["Current Price (₹)"].apply(lambda x: f"₹{x:,.2f}")
    df_display["Peak Price (₹)"] = df_display["Peak Price (₹)"].apply(lambda x: f"₹{x:,.2f}")
    df_display["Current Value (₹)"] = df_display["Current Value (₹)"].apply(lambda x: f"₹{x:,.2f}")
    df_display["Unrealized PnL (₹)"] = df_display["Unrealized PnL (₹)"].apply(lambda x: f"₹{x:,.2f}")
    df_display["PnL (%)"] = df_display["PnL (%)"].apply(lambda x: f"{x:+.2f}%")

    display_custom_table(df_display)
else:
    st.warning("No open holdings currently active.")

st.divider()

# Section 3: Trade Execution History
st.subheader("📜 Historical Execution Logs")
if not trade_df.empty:
    sorted_trades = trade_df.sort_values(by="Date", ascending=False).reset_index(drop=True)
    display_custom_table(sorted_trades)
else:
    st.info("No trades executed yet.")
