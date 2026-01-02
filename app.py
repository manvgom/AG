import streamlit as st
import pandas as pd
import time
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# Page configuration
st.set_page_config(page_title="Time Tracker", page_icon="⏱️", layout="wide")

# Custom CSS for premium look
st.markdown("""
    <style>
    .stButton>button {
        width: 100%;
        border-radius: 5px;
        height: 3em;
    }
    .stTextInput>div>div>input {
        border-radius: 5px;
    }
    </style>
    """, unsafe_allow_html=True)

# Constants
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
REQUIRED_COLUMNS = ['name', 'total_seconds', 'status']

# Helper: Find credentials dictionary recursively
def find_credentials(secrets_proxy):
    # Convert to standard dict to avoid AttrDict weirdness if necessary, 
    # but strictly speaking st.secrets acts like a dict.
    
    # 1. Check root
    if "private_key" in secrets_proxy:
        return secrets_proxy
        
    # 2. Check first level items (e.g. [gsheets], [connections])
    for key in secrets_proxy:
        val = secrets_proxy[key]
        # Check if item is dict-like
        if hasattr(val, "keys"): 
            if "private_key" in val:
                return val
            # 3. Check second level (e.g. [connections.gsheets])
            for subkey in val:
                subval = val[subkey]
                if hasattr(subval, "keys") and "private_key" in subval:
                    return subval
    return None

def get_gc():
    secrets = find_credentials(st.secrets)
    
    if not secrets:
        # Debugging aid: Show available keys (sanitized) to help user
        st.error("❌ Credentials not found in secrets.")
        st.warning("Debugging info - Secret Keys found:")
        st.json(dict(st.secrets)) # Safe? This might show values if they are strings. 
        # Better: just keys
        keys_structure = {}
        for k in st.secrets:
            if hasattr(st.secrets[k], "keys"):
                keys_structure[k] = list(st.secrets[k].keys())
            else:
                keys_structure[k] = "Value"
        st.write("Keys Structure:", keys_structure)
        st.stop()

    # Create credentials from secrets dict
    try:
        creds_dict = {
            "type": secrets["type"],
            "project_id": secrets["project_id"],
            "private_key_id": secrets["private_key_id"],
            "private_key": secrets["private_key"],
            "client_email": secrets["client_email"],
            "client_id": secrets["client_id"],
            "auth_uri": secrets["auth_uri"],
            "token_uri": secrets["token_uri"],
            "auth_provider_x509_cert_url": secrets["auth_provider_x509_cert_url"],
            "client_x509_cert_url": secrets["client_x509_cert_url"],
        }
    except KeyError as e:
        st.error(f"Missing required key in credentials: {e}")
        st.stop()
    
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)

def load_tasks():
    try:
        gc = get_gc()
        
        # Try to find spreadsheet url in the same creds block or root
        secrets = find_credentials(st.secrets)
        url = secrets.get("spreadsheet") if secrets else None
        
        # If not in creds block, check keys roughly
        if not url:
             if "spreadsheet" in st.secrets:
                 url = st.secrets["spreadsheet"]
             # Check legacy nested
             elif "connections" in st.secrets and "gsheets" in st.secrets.connections:
                 url = st.secrets.connections.gsheets.get("spreadsheet")

        if not url:
            st.error("Spreadsheet URL not found in secrets.")
            return []

        sh = gc.open_by_url(url)
        worksheet = sh.get_worksheet(0) # First sheet
        
        data = worksheet.get_all_records()
        
        if not data:
            return []
            
        # Ensure columns exist in first row checks? 
        # get_all_records uses first row as keys.
        
        # Normalize and Validation
        validated_data = []
        for row in data:
            # Basic validation/cleaning
            clean_row = {
                'name': str(row.get('name', '')),
                'total_seconds': float(row.get('total_seconds', 0.0) or 0.0),
                'status': str(row.get('status', 'Pending'))
            }
            validated_data.append(clean_row)
            
        return validated_data
        
    except Exception as e:
        # If sheet is empty (no headers), get_all_records might fail or return empty.
        # Initialize headers if needed?
        st.warning(f"Could not load data (New sheet?): {e}")
        return []

def save_tasks():
    try:
        gc = get_gc()
        
        # Find URL (logic duplicated for safety, could be helper but inline involves less diff risk)
        secrets = find_credentials(st.secrets)
        url = secrets.get("spreadsheet") if secrets else None
        
        if not url and "spreadsheet" in st.secrets:
             url = st.secrets["spreadsheet"]
        
        if not url:
            st.error("Spreadsheet URL not found.")
            return
        
        sh = gc.open_by_url(url)
        worksheet = sh.get_worksheet(0)
        
        # Prepare data for sheet
        # Row 1: Headers
        # Row 2+: Data
        
        headers = REQUIRED_COLUMNS
        
        values = [headers]
        for task in st.session_state.tasks:
            row = [
                task.get('name', ''),
                task.get('total_seconds', 0),
                task.get('status', 'Pending')
            ]
            values.append(row)
            
        worksheet.clear()
        worksheet.update(values)
        
    except Exception as e:
        st.error(f"Error saving to Google Sheets: {e}")

# Initialize session state for tasks
if 'tasks' not in st.session_state:
    st.session_state.tasks = load_tasks()

# Initialize session state for active timer
if 'active_task_idx' not in st.session_state:
    st.session_state.active_task_idx = None
if 'start_time' not in st.session_state:
    st.session_state.start_time = None

def add_task():
    task_name = st.session_state.new_task_input
    if task_name:
        st.session_state.tasks.append({
            'name': task_name,
            'total_seconds': 0,
            'status': 'Pending'
        })
        st.session_state.new_task_input = "" # Clear input
        save_tasks()

def delete_task(index):
    # Handle active timer logic before deletion
    if st.session_state.active_task_idx is not None:
        if st.session_state.active_task_idx == index:
            # We are deleting the running task. Stop timer first.
            st.session_state.active_task_idx = None
            st.session_state.start_time = None
        elif st.session_state.active_task_idx > index:
            # We are deleting a task above the running one. Shift index down.
            st.session_state.active_task_idx -= 1
            
    st.session_state.tasks.pop(index)
    save_tasks()

def toggle_timer(index):
    current_time = time.time()
    
    # If starting a new timer (and one was already running), stop the old one first
    if st.session_state.active_task_idx is not None and st.session_state.active_task_idx != index:
        # Stop previous
        prev_idx = st.session_state.active_task_idx
        elapsed = current_time - st.session_state.start_time
        st.session_state.tasks[prev_idx]['total_seconds'] += elapsed
        st.session_state.tasks[prev_idx]['status'] = 'Paused'
        st.session_state.active_task_idx = None
        st.session_state.start_time = None

    # Toggle current
    if st.session_state.active_task_idx == index:
        # Stop
        elapsed = current_time - st.session_state.start_time
        st.session_state.tasks[index]['total_seconds'] += elapsed
        st.session_state.tasks[index]['status'] = 'Paused'
        st.session_state.active_task_idx = None
        st.session_state.start_time = None
    else:
        # Start
        st.session_state.active_task_idx = index
        st.session_state.start_time = current_time
        st.session_state.tasks[index]['status'] = 'Running ⏱️'
    
    save_tasks()

def format_time(seconds):
    try:
        val = int(seconds)
    except:
        val = 0
    m, s = divmod(val, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

# Header
st.title("⏱️ AG Time Tracker (GSpread Edition)")
st.markdown("---")

# Input Section
col1, col2 = st.columns([3, 1])
with col1:
    st.text_input("New Task Name", key="new_task_input", placeholder="Enter task description...")
with col2:
    st.markdown("##") # Spacer to align button
    st.button("Add Task", on_click=add_task, use_container_width=True)

st.markdown("### My Tasks")

# Task List
if not st.session_state.tasks:
    st.info("No tasks found. Add one to start tracking!")
else:
    # Header row
    cols = st.columns([0.5, 3, 1.5, 1.5, 1.0, 0.5])
    cols[0].markdown("**#**")
    cols[1].markdown("**Task Name**")
    cols[2].markdown("**Status**")
    cols[3].markdown("**Duration**")
    cols[4].markdown("**Action**")
    cols[5].markdown("**Del**")

    # Loop to render rows
    for idx, task in enumerate(st.session_state.tasks):
        with st.container():
            cols = st.columns([0.5, 3, 1.5, 1.5, 1.0, 0.5])
            
            # Index
            cols[0].text(f"{idx + 1}")
            
            # Name
            cols[1].text(task['name'])
            
            # Status
            status_color = "green" if idx == st.session_state.active_task_idx else "grey"
            cols[2].markdown(f":{status_color}[{task['status']}]")
            
            # Duration Calculation
            current_total = task['total_seconds']
            # Safety check if total_seconds comes as string from sheets
            try:
                current_total = float(current_total)
            except:
                current_total = 0.0
                
            if idx == st.session_state.active_task_idx:
                current_total += (time.time() - st.session_state.start_time)
            
            cols[3].code(format_time(current_total))
            
            # Action Button
            btn_label = "Stop" if idx == st.session_state.active_task_idx else "Start"
            btn_type = "primary" if idx == st.session_state.active_task_idx else "secondary"
            cols[4].button(btn_label, key=f"btn_{idx}", type=btn_type, on_click=toggle_timer, args=(idx,), use_container_width=True)
            
            # Delete Button
            cols[5].button("🗑️", key=f"del_{idx}", type="secondary", on_click=delete_task, args=(idx,), use_container_width=True)
            
    st.markdown("---")

    # Auto-refresh if timer is running
    if st.session_state.active_task_idx is not None:
        time.sleep(1)
        st.rerun()
