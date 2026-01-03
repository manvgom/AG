# debug_auth.py
import streamlit as st
import sys
st.write(f"Python path: {sys.executable}")
st.write(f"Streamlit version: {st.__version__}")
try:
    from streamlit_gsheets import GSheetsConnection
except ImportError as e:
    st.error(f"Import Error: {e}")
    st.stop()
import pandas as pd

st.write("Checking secrets...")
if "connections" in st.secrets and "gsheets" in st.secrets.connections:
    st.write("✅ content found in [connections.gsheets]")
else:
    st.error("❌ [connections.gsheets] NOT found in secrets.toml")

try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    st.write("Connection object created.")
    
    url = "https://docs.google.com/spreadsheets/d/1jbjVfsv4FV4c2OOkmH3dQnn8NzVvB1xa_BSizobODVg/edit?gid=0#gid=0"
    st.write(f"Attempting to read from: {url}")
    
    df = conn.read(spreadsheet=url, ttl=0)
    st.write("✅ Read success!")
    st.write(df.head())
    
    st.write("Attempting to write...")
    # Try to write back the same data to verify write permissions
    conn.update(spreadsheet=url, data=df)
    st.write("✅ Write success!")

except Exception as e:
    st.error(f"❌ Error: {e}")
