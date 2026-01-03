import streamlit as st
import pandas as pd
import time
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# Page configuration
st.set_page_config(page_title="Tasks Monitor", page_icon="⏱️", layout="wide")

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
# Added start_epoch for persistence, formatted_time for readability
REQUIRED_COLUMNS = ['name', 'category', 'formatted_time', 'start_epoch', 'notes', 'created_date']

CATEGORIES = [
    "Gestión de la demanda",
    "Gestión de la planificación",
    "Otros"
]

# Helper: Format seconds to HH:MM:SS
def format_time(seconds):
    try:
        # Handle string floats "12.5" -> 12
        val = int(float(seconds))
    except:
        val = 0
    m, s = divmod(val, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

# Helper: Find credentials dictionary recursively
def find_credentials(secrets_proxy):
    # ... (content remains same, just ensuring format_time is above) ...
    # To avoid huge diff, I will just replicate find_credentials lines if needed or assume I can't move blocks easily with replace_file without reprinting content.
    if "private_key" in secrets_proxy:
        return secrets_proxy
    for key in secrets_proxy:
        val = secrets_proxy[key]
        if hasattr(val, "keys"): 
            if "private_key" in val:
                return val
            for subkey in val:
                subval = val[subkey]
                if hasattr(subval, "keys") and "private_key" in subval:
                    return subval
    return None

def get_gc():
    secrets = find_credentials(st.secrets)
    
    if not secrets:
        st.error("❌ Credentials not found.")
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

# Helper: Parse HH:MM:SS to seconds
def parse_time_str(time_str):
    try:
        parts = str(time_str).split(':')
        if len(parts) == 3:
            h, m, s = map(int, parts)
            return h * 3600 + m * 60 + s
    except:
        pass
    return 0.0

def load_tasks():
    try:
        gc = get_gc()
        secrets = find_credentials(st.secrets)
        url = secrets.get("spreadsheet") if secrets else None
        
        if not url:
             if "spreadsheet" in st.secrets: url = st.secrets["spreadsheet"]
             elif "connections" in st.secrets and "gsheets" in st.secrets.connections:
                 url = st.secrets.connections.gsheets.get("spreadsheet")

        if not url:
            st.error("Spreadsheet URL not found.")
            return []

        sh = gc.open_by_url(url)
        worksheet = sh.get_worksheet(0)
        data = worksheet.get_all_records()
        
        validated_data = []
        active_idx_found = None
        start_time_found = None
        
        for i, row in enumerate(data):
            # SOURCE OF TRUTH: HH:MM:SS column ('formatted_time')
            # We ignore 'total_seconds' from sheet to avoid the giant number bugs.
            # We recalculate total_seconds from the clean string.
            time_str = str(row.get('formatted_time', '00:00:00'))
            total_sec = float(parse_time_str(time_str))
            
            # Start Epoch Logic
            try:
                raw_ep = str(row.get('start_epoch', 0.0) or 0.0).replace(',', '.')
                start_ep = float(raw_ep)
            except:
                start_ep = 0.0
            
            # If start_epoch is set (>0), this task is RUNNING
            status = str(row.get('status', 'Pending'))
            if start_ep > 0:
                active_idx_found = i
                start_time_found = start_ep
                status = 'Running ⏱️' 
            
            clean_row = {
                'name': str(row.get('name', '')),
                'category': str(row.get('category', '')),
                'total_seconds': total_sec,
                'status': status,
                'start_epoch': start_ep,
                'notes': str(row.get('notes', ''))
            }
            validated_data.append(clean_row)
        
        if active_idx_found is not None:
            st.session_state.active_task_idx = active_idx_found
            st.session_state.start_time = start_time_found
            
        return validated_data
        
    except Exception as e:
        st.warning(f"Could not load data (or empty sheet): {e}")
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
            # Calculate current total for display/saving (if running, use snapshot)
            # Actually, save_tasks usually saves the 'base' total_seconds.
            # If running, we might want to save the *current* elapsed? 
            # No, 'start_epoch' handles the running part. 'total_seconds' is the stored accumulator.
            # But the user wants 'formatted_time' to look correct.
            # We'll formatting the STored total_seconds.
            
            t_sec = task.get('total_seconds', 0)
            
            row = [
                task.get('name', ''),
                task.get('category', ''),
                format_time(t_sec), 
                task.get('status', 'Pending'),
                task.get('start_epoch', 0.0),
                task.get('notes', '')
            ]
            values.append(row)
            
        worksheet.clear()
        worksheet.update(values)
        
    except Exception as e:
        st.error(f"Error saving to Google Sheets: {e}")

# Initialize session state for tasks
if 'tasks' not in st.session_state:
    st.session_state.tasks = load_tasks()

# Initialize session state placeholders if not set by load_tasks
if 'active_task_idx' not in st.session_state:
    st.session_state.active_task_idx = None
if 'start_time' not in st.session_state:
    st.session_state.start_time = None



if 'confirm_delete_idx' not in st.session_state:
    st.session_state.confirm_delete_idx = None
if 'active_note_idx' not in st.session_state:
    st.session_state.active_note_idx = None

def toggle_notes(index):
    # If closing, save manually to ensure latest change is captured
    if st.session_state.active_note_idx == index:
        key = f"note_content_{index}"
        if key in st.session_state:
            st.session_state.tasks[index]['notes'] = st.session_state[key]
            save_tasks()
        st.session_state.active_note_idx = None
    else:
        st.session_state.active_note_idx = index

def update_notes():
    idx = st.session_state.active_note_idx
    if idx is not None:
        key = f"note_content_{idx}"
        if key in st.session_state:
            st.session_state.tasks[idx]['notes'] = st.session_state[key]
            save_tasks()

def log_session(task_name, category, elapsed_seconds):
    """Appends a new row to the 'Logs' worksheet."""
    try:
        if elapsed_seconds < 1: return # Ignore accidental clicks
        
        gc = get_gc()
        secrets = find_credentials(st.secrets)
        url = secrets.get("spreadsheet") if secrets else None
        if not url and "spreadsheet" in st.secrets: url = st.secrets["spreadsheet"]
        
        if not url: return

        sh = gc.open_by_url(url)
        
        # Get or create 'Logs' worksheet
        try:
            ws_logs = sh.worksheet("Logs")
        except:
            ws_logs = sh.add_worksheet(title="Logs", rows=1000, cols=5)
            ws_logs.append_row(["Date", "Task Name", "Category", "Duration (s)", "Duration (Formatted)"])
            
        # Append log data
        today_str = datetime.now().strftime("%d/%m/%Y")
        ws_logs.append_row([
            today_str,
            task_name,
            category,
            elapsed_seconds,
            format_time(elapsed_seconds)
        ])
        
    except Exception as e:
        st.warning(f"Could not log session: {e}")

@st.dialog("⚠️ Delete Task")
def delete_confirmation(index):
    st.write("Are you sure you want to delete this task?")
    st.write(f"**{st.session_state.tasks[index]['name']}**")
    
    col1, col2 = st.columns(2)
    if col1.button("Cancel", use_container_width=True):
        st.rerun()
        
    if col2.button("Delete", type="primary", use_container_width=True):
        # Perform actual deletion
        # Stop timer if deleting active task
        if st.session_state.active_task_idx == index:
            st.session_state.active_task_idx = None
            st.session_state.start_time = None
        elif st.session_state.active_task_idx is not None and st.session_state.active_task_idx > index:
            st.session_state.active_task_idx -= 1
                
        st.session_state.tasks.pop(index)
        save_tasks()
        st.rerun()

def add_task():
    task_name = st.session_state.new_task_input
    task_category = st.session_state.get("new_category_input", "") 
    
    if task_name:
        # Capture current date
        current_date = datetime.now().strftime("%d/%m/%Y")

        st.session_state.tasks.append({
            'name': task_name,
            'category': task_category,
            'total_seconds': 0,
            # 'status' removed
            'start_epoch': 0.0,
            'notes': "",
            'created_date': current_date
        })
        st.session_state.new_task_input = "" 
        st.session_state.new_category_input = "" 
        save_tasks()

# Old delete helpers removed in favor of dialog logic

def toggle_timer(index):
    # ... (toggle_timer logic remains same) ...
    current_time = time.time()
    
    # 1. Stop distinct previous task if running
    if st.session_state.active_task_idx is not None and st.session_state.active_task_idx != index:
        prev_idx = st.session_state.active_task_idx
        prev_start = st.session_state.tasks[prev_idx].get('start_epoch', 0.0)
        
        # Safety: If start_epoch is missing/0, assume we just started (0 elapsed) to avoid 120-year bug
        if prev_start == 0.0:
            prev_start = current_time
        
        # Calculate delta
        elapsed = current_time - prev_start
        if elapsed < 0: elapsed = 0 
        
        st.session_state.tasks[prev_idx]['total_seconds'] += elapsed
        # Status update removed
        st.session_state.tasks[prev_idx]['start_epoch'] = 0.0 
        
        st.session_state.active_task_idx = None
        st.session_state.start_time = None

    # 2. Toggle clicked task
    if st.session_state.active_task_idx == index:
        # STOP
        start_t = st.session_state.tasks[index].get('start_epoch', 0.0)
        
        # Safety check
        if start_t == 0.0:
            start_t = current_time
            
        elapsed = current_time - start_t
        if elapsed < 0: elapsed = 0
        
        st.session_state.tasks[index]['total_seconds'] += elapsed
        # Status update removed
        st.session_state.tasks[index]['start_epoch'] = 0.0 
        
        # LOG SESSION
        log_session(task.get('name'), task.get('category'), elapsed)

        st.session_state.active_task_idx = None
        st.session_state.start_time = None
    else:
        # START
        st.session_state.active_task_idx = index
        st.session_state.start_time = current_time
        # Status update removed
        st.session_state.tasks[index]['start_epoch'] = current_time 
    
    save_tasks()

# Header
st.title("⏱️ Tasks Monitor")
st.markdown("---")

# Input Section
col1, col2, col3 = st.columns([3, 2, 1], vertical_alignment="bottom")
with col1:
    st.text_input("Task Name", key="new_task_input", placeholder="Enter task description...")
with col2:
    # Changed to Selectbox
    st.selectbox("Category", CATEGORIES, key="new_category_input")
with col3:
    st.button("Add", on_click=add_task, use_container_width=True)

st.markdown("### My Tasks")

# Task List
if not st.session_state.tasks:
    st.info("No tasks found. Add one to start tracking!")
else:
    # Header row
    # Col widths: Index (#), Date, Name, Category, Duration, Action, Note, Del
    # Status removed. Distribute weights.
    # Total ~10. Old Status was 1.3. Give to Name (+0.5) and Category (+0.8) approx.
    # New: 0.5, 1.2, 3.0, 2.6, 1.2, 0.5, 0.5, 0.5 = 10.0
    cols = st.columns([0.5, 1.2, 3.0, 2.6, 1.2, 0.5, 0.5, 0.5])
    cols[0].markdown("**#**")
    cols[1].markdown("**Date**")
    cols[2].markdown("**Task Name**")
    cols[3].markdown("**Category**")
    # Status Header Removed
    cols[4].markdown("**Duration**")
    cols[5].markdown("") # Action
    cols[6].markdown("") # Note
    cols[7].markdown("") # Del

    # Loop to render rows
    for idx, task in enumerate(st.session_state.tasks):
        with st.container():
            cols = st.columns([0.5, 1.2, 3.0, 2.6, 1.2, 0.5, 0.5, 0.5])
            
            # Index
            cols[0].text(f"{idx + 1}")
            
            # Date
            cols[1].text(task.get('created_date', '-'))
            
            # Name
            cols[2].text(task.get('name', ''))
            
            # Category
            cols[3].text(task.get('category', ''))
            
            # Status Column REMOVED
            is_running = (idx == st.session_state.active_task_idx)
            
            # Duration Calculation
            try:
                raw_val = str(task.get('total_seconds', 0.0) or 0.0).replace(',', '.')
                current_total = float(raw_val)
            except:
                current_total = 0.0
            
            # If running, add ONLY the elapsed time since start (don't mutate session state here)
            if is_running:
                # Use stored start_time for smooth UI updates
                start_t = st.session_state.start_time or time.time()
                current_total += (time.time() - start_t)
            
            cols[4].code(format_time(current_total))
            
            # Action Button (Icon based)
            btn_label = "⏹️" if is_running else "▶️"
            btn_type = "primary" if is_running else "secondary"
            cols[5].button(btn_label, key=f"btn_{idx}", type=btn_type, on_click=toggle_timer, args=(idx,), use_container_width=True)
            
            # Notes Button
            cols[6].button("📝", key=f"note_btn_{idx}", on_click=toggle_notes, args=(idx,), use_container_width=True)
            
            # Delete Button
            if cols[7].button("🗑️", key=f"del_{idx}", type="secondary", on_click=delete_confirmation, args=(idx,), use_container_width=True):
                pass # The click triggers the dialog logic via the callback
            
            # Notes Area (Conditional)
            if st.session_state.active_note_idx == idx:
                st.markdown(f"**Notes for: {task.get('name', '')}**")
                st.text_area(
                    "Notes", 
                    value=task.get('notes', ''), 
                    key=f"note_content_{idx}",
                    on_change=update_notes,
                    label_visibility="collapsed",
                    placeholder="Write details here..."
                )
            
    st.markdown("---")

    # Auto-refresh if timer is running
    if st.session_state.active_task_idx is not None:
        time.sleep(1)
        st.rerun()

