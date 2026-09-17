import streamlit as st
import pandas as pd
import asyncio
from scanner import main  # Import your existing async function logic

st.set_page_config(page_title="AI Quantitative Crypto Scanner", layout="wide", page_icon="⚡")

st.title("⚡ AI Quantitative Crypto Scanner")
st.caption("Live quantitative signals across KuCoin, MEXC, and OKX")

# Sidebar Controls
st.sidebar.header("Scanner Settings")
if st.sidebar.button("🚀 Run Live Market Scan"):
    with st.spinner("Fetching market data across exchanges..."):
        # Executes your scanner async function
        asyncio.run(main())
        st.success("Scan completed successfully!")

# Load and display saved CSV results
try:
    df = pd.read_csv("signals_log.csv")
    
    # Filter Controls
    exchanges = st.sidebar.multiselect("Filter Exchange", options=df["Exchange"].unique(), default=df["Exchange"].unique())
    signals = st.sidebar.multiselect("Filter Signal", options=df["Signal"].unique(), default=df["Signal"].unique())
    
    filtered_df = df[(df["Exchange"].isin(exchanges)) & (df["Signal"].isin(signals))]

    # Key Metrics Overview
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Processed Signals", len(filtered_df))
    col2.metric("Bullish Opportunities", len(filtered_df[filtered_df["Signal"].str.contains("BULLISH", na=False)]))
    col3.metric("Bearish Opportunities", len(filtered_df[filtered_df["Signal"].str.contains("BEARISH", na=False)]))

    # Interactive Table
    st.subheader("📊 High-Conviction Signals")
    st.dataframe(filtered_df, use_container_width=True)

except FileNotFoundError:
    st.info("No scan history found. Click 'Run Live Market Scan' in the sidebar to generate data.")