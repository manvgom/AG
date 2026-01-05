import streamlit as st
import pandas as pd
import time
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import altair as alt
import pytz
import plotly.express as px
import plotly.graph_objects as go
# Page configuration
st.set_page_config(page_title="Tasks Monitor", page_icon="🖥️", layout="wide")

# --- AUTHENTICATION ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

def check_login():
    if st.session_state.get("auth_input", "") == st.secrets.get("password"):
        st.session_state.authenticated = True
    else:
        st.session_state.auth_error = "Incorrect password ❌"

def logout():
    st.session_state.authenticated = False
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    # Check if password is configured
    if "password" not in st.secrets:
        st.warning("⚠️ Authentication is enabled but no password is set in `.streamlit/secrets.toml`. Please add `password = 'your_password'`.")
        st.stop()
        
    st.title("🔐 Access Required")
    st.text_input("Enter Password", type="password", key="auth_input", on_change=check_login)
    
    if "auth_error" in st.session_state:
        st.error(st.session_state.auth_error)
        del st.session_state.auth_error
        
    st.stop() # Block app execution



# Custom CSS for premium look
st.markdown("""
    <style>
    .stButton>button {
        width: 100%;
        border-radius: 5px;
        /* height: 3em; Removed to match default input height */
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

# Timezone
MADRID_TZ = pytz.timezone('Europe/Madrid')

# Added start_epoch for persistence, formatted_time for readability, archived/completion_date for lifecycle
# Removed 'status' as per user request (Option A)
# Updated to English Title Case Headers (Standardization)
REQUIRED_COLUMNS = ['ID', 'Task', 'Category', 'Duration', 'Start Epoch', 'Notes', 'Date Created', 'Archived', 'Date Archived']

DEFAULT_CATEGORIES = [
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

def load_categories():
    """Load categories from 'Categories' worksheet OR initialize with defaults."""
    
    # Init map if missing
    if 'categories_desc' not in st.session_state:
         st.session_state.categories_desc = {} # Name -> Desc

    if 'categories_list' not in st.session_state:
        # Try loading from sheet
        try:
            gc = get_gc()
            secrets = find_credentials(st.secrets)
            url = secrets.get("spreadsheet") if secrets else None
            if not url and "spreadsheet" in st.secrets: url = st.secrets["spreadsheet"]
            
            if url:
                sh = gc.open_by_url(url)
                try:
                    ws_cat = sh.worksheet("Categories")
                    # Read all values including Description
                    all_rows = ws_cat.get_all_values()
                    
                    if not all_rows:
                         # Empty sheet -> Populate defaults
                         ws_cat.clear()
                         ws_cat.append_row(["Category", "Description"])
                         for c in DEFAULT_CATEGORIES:
                             ws_cat.append_row([c, ""])
                         st.session_state.categories_list = DEFAULT_CATEGORIES
                         st.session_state.categories_desc = {c: "" for c in DEFAULT_CATEGORIES}
                    else:
                        # Parse Rows
                        # Header is row 0
                        data_rows = all_rows[1:]
                        loaded_list = []
                        loaded_desc = {}
                        
                        for row in data_rows:
                            if not row: continue
                            c_name = row[0].strip()
                            if c_name:
                                loaded_list.append(c_name)
                                c_desc = row[1] if len(row) > 1 else ""
                                loaded_desc[c_name] = c_desc
                                
                        if not loaded_list:
                             st.session_state.categories_list = DEFAULT_CATEGORIES
                             st.session_state.categories_desc = {c: "" for c in DEFAULT_CATEGORIES}
                        else:
                             st.session_state.categories_list = loaded_list
                             st.session_state.categories_desc = loaded_desc

                except gspread.WorksheetNotFound:
                    # Create it
                    ws_cat = sh.add_worksheet(title="Categories", rows=100, cols=2)
                    ws_cat.append_row(["Category", "Description"])
                    for c in DEFAULT_CATEGORIES:
                        ws_cat.append_row([c, ""])
                    st.session_state.categories_list = DEFAULT_CATEGORIES
                    st.session_state.categories_desc = {c: "" for c in DEFAULT_CATEGORIES}
            else:
                st.session_state.categories_list = DEFAULT_CATEGORIES
                st.session_state.categories_desc = {c: "" for c in DEFAULT_CATEGORIES}
        except:
            st.session_state.categories_list = DEFAULT_CATEGORIES
            st.session_state.categories_desc = {c: "" for c in DEFAULT_CATEGORIES}

            st.session_state.categories_list = DEFAULT_CATEGORIES
            st.session_state.categories_desc = {c: "" for c in DEFAULT_CATEGORIES}

def save_categories():
    """Persist current categories_list and categories_desc to Sheet."""
    try:
        gc = get_gc()
        secrets = find_credentials(st.secrets)
        url = secrets.get("spreadsheet") if secrets else None
        if not url and "spreadsheet" in st.secrets: url = st.secrets["spreadsheet"]
        if url:
            sh = gc.open_by_url(url)
            ws = sh.worksheet("Categories")
            ws.clear()
            ws.append_row(["Category", "Description"])
            
            # Bulk update
            if 'categories_list' in st.session_state:
                 rows = [[c, st.session_state.categories_desc.get(c, "")] for c in st.session_state.categories_list]
                 if rows:
                     ws.update(f"A2:B{len(rows)+1}", rows)
    except Exception as e:
        print(f"Error saving categories: {e}")

def add_category(new_cat_name, new_cat_desc=""):
    if new_cat_name and new_cat_name not in st.session_state.categories_list:
        st.session_state.categories_list.append(new_cat_name)
        if 'categories_desc' not in st.session_state: st.session_state.categories_desc = {}
        st.session_state.categories_desc[new_cat_name] = new_cat_desc
        
        # Persist
        save_categories()
        st.toast(f"Category '{new_cat_name}' added!", icon="✅")

def remove_category(cat_name):
    if cat_name in st.session_state.categories_list:
        st.session_state.categories_list.remove(cat_name)
        if 'categories_desc' in st.session_state:
             st.session_state.categories_desc.pop(cat_name, None)
             
        # Persist (Overwrite list)
        save_categories()
        st.toast(f"Category '{cat_name}' removed!", icon="🗑️")


def update_category(old_name, new_name, new_desc):
    """Update a category name and description, propagating to tasks."""
    if 'categories_list' not in st.session_state: load_categories()
    
    # 1. Update List
    if old_name in st.session_state.categories_list:
        idx = st.session_state.categories_list.index(old_name)
        st.session_state.categories_list[idx] = new_name
    else:
        # Fallback if somehow missing
        st.session_state.categories_list.append(new_name)
        
    # 2. Update Description
    if 'categories_desc' not in st.session_state: st.session_state.categories_desc = {}
    # Remove old desc if key changed
    if old_name != new_name and old_name in st.session_state.categories_desc:
        del st.session_state.categories_desc[old_name]
    st.session_state.categories_desc[new_name] = new_desc
    
    # 3. Propagate to Tasks
    # We iterate all tasks and update category if it matches old_name
    updated_tasks = False
    if st.session_state.tasks:
        for t in st.session_state.tasks:
            if t.get('category') == old_name:
                t['category'] = new_name
                updated_tasks = True
    
    # 4. Save
    save_categories()
    if updated_tasks:
        save_tasks()
    
    st.toast(f"✅ Category updated: {old_name} -> {new_name}", icon="✨")

def ensure_logs_loaded():
    """Ensure logs_data is loaded in session state."""
    if "logs_data" not in st.session_state or st.session_state.logs_data is None:
        try:
            gc = get_gc()
            secrets = find_credentials(st.secrets)
            url = secrets.get("spreadsheet") if secrets else None
            if not url and "spreadsheet" in st.secrets: url = st.secrets["spreadsheet"]
            
            if url:
                sh = gc.open_by_url(url)
                try:
                    ws_logs = sh.worksheet("Logs")
                    data = ws_logs.get_all_values()
                    
                    # ---------------------------------------------------------
                    # HEADER FIX / MIGRATION
                    # ---------------------------------------------------------
                    # Old: ["ID", "Descripción", "Categoría", "Fecha Inicio", "Fecha Fin", "Tiempo"]
                    # New: ["ID", "Task", "Category", "Start Time", "End Time", "Duration"]
                    NEW_HEADERS = ["ID", "Task", "Category", "Start Time", "End Time", "Duration"]
                    need_header_update = False
                    
                    if not data:
                        need_header_update = True
                    else:
                        current_headers = data[0]
                        # Check if headers match new standard. If not (e.g. Spanish or lowercase), update.
                        # Simple check: Is 2nd col "Task"?
                        if len(current_headers) < 2 or current_headers[1] != "Task":
                            need_header_update = True
                    
                    if need_header_update:
                        if not data:
                            ws_logs.append_row(NEW_HEADERS)
                        else:
                            # Update header row
                            ws_logs.update(range_name="A1:F1", values=[NEW_HEADERS])
                        data = ws_logs.get_all_values()
                        st.toast("✅ Updated Logs Headers to standard English format.", icon="🛠️")

                    if data:
                        raw_headers = data[0]
                        raw_rows = data[1:]
                        valid_indices = [i for i, h in enumerate(raw_headers) if h.strip()]
                        
                        if valid_indices:
                            clean_headers = [raw_headers[i] for i in valid_indices]
                            clean_rows = [[r[i] if i < len(r) else "" for i in valid_indices] for r in raw_rows]
                            st.session_state.logs_data = pd.DataFrame(clean_rows, columns=clean_headers)
                        else:
                             st.session_state.logs_data = pd.DataFrame()
                    else:
                        st.session_state.logs_data = pd.DataFrame()
                except gspread.WorksheetNotFound:
                     st.session_state.logs_data = pd.DataFrame()
            else:
                 st.session_state.logs_data = pd.DataFrame()
        except Exception as e:
            st.warning(f"Error loading logs: {e}")
            st.session_state.logs_data = pd.DataFrame()

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
        if worksheet.title != "General":
            worksheet.update_title("General")
        data = worksheet.get_all_records()
        
        validated_data = []
        active_idx_found = None
        start_time_found = None
        
        for i, row in enumerate(data):
            # MIGRATION LOGIC: Try New Keys -> Fail over to Old Keys
            
            # Duration (Source of Truth)
            # New: 'Duration', Old: 'formatted_time'
            time_str = str(row.get('Duration') or row.get('formatted_time', '00:00:00'))
            total_sec = float(parse_time_str(time_str))
            
            # Start Epoch
            # New: 'Start Epoch', Old: 'start_epoch'
            try:
                raw_ep = str(row.get('Start Epoch') or row.get('start_epoch', 0.0) or 0.0).replace(',', '.')
                start_ep = float(raw_ep)
            except:
                start_ep = 0.0
            
            # If start_epoch is set (>0), this task is RUNNING
            if start_ep > 0:
                active_idx_found = i
                start_time_found = start_ep
            
            clean_row = {
                'id': str(row.get('ID') or row.get('id', '')),
                'name': str(row.get('Task') or row.get('name', '')),
                'category': str(row.get('Category') or row.get('category', '')),
                'total_seconds': total_sec,
                'start_epoch': start_ep,
                'notes': str(row.get('Notes') or row.get('notes', '')),
                'created_date': str(row.get('Date Created') or row.get('created_date', '')),
                'archived': str(row.get('Archived') or row.get('archived', 'False')).lower() == 'true',
                'completion_date': str(row.get('Date Archived') or row.get('completion_date', ''))
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
        if worksheet.title != "General":
            worksheet.update_title("General")
        
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
                task.get('id', ''),
                task.get('name', ''),
                task.get('category', ''),
                format_time(t_sec), 
                task.get('start_epoch', 0.0), 
                task.get('notes', ''),
                task.get('created_date', ''),
                # task.get('status', 'To Do'), # Removed
                str(task.get('archived', False)),
                task.get('completion_date', '')
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

@st.dialog("📝 Task Notes")
def notes_dialog(index):
    task = st.session_state.tasks[index]
    st.markdown(f"**Task:** {task.get('name', 'Unknown')}")
    
    # Text Area
    # We use a key that doesn't conflict with main state to allow "Save" logic
    # Actually, st.dialog reruns are tricky. We want to act on button press.
    
    # Initial load
    if f"note_temp_{index}" not in st.session_state:
        st.session_state[f"note_temp_{index}"] = task.get('notes', '')
        
    def insert_timestamp():
        now_str = datetime.now().strftime("[%d/%m/%Y %H:%M:%S]")
        current_text = st.session_state.get(f"note_temp_{index}", "")
        if current_text:
            new_text = f"{current_text}\n\n{now_str}: "
        else:
            new_text = f"{now_str}: "
        st.session_state[f"note_temp_{index}"] = new_text
        
    # Timestamp Button
    if st.button("📅 Add Timestamp", key=f"ts_btn_{index}"):
        insert_timestamp()
        
    # Text Input
    new_notes = st.text_area(
        "Content",
        value=st.session_state.get(f"note_temp_{index}", ""),
        height=300,
        key=f"note_temp_{index}",
        placeholder="Type details, updates, or logs here..."
    )
    
    if st.button("Save Notes", type="primary", use_container_width=True):
        st.session_state.tasks[index]['notes'] = new_notes
        # Clean temp key to avoid stale data next open? 
        # Actually session state persists, so we should update it or clear it.
        # Clearing it ensures next open pulls from 'tasks' again.
        del st.session_state[f"note_temp_{index}"]
        save_tasks()
        st.rerun()

@st.dialog("➕ Add New Category to Task")
def add_sibling_task_dialog(task_id, task_name):
    st.write(f"Adding new category for: **{task_id} - {task_name}**")
    
    # Category Selection
    load_categories()
    categories = st.session_state.categories_list
    new_cat = st.selectbox("Select New Category", categories, key="sibling_cat_select")
    
    # Show description
    if 'categories_desc' in st.session_state:
        desc = st.session_state.categories_desc.get(new_cat, "")
        if desc:
            st.info(f"💡 {desc}")
    
    if st.button("Create Task Variant", type="primary", use_container_width=True):
        if not new_cat:
            st.error("Please select a category.")
            return

        current_date = datetime.now().strftime("%d/%m/%Y")
        
        # Determine status. Default To Do.
        
        new_task = {
            'id': task_id,
            'name': task_name,
            'category': new_cat,
            # 'status': 'To Do', # Removed
            'total_seconds': 0.0,
            'start_epoch': 0.0,
            'notes': '',
            'created_date': current_date
        }
        
        st.session_state.tasks.append(new_task)
        save_tasks()
        st.rerun()

def log_session(task_id, task_name, category, elapsed_seconds, start_epoch, end_epoch):
    """Appends a new row to the 'Logs' worksheet with the format:
       ID, Descripción, Categoría, Fecha Inicio, Fecha Fin, Tiempo
    """
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
            ws_logs = sh.add_worksheet(title="Logs", rows=1000, cols=6)
            # New Headers
            ws_logs.append_row([
                "ID", 
                "Task", 
                "Category", 
                "Start Time", 
                "End Time", 
                "Duration"
            ])
            
        # Format Timestamps: DD/MM/AAAA HH:MM:SS
        # Explicitly convert to Europe/Madrid
        madrid_tz = pytz.timezone('Europe/Madrid')
        
        # fromtimestamp returns naive local time of server. 
        # Better to strictly use utcfromtimestamp -> localize UTC -> convert to Madrid
        start_utc = datetime.utcfromtimestamp(start_epoch).replace(tzinfo=pytz.utc)
        end_utc = datetime.utcfromtimestamp(end_epoch).replace(tzinfo=pytz.utc)
        
        start_dt = start_utc.astimezone(madrid_tz)
        end_dt = end_utc.astimezone(madrid_tz)
        
        start_str = start_dt.strftime("%d/%m/%Y %H:%M:%S")
        end_str = end_dt.strftime("%d/%m/%Y %H:%M:%S")
        
        # Format Duration: HH:MM:SS
        duration_str = format_time(elapsed_seconds)
        
        # Append log data
        ws_logs.append_row([
            str(task_id),
            task_name,
            category,
            start_str,
            end_str,
            duration_str
        ])
        
        # Invalidate cache to force reload on next view
        st.session_state.logs_data = None
        
    except Exception as e:
        print(f"Log Error: {e}")

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

@st.dialog("✏️ Edit Task")
def edit_task_dialog(index):
    task = st.session_state.tasks[index]
    
    new_id = st.text_input("ID", value=task.get('id', ''))
    new_name = st.text_input("Task", value=task.get('name', ''))
    
    # Category Selectbox
    current_cat = task.get('category', 'Otros')
    cat_list = st.session_state.get('categories_list', DEFAULT_CATEGORIES)
    try:
        cat_idx = cat_list.index(current_cat)
    except:
        cat_idx = 0
    new_cat = st.selectbox("Category", cat_list, index=cat_idx)
    
    col1, col2 = st.columns(2)
    if col1.button("Cancel", use_container_width=True):
        st.rerun()
        
    if col2.button("Save", type="primary", use_container_width=True):
        st.session_state.tasks[index]['id'] = new_id
        st.session_state.tasks[index]['name'] = new_name
        st.session_state.tasks[index]['category'] = new_cat
        save_tasks()
        st.rerun()

@st.dialog("📦 Archive Project")
def archive_confirmation(group_id, group_name):
    st.write(f"Archive project **{group_id} - {group_name}**?")
    st.info("This will move ALL tasks in this group to 'Archived'.")
    
    if st.button("Yes, Archive", type="primary", use_container_width=True):
        current_date_str = datetime.now().strftime("%d/%m/%Y")
        
        # Iterate all tasks and archive matching ones in session state
        for t in st.session_state.tasks:
            t_id = t.get('id', '').strip()
            t_name = t.get('name', '').strip()
            
            if t_id == group_id and t_name == group_name:
                t['archived'] = True
                t['completion_date'] = current_date_str
                
        # Handle active task reset if it belonged to this group
        if st.session_state.active_task_idx is not None:
             active_t = st.session_state.tasks[st.session_state.active_task_idx]
             if active_t.get('archived', False):
                 st.session_state.active_task_idx = None
                 st.session_state.start_time = None
                 
        save_tasks()
        st.rerun()

def unarchive_group(group_id, group_name):
    for t in st.session_state.tasks:
        if t.get('id', '').strip() == group_id and t.get('name', '').strip() == group_name:
            t['archived'] = False
            t['completion_date'] = ""
            
    save_tasks()
    st.rerun()

def add_task():
    task_id = st.session_state.get("new_task_id", "").strip()
    task_name = st.session_state.get("new_task_input", "").strip()
    # Default category if none selected (since input removed)
    task_category = "Otros" 
    
    if not task_id or not task_name:
        st.toast("⚠️ Please fill in ID and Description", icon="⚠️")
        return

    if task_name: # Redundant check but keeping logic structure
        # Capture current date
        current_date = datetime.now(MADRID_TZ).strftime("%d/%m/%Y")

        st.session_state.tasks.append({
            'id': task_id,
            'name': task_name,
            'category': task_category,
            'total_seconds': 0,
            'start_epoch': 0.0,
            'notes': "",
            'created_date': current_date
            # 'status': "To Do" # Removed
        })
        st.session_state.new_task_input = "" 
        # st.session_state.new_category_input = "" # Removed
        st.session_state.new_task_id = "" # Clear ID
        save_tasks()

# Old delete helpers removed in favor of dialog logic

def toggle_timer(index):
    # Rule 1: One timer global
    if st.session_state.active_task_idx is not None and st.session_state.active_task_idx != index:
        st.toast("⚠️ Another timer is running! Stop it first.", icon="🚫")
        return
        
    # Rule 2: Archived tasks cannot start
    if st.session_state.tasks[index].get('archived', False):
        st.toast("🚫 Cannot start timer on archived task.", icon="🔒")
        return

    current_time = time.time()
    
    # Check if we are stopping the CURRENT task
    if st.session_state.active_task_idx == index:
        prev_idx = st.session_state.active_task_idx
        prev_start = st.session_state.tasks[prev_idx].get('start_epoch', 0.0)
        
        # Safety
        if prev_start == 0.0: prev_start = current_time
        
        elapsed = current_time - prev_start
        if elapsed < 0: elapsed = 0
        
        st.session_state.tasks[prev_idx]['total_seconds'] += elapsed
        st.session_state.tasks[prev_idx]['start_epoch'] = 0.0
        
        # Log session
        log_session(
            st.session_state.tasks[prev_idx].get('id', ''),
            st.session_state.tasks[prev_idx].get('name', ''), 
            st.session_state.tasks[prev_idx].get('category', ''), 
            elapsed,
            prev_start,
            current_time
        )
        
        st.session_state.active_task_idx = None
        st.session_state.start_time = None
        
    else:
        # Starting NEW task (Index != Active, and Active is None due to Rule 1)
        st.session_state.active_task_idx = index
        st.session_state.start_time = current_time
        st.session_state.tasks[index]['start_epoch'] = current_time
    
    save_tasks()
        



@st.dialog("⚙️ Manage Categories", width="large")
def manage_categories_dialog():
    st.write("Add or remove categories below.")
    
    # EDIT MODE HANDLING
    edit_target = st.session_state.get("cat_edit_target", None)
    
    if edit_target:
        st.info(f"✏️ Editing: **{edit_target}**")
        # Pre-fill (Session state persistence for inputs needs manual key handling or value=...)
        # Streamlit resets widgets on rerun if key is same but code changed? 
        # Better to rely on separate keys for edit mode or shared keys initialized?
        # Let's use value=... and keys specific to edit to avoid conflict? Or shared.
        
        # Get current desc
        current_desc = st.session_state.get('categories_desc', {}).get(edit_target, "")
        
        new_cat = st.text_input("Category Name", value=edit_target, key="dialog_edit_cat")
        new_desc = st.text_area("Description (Optional)", value=current_desc, key="dialog_edit_desc")
        
        c_up, c_cancel = st.columns([1, 1])
        with c_up:
            if st.button("Update", type="primary", use_container_width=True):
                if new_cat:
                    update_category(edit_target, new_cat, new_desc)
                    st.session_state.cat_edit_target = None # Exit edit mode
                    # st.rerun() # REMOVED: Triggers dialog closure
        with c_cancel:
             if st.button("Cancel", use_container_width=True):
                 st.session_state.cat_edit_target = None
                 # st.rerun() # REMOVED: Triggers dialog closure
                 
    else:
        # ADD MODE
        new_cat = st.text_input("New Category Name", placeholder="e.g. Design, Meeting...", key="dialog_new_cat")
        new_desc = st.text_area("Description (Optional)", placeholder="Context about this category...", key="dialog_new_desc")
        
        if st.button("Add Category", type="primary", use_container_width=True):
            if new_cat:
                add_category(new_cat, new_desc)
                # Fragment auto-reruns on interaction, manual rerun not needed for dialog update
            
    st.markdown("---")
    st.markdown("##### Current Categories")
    
    if not st.session_state.categories_list:
        st.info("No categories found.")
    else:
        # Ensure desc map exists
        if 'categories_desc' not in st.session_state: st.session_state.categories_desc = {}
        
        for cat in st.session_state.categories_list:
            desc = st.session_state.categories_desc.get(cat, "")
            
            c1, c2, c3 = st.columns([3.5, 0.75, 0.75], vertical_alignment="center")
            if desc:
                c1.markdown(f"**{cat}**<br><span style='color:grey; font-size:0.8em;'>{desc}</span>", unsafe_allow_html=True)
            else:
                c1.text(cat)
            
            # Edit Button
            if c2.button("✏️", key=f"edit_cat_dialog_{cat}"):
                st.session_state.cat_edit_target = cat
                # st.rerun() # REMOVED: Triggers dialog closure
                
            # Delete Button
            if c3.button("🗑️", key=f"rm_cat_dialog_{cat}"):
                remove_category(cat)
                # st.rerun() # REMOVED: Triggers dialog closure
    
    # Close button removed as per request (Dialog has built-in close)


# Sidebar Logout & Settings
with st.sidebar:
    if st.button("🔄 Refresh Data", use_container_width=True):
         ensure_logs_loaded(force=True)
         # load_categories(force=True) # Optional, if we want to sync categories too
         st.success("Data reloaded from cloud.")
         st.rerun()
         
    st.header("Configurations")
    
    # Category Management
    load_categories() # Ensure loaded
    
    # Categories Button (Primary Config)
    # Using state-based dialog to prevent closing on updates
    if st.button("⚙️ Categories", use_container_width=True):
        manage_categories_dialog()
        
    # Database Link
    secrets = find_credentials(st.secrets)
    url = secrets.get("spreadsheet") if secrets else None
    if not url and "spreadsheet" in st.secrets: url = st.secrets["spreadsheet"]
    
    if url:
        st.link_button("📂 DDBB", url, use_container_width=True)
        
    # Logout (Bottom)
    if st.button("🔒 Logout", key="logout_btn", use_container_width=True):
        logout()

# Header
st.title("🖥️ Tasks Tracker")
st.markdown("---")

# Tabs
tab_tracker, tab_analytics, tab_logs = st.tabs(["⏱️ Tracker", "📊 Analytics", "📜 Logs"])

with tab_tracker:
    # Input Section
    # Minimalist differentiator: Divider + Container style or just plain collapsed inputs with placeholder.
    # User asked for "minimalist differentiation". Let's use a subheader/caption or just spacing.
    # Also collapsed labels as requested.

    # 3 columns: ID | Description | Add
    # Using 'label_visibility="collapsed"'
    
    # Spacers removed to decrease area.
    # Custom CSS to reduce margin of horizontal rules and ensure tight vertical stacking
    st.markdown("""
        <style>
        /* Tighter dividers */
        hr {
            margin-top: 1em;
            margin-bottom: 1em;
        }
        </style>
    """, unsafe_allow_html=True)

    # Structure: [Spacer, ID, Task, Button, Spacer]
    # Ratio: 1 : 2 : 6 : 2 : 1
    
    col_s1, col_id, col_task, col_btn, col_s2 = st.columns([0.5, 1.5, 5, 1.5, 0.5], vertical_alignment="center")
    
    with col_id:
        st.text_input("ID", key="new_task_id", placeholder="New ID", label_visibility="collapsed")
    with col_task:
        st.text_input("Task", key="new_task_input", placeholder="New Task Description...", label_visibility="collapsed")
    with col_btn:
        st.button("Add Task", on_click=add_task, use_container_width=True)

    st.markdown("---") # Minimalist separation

    # Filters
    # Filters
    # Calculate unique archived groups count first
    archived_groups_count = 0
    if st.session_state.tasks:
         arch_pairs = set()
         for t in st.session_state.tasks:
             if t.get('archived', False):
                 arch_pairs.add((t.get('id', '').strip(), t.get('name', '').strip()))
         archived_groups_count = len(arch_pairs)

    f_col1, f_col2, f_col3, f_col4 = st.columns([1.5, 1.5, 2, 1], vertical_alignment="center")
    
    # Order matched to Analytics/Logs: Date -> Category -> Search (-> Archive)
    with f_col1:
        filter_date = st.date_input("Date", value=[], label_visibility="collapsed")
    with f_col2:
        # Check if we have categories, else default
        cat_options = st.session_state.get('categories_list', DEFAULT_CATEGORIES)
        filter_categories = st.multiselect("Category", cat_options, placeholder="Category", label_visibility="collapsed")
    with f_col3:
        search_query = st.text_input("Search", placeholder="Search ID or Task...", key="tracker_search", label_visibility="collapsed").lower()
    with f_col4:
        show_archived = st.checkbox(f"Archived [{archived_groups_count}]", value=False)

    # Task List Logic
    if not st.session_state.tasks:
        st.info("No tasks found. Add one to start tracking!")
    else:
        # 1. Filter Logic
        filtered_tasks = []
        for i, t in enumerate(st.session_state.tasks):
            # Match Search
            match_search = True
            if search_query:
                id_match = search_query in str(t.get('id', '')).lower()
                desc_match = search_query in str(t.get('name', '')).lower()
                match_search = id_match or desc_match
            
            # Match Category
            match_cat = True
            if filter_categories:
                match_cat = t.get('category') in filter_categories
            
            # Match Date
            match_date = True
            if filter_date:
                try:
                    task_dt = datetime.strptime(t.get('created_date', ''), "%d/%m/%Y").date()
                except:
                    task_dt = None
                
                # Careful: st.date_input with value=[] can return [] or partial tuple
                # If user hasn't selected anything, filter_date might be empty list -> False
                # If user selected one date -> tuple length 1
                
                if not task_dt:
                     # If task has no date, exclude it if filter is active
                     match_date = False 
                else:
                    if len(filter_date) == 1:
                        if task_dt != filter_date[0]:
                            match_date = False
                    elif len(filter_date) == 2:
                        start_d, end_d = filter_date
                        if not (start_d <= task_dt <= end_d):
                            match_date = False
            
            # Match Archive Status
            is_archived = t.get('archived', False)
            match_archive = (is_archived == show_archived)

            if match_search and match_cat and match_date and match_archive:
                filtered_tasks.append((i, t))

        if not filtered_tasks:
            st.warning("No tasks match your filters.")
        else:
            # Group filtered tasks by (id, name) to avoid duplication
            # groups: dict[key: tuple(id, name)] -> list[tuple(index, task)]
            groups = {}
            for idx, task in filtered_tasks:
                key = (task.get('id', '').strip(), task.get('name', '').strip())
                if key not in groups:
                    groups[key] = []
                groups[key].append((idx, task))
            
            # Loop through groups
            for (g_id, g_name), g_tasks in groups.items():
                # Check coverage math
                total_subtasks = len(g_tasks)
                completed_subtasks = sum(1 for _, t in g_tasks if t.get('status') == 'Done')
                
                # Calculate total group time for header
                group_total_seconds = 0.0
                for _, t in g_tasks:
                    try:
                        raw_val = str(t.get('total_seconds', 0.0) or 0.0).replace(',', '.')
                        group_total_seconds += float(raw_val)
                    except:
                        pass
                    
                # Add running time to group total if any task in group is running
                running_in_group = False
                for i, _ in g_tasks:
                    if i == st.session_state.active_task_idx:
                        start_t = st.session_state.start_time or time.time()
                        group_total_seconds += (time.time() - start_t)
                        running_in_group = True
                
                header_duration = format_time(group_total_seconds)
                
                # New Format: II2025029 - MES Fase IV - [00:01:25]
                id_part = g_id if g_id else 'No ID'
                header_str = f"**{id_part}** - {g_name} - [{header_duration}]"
                
                if running_in_group:
                    header_str = "🟢 " + header_str
                
                
                # Render Group Expander
                # Default open if filtered or running (but collapsed if archived)
                is_expanded = ((len(groups) == 1) or running_in_group) and not show_archived
                
                with st.expander(header_str, expanded=is_expanded):
                    # Header row for the group content
                    # Col widths: Category, Date, Duration, Action, Edit, Note, Del
                    # Header row for the group content
                    # Col widths: Category, Duration, Action, Edit, Note, Del
                    # Previous was [2.5, 1.2, 1.5, ...]. Removed 1.2 (Date). Added to Category -> 3.7
                    if g_tasks:
                        # h_cols = st.columns([3.7, 1.5, 0.7, 0.7, 0.7, 0.7], vertical_alignment="center")
                        # h_cols[0].markdown("**Category**") # Removed
                        # h_cols[1].markdown("**Duration**") # Removed
                        pass
                    
                    for idx, task in g_tasks:
                        r_cols = st.columns([3.7, 1.5, 0.7, 0.7, 0.7, 0.7], vertical_alignment="center")
                        
                        # Category
                        cat_name = task.get('category', '')
                        cat_desc = st.session_state.get('categories_desc', {}).get(cat_name, "")
                        if cat_desc:
                             r_cols[0].markdown(f"{cat_name}<br><span style='color:grey; font-size:0.8em;'>{cat_desc}</span>", unsafe_allow_html=True)
                        else:
                             r_cols[0].text(cat_name)
                        
                        # Date Removed
                        # r_cols[1].text(task.get('created_date', '-'))
                        
                        is_running = (idx == st.session_state.active_task_idx)
                        
                        # Duration Calculation
                        try:
                            raw_val = str(task.get('total_seconds', 0.0) or 0.0).replace(',', '.')
                            current_total = float(raw_val)
                        except:
                            current_total = 0.0
                        
                        if is_running:
                            start_t = st.session_state.start_time or time.time()
                            current_total += (time.time() - start_t)
                        
                        dur_str = format_time(current_total)
                        if is_running:
                             r_cols[1].markdown(f"<span style='color:#28a745; font-weight:bold; font-family:monospace; font-size:1.1em;'>{dur_str}</span>", unsafe_allow_html=True)
                        else:
                             r_cols[1].markdown(f"<span style='font-family:monospace;'>{dur_str}</span>", unsafe_allow_html=True)
                        
                        # Buttons
                        btn_label = "⏹️" if is_running else "▶️"
                        btn_type = "primary" if is_running else "secondary"
                        # No more blocked button by status
                        
                        r_cols[2].button(
                            btn_label, 
                            key=f"btn_{idx}", 
                            type=btn_type, 
                            on_click=toggle_timer, 
                            args=(idx,), 
                            use_container_width=True,
                            disabled=show_archived # Disable play if archived
                        )
                        
                            
                        if r_cols[3].button("✏️", key=f"edit_btn_{idx}", on_click=edit_task_dialog, args=(idx,), use_container_width=True, disabled=show_archived):
                            pass

                        # Notes Button - Dynamic Icon
                        has_notes = bool(task.get('notes', '').strip())
                        note_icon = "📝" if has_notes else "📄"
                        
                        r_cols[4].button(note_icon, key=f"note_btn_{idx}", on_click=notes_dialog, args=(idx,), use_container_width=True)
                        
                        if r_cols[5].button("🗑️", key=f"del_{idx}", type="secondary", on_click=delete_confirmation, args=(idx,), use_container_width=True):
                            pass
                    
                    st.write("") # Spacer
                    
                    # Footer: Left = Add Category, Right = Archive
                    f_col1, f_col2 = st.columns([1, 1], vertical_alignment="bottom")
                    
                    with f_col1:
                        if not show_archived:
                            if st.button(f"➕ Add Category", key=f"add_sibling_{g_id}_{g_name}", use_container_width=True):
                                add_sibling_task_dialog(g_id, g_name)
                    
                    with f_col2:
                        # Use container to align right? Streamlit columns justify content left by default.
                        # We can just put it in the second column.
                        if show_archived:
                             st.button("📂 Unarchive Project", key=f"unarch_{g_id}_{g_name}", on_click=unarchive_group, args=(g_id, g_name), use_container_width=True)
                        else:
                             st.button("📦 Archive Project", key=f"arch_{g_id}_{g_name}", on_click=archive_confirmation, args=(g_id, g_name), use_container_width=True)
                
        st.markdown("---")

with tab_analytics:
    # Ensure data is loaded
    ensure_logs_loaded()
    
    if "logs_data" not in st.session_state or st.session_state.logs_data.empty:
         st.info("No logs data available yet. Start working on tasks to see analytics!")
    else:
        # Process Data from LOGS (Not Tasks)
        df_log = st.session_state.logs_data.copy()
        
        # Schema: ["ID", "Task", "Category", "Start Time", "End Time", "Duration"]
        # Parse 'Duration' (HH:MM:SS) -> Seconds manually
        def parse_dur(x):
            try:
                parts = str(x).split(':')
                if len(parts) == 3:
                     h, m, s = map(int, parts)
                     return h*3600 + m*60 + s
            except:
                pass
            return 0.0
            
        df_log['Seconds'] = df_log['Duration'].apply(parse_dur)
        # df_log['Seconds'] = pd.to_numeric(df_log['Duration'], errors='coerce').fillna(0) # OLD: Failed because it's HH:MM:SS string
        
        df_log['Hours'] = df_log['Seconds'] / 3600.0
        
        # Convert Dates
        # Format in Sheet is "DD/MM/YYYY HH:MM:SS" from log_session
        
        # Parse 'Start Time' to datetime
        df_log['StartDT'] = pd.to_datetime(df_log['Start Time'], format="%d/%m/%Y %H:%M:%S", errors='coerce')
        # Fallback if format differs?
        
        df_log['Date'] = df_log['StartDT'].dt.date
        df_log['Hour'] = df_log['StartDT'].dt.hour
        
    
    # helper for presets
    def get_preset_dates(option):
        today = datetime.now(MADRID_TZ).date()
        if option == "Today":
            return (today, today)
        elif option == "Week":
            start = today - pd.Timedelta(days=today.weekday()) # Monday
            return (start, today)
        elif option == "Month":
            start = today.replace(day=1)
            return (start, today)
        elif option == "Year":
             start = today.replace(month=1, day=1)
             return (start, today)
        return []

    # Filter State Management - Default to Week if not set, or keep existing
    if "an_preset" not in st.session_state: st.session_state.an_preset = "Week"
    
    # Calculate initial range from preset logic (optional, acts as default)
    # We can keep using get_preset_dates for initialization if needed, 
    # but since buttons are gone, maybe we just default to 'Today' or 'Week' once.
    # Let's trust the session state or just default to empty if desired. 
    # Current behavior: preset_range derives from 'an_preset'.
    preset_range = get_preset_dates(st.session_state.an_preset) if st.session_state.an_preset != "All" else []
    
    # Row 1: Detailed Filters (No styling/titles)
    f_col1, f_col2, f_col3 = st.columns(3)
    
    # Category Filter
    if "logs_data" in st.session_state and isinstance(st.session_state.logs_data, pd.DataFrame) and not st.session_state.logs_data.empty:
        df_log = st.session_state.logs_data.copy()
        
        # Pre-process Data (Duration/Dates)
        def parse_dur(x):
            try:
                parts = str(x).split(':')
                if len(parts) == 3:
                     h, m, s = map(int, parts)
                     return h*3600 + m*60 + s
            except:
                pass
            return 0.0
            
        df_log['Seconds'] = df_log['Duration'].apply(parse_dur)
        df_log['Hours'] = df_log['Seconds'] / 3600.0
        
        df_log['StartDT'] = pd.to_datetime(df_log['Start Time'], format="%d/%m/%Y %H:%M:%S", errors='coerce')
        df_log['Date'] = df_log['StartDT'].dt.date
        df_log['Hour'] = df_log['StartDT'].dt.hour
        
        # FILTERS UI
        with f_col1:
            date_range = st.date_input("Date Range", value=preset_range, key="an_date_range", label_visibility="collapsed")
            
        with f_col2:
            all_cats = sorted(list(set(df_log['Category'].dropna()))) if not df_log.empty else []
            sel_cats = st.multiselect("Category", all_cats, placeholder="All Categories", label_visibility="collapsed")
            
        with f_col3:
            search_txt = st.text_input("Search", placeholder="Search ID or Task...", key="analytics_search", label_visibility="collapsed").lower()
        
        # --- APPLY LOGIC ---
        if date_range:
            if len(date_range) == 2:
                s, e = date_range
                df_log = df_log[(df_log['Date'] >= s) & (df_log['Date'] <= e)]
            elif len(date_range) == 1:
                df_log = df_log[df_log['Date'] == date_range[0]]
                
        if sel_cats:
            df_log = df_log[df_log['Category'].isin(sel_cats)]
            
        if search_txt:
             df_log = df_log[
                df_log['ID'].astype(str).str.lower().str.contains(search_txt) | 
                df_log['Task'].astype(str).str.lower().str.contains(search_txt)
            ]
            
    else:
         df_log = pd.DataFrame() # Fallback 
                
    if df_log.empty:
        st.warning("No data for selected period.")
    else:


            # Prepare Data (Global for Analytics)
            df_log['Seconds'] = df_log['Duration'].apply(parse_dur)
            df_log['Hours'] = df_log['Seconds'] / 3600.0

            # -------------------------------------------------------
            # 2. The "Flow" (Sankey Diagram)
            # -------------------------------------------------------
            st.subheader("🌊 Time Flow (Category ➔ Task)")
            st.caption("Where does your time actually go? Follow the stream.")
            
            # Sankey Data Prep
            sankey_data = df_log.groupby(['Category', 'Task'])['Seconds'].sum().reset_index()
            sankey_data = sankey_data[sankey_data['Seconds'] > 0] 
            
            if not sankey_data.empty:
                sankey_data['Formatted'] = sankey_data['Seconds'].apply(format_time)
                
                all_cats = list(sankey_data['Category'].unique())
                all_tasks = list(sankey_data['Task'].unique())
                node_labels = all_cats + all_tasks
                node_map = {label: i for i, label in enumerate(node_labels)}
                
                sources = [node_map[row['Category']] for _, row in sankey_data.iterrows()]
                targets = [node_map[row['Task']] for _, row in sankey_data.iterrows()]
                values = (sankey_data['Seconds'] / 3600.0).tolist() # Visual thickness still needs valid numeric
                custom_data = sankey_data['Formatted'].tolist() # For tooltip
                
                # Note: Sankey hovertemplate is tricky for links vs nodes. 
                # We will just try to simplify or use standard values, but user wants HH:MM:SS.
                # Plotly Sankey shows "value" by default. We can replace it with customdata.
                
                fig_sankey = go.Figure(data=[go.Sankey(
                    node = dict(
                      pad = 15,
                      thickness = 20,
                      line = dict(color = "black", width = 0.5),
                      label = node_labels,
                      color = "rgba(46, 204, 113, 0.5)",
                      # We'd need to pre-calculate node total time for HH:MM:SS on nodes, skipping for now to keep it simple or doing it right?
                      # Let's do links first which is the "flow".
                    ),
                    link = dict(
                      source = sources,
                      target = targets,
                      value = values,
                      customdata = custom_data,
                      hovertemplate='Source: %{source.label}<br>Target: %{target.label}<br>Time: %{customdata}<extra></extra>',
                      color = "rgba(200, 200, 200, 0.3)" 
                  ))])
                
                fig_sankey.update_layout(title_text="", font_size=12, height=400, margin=dict(l=0, r=0, t=10, b=10))
                st.plotly_chart(fig_sankey, use_container_width=True)
            else:
                st.info("Not enough data for Flow Chart.")

            st.markdown("---")

            # -------------------------------------------------------
            # 3. Heatmap & Evolution
            # -------------------------------------------------------
            c_heat, c_evol = st.columns(2)
            
            with c_heat:
                st.subheader("🔥 Intensity Map")
                # Prepare Data: Date, Hours
                heat_data = df_log.groupby('Date')['Seconds'].sum().reset_index()
                heat_data['Hours'] = heat_data['Seconds'] / 3600.0
                heat_data['Formatted'] = heat_data['Seconds'].apply(format_time)
                
                heat_data['Date'] = pd.to_datetime(heat_data['Date'])
                heat_data['Week'] = heat_data['Date'].dt.isocalendar().week
                heat_data['Day'] = heat_data['Date'].dt.day_name()
                
                days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                
                fig_heat = px.density_heatmap(
                    heat_data, 
                    x="Week", 
                    y="Day", 
                    z="Hours", 
                    color_continuous_scale="Greens",
                    category_orders={"Day": days_order},
                    nbinsx=52,
                    hover_data=['Formatted']
                )
                fig_heat.update_traces(hovertemplate='Week: %{x}<br>Day: %{y}<br>Time: %{customdata[0]}<extra></extra>')
                fig_heat.update_layout(height=350, title="Daily Intensity")
                st.plotly_chart(fig_heat, use_container_width=True)
                
            with c_evol:
                st.subheader("📈 Strategy Evolution")
                df_log['WeekStart'] = df_log['StartDT'].dt.to_period('W').apply(lambda r: r.start_time)
                evol_data = df_log.groupby(['WeekStart', 'Category'])['Seconds'].sum().reset_index()
                evol_data['Hours'] = evol_data['Seconds'] / 3600.0
                evol_data['Formatted'] = evol_data['Seconds'].apply(format_time)
                
                if not evol_data.empty:
                    fig_evol = px.bar(
                        evol_data, 
                        x="WeekStart", 
                        y="Hours", 
                        color="Category", 
                        title="",
                        labels={"WeekStart": "Week", "Hours": "Total Hours"},
                        hover_data=['Formatted', 'Category']
                    )
                    fig_evol.update_traces(hovertemplate='Week: %{x}<br>Category: %{customdata[1]}<br>Time: %{customdata[0]}<extra></extra>')
                    fig_evol.update_layout(height=350, showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                    st.plotly_chart(fig_evol, use_container_width=True)
                else:
                    st.info("No data for evolution.")


            

            
            st.markdown("---")




with tab_logs:
    ensure_logs_loaded()
    
    if "logs_data" in st.session_state and isinstance(st.session_state.logs_data, pd.DataFrame) and not st.session_state.logs_data.empty:
        df_log = st.session_state.logs_data.copy()
        
        # Prepare columns (reuse logic)
        def parse_dur_log(x):
            try:
                parts = str(x).split(':')
                if len(parts) == 3:
                     h, m, s = map(int, parts)
                     return h*3600 + m*60 + s
            except:
                pass
            return 0.0
            
        df_log['Seconds'] = df_log['Duration'].apply(parse_dur_log)
        df_log['Hours'] = df_log['Seconds'] / 3600.0
        df_log['StartDT'] = pd.to_datetime(df_log['Start Time'], format="%d/%m/%Y %H:%M:%S", errors='coerce')
        df_log['Date'] = df_log['StartDT'].dt.date
        
        # Filters UI
        f_col1, f_col2, f_col3 = st.columns(3)
        with f_col1:
            log_date_range = st.date_input("Date Range", value=[], key="log_date_range", label_visibility="collapsed")
        with f_col2:
            all_cats = sorted(list(set(df_log['Category'].dropna()))) if not df_log.empty else []
            log_sel_cats = st.multiselect("Category", all_cats, placeholder="All Categories", key="log_cat_filter", label_visibility="collapsed")
        with f_col3:
            log_search = st.text_input("Search", placeholder="Search ID or Task...", key="log_search", label_visibility="collapsed").lower()
            
        # Apply Filters
        if log_date_range:
            if len(log_date_range) == 2:
                s, e = log_date_range
                df_log = df_log[(df_log['Date'] >= s) & (df_log['Date'] <= e)]
            elif len(log_date_range) == 1:
                df_log = df_log[df_log['Date'] == log_date_range[0]]
                
        if log_sel_cats:
            df_log = df_log[df_log['Category'].isin(log_sel_cats)]
            
        if log_search:
             df_log = df_log[
                df_log['ID'].astype(str).str.lower().str.contains(log_search) | 
                df_log['Task'].astype(str).str.lower().str.contains(log_search)
            ]
            
        # Display
        if not df_log.empty:
            st.dataframe(
                df_log, 
                use_container_width=True,
                column_config={
                    "Start Time": st.column_config.DatetimeColumn(format="D/M/YYYY HH:mm:ss"),
                    "End Time": st.column_config.DatetimeColumn(format="D/M/YYYY HH:mm:ss"),
                     "Hours": None,
                     "Seconds": None, # Hide helper
                     "StartDT": None,
                     "Date": None
                }
            )
        else:
             st.info("No logs match your filters.")
    else:
        st.info("No logs found yet.")

# Auto-refresh if timer is running
if st.session_state.active_task_idx is not None:
    time.sleep(1)
    st.rerun()
