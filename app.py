import streamlit as st
import pandas as pd
import json
import plotly.express as px
import os

st.set_page_config(page_title="Momentum Strategy Dashboard", layout="wide")

STATE_FILE = "data/portfolio_state.json"
TRADE_LOG_FILE = "data/trade_log.csv"
EQUITY_FILE = "data/equity_history.csv"

st.title("🚀 Mid/Smallcap Momentum Strategy Engine")

@st.cache_data(ttl=60)
def load_data():
    state = json.load(open(STATE_FILE)) if os.path.exists(STATE_FILE) else {"cash": 500000, "initial_capital": 500000, "holdings": {}}
    eq_df = pd.read_csv(EQUITY_FILE) if os.path.exists(EQUITY_FILE) else pd.DataFrame(columns=["Date", "Portfolio_Value", "Cash", "Holdings_Count"])
    trade_df = pd.read_csv(TRADE_LOG_FILE) if os.path.exists(TRADE_LOG_FILE) else pd.DataFrame(columns=["Date", "Ticker", "Action", "Price", "Shares", "Value", "PnL_Pct", "Reason"])
    return state, eq_df, trade_df

state, eq_df, trade_df = load_data()

# KPI Metric Cards
col1, col2, col3, col4 = st.columns(4)
current_val = eq_df["Portfolio_Value"].iloc[-1] if not eq_df.empty else state["initial_capital"]
tot_ret = ((current_val - state["initial_capital"]) / state["initial_capital"]) * 100

col1.metric("Total Portfolio Value", f"₹{current_val:,.2f}", f"{tot_ret:.2f}%")
col2.metric("Cash Balance", f"₹{state['cash']:,.2f}")
col3.metric("Active Holdings", f"{len(state['holdings'])} / 15")
col4.metric("Total Executed Trades", len(trade_df))

st.divider()

# Section 1: Equity Curve Chart
st.subheader("📈 Equity Growth Curve")
if not eq_df.empty:
    fig = px.line(eq_df, x="Date", y="Portfolio_Value", title="Portfolio Value (INR)", labels={"Portfolio_Value": "Total Value (₹)"})
    fig.update_traces(line_color="#00CC96", line_width=2.5)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No equity history recorded yet. The chart will plot after your first daily execution.")

# Section 2: Active Portfolio Positions
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
            "Current Capital (₹)": f"₹{info['shares'] * info['entry_price']:,.2f}"
        })
    st.dataframe(pd.DataFrame(h_list), use_container_width=True)
else:
    st.warning("No open holdings currently active.")

# Section 3: Historical Trade Activity
st.subheader("📜 Historical Execution Logs")
if not trade_df.empty:
    st.dataframe(trade_df.sort_values(by="Date", ascending=False), use_container_width=True)
else:
    st.info("No trades executed yet.")
