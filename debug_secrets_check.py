import streamlit as st

st.write("## Secrets Debugger")
st.write("Keys found in st.secrets:")
st.write(list(st.secrets.keys()))

if "password" in st.secrets:
    st.success("✅ 'password' key found!")
else:
    st.error("❌ 'password' key NOT found at root level.")

# Check for common nesting mistakes
for key in st.secrets:
    if isinstance(st.secrets[key], dict):
        st.write(f"Checking inside section '[{key}]'...")
        if "password" in st.secrets[key]:
            st.warning(f"⚠️ Found 'password' inside '[{key}]'. Move it to the top level!")
