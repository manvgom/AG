import streamlit as st
import pandas as pd
import time
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import altair as alt

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
# Added start_epoch for persistence, formatted_time for readability, archived/completion_date for lifecycle
REQUIRED_COLUMNS = ['id', 'name', 'category', 'formatted_time', 'start_epoch', 'notes', 'created_date', 'status', 'archived', 'completion_date']

DEFAULT_CATEGORIES = [
    "Gestión de la demanda",
    "Gestión de la planificación",
    "Otros"
]

STATUS_OPTIONS = ["To Do", "Waiting", "Done"]

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

def add_category(new_cat_name, new_cat_desc=""):
    if new_cat_name and new_cat_name not in st.session_state.categories_list:
        st.session_state.categories_list.append(new_cat_name)
        if 'categories_desc' not in st.session_state: st.session_state.categories_desc = {}
        st.session_state.categories_desc[new_cat_name] = new_cat_desc
        
        # Persist
        try:
            gc = get_gc()
            secrets = find_credentials(st.secrets)
            url = secrets.get("spreadsheet") if secrets else None
            if not url and "spreadsheet" in st.secrets: url = st.secrets["spreadsheet"]
            if url:
                sh = gc.open_by_url(url)
                ws = sh.worksheet("Categories")
                ws.append_row([new_cat_name, new_cat_desc])
                st.toast(f"Category '{new_cat_name}' added!", icon="✅")
        except:
             pass

def remove_category(cat_name):
    if cat_name in st.session_state.categories_list:
        st.session_state.categories_list.remove(cat_name)
        if 'categories_desc' in st.session_state:
             st.session_state.categories_desc.pop(cat_name, None)
             
        # Persist (Overwrite list)
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
                rows = [[c, st.session_state.categories_desc.get(c, "")] for c in st.session_state.categories_list]
                if rows:
                    ws.update(f"A2:B{len(rows)+1}", rows)
                st.toast(f"Category '{cat_name}' removed!", icon="🗑️")
        except Exception as e:
            st.warning(f"Error removing category: {e}")

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
                    NEW_HEADERS = ["ID", "Descripción", "Categoría", "Fecha Inicio", "Fecha Fin", "Tiempo"]
                    need_header_update = False
                    
                    if not data:
                        need_header_update = True
                    else:
                        current_headers = data[0]
                        if len(current_headers) < 3 or current_headers[0] != "ID" or current_headers[1] != "Descripción":
                            need_header_update = True
                    
                    if need_header_update:
                        if not data:
                            ws_logs.append_row(NEW_HEADERS)
                        else:
                            ws_logs.update(range_name="A1:F1", values=[NEW_HEADERS])
                        data = ws_logs.get_all_values()
                        st.toast("✅ Updated Logs Headers to new format.", icon="🛠️")

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
            if start_ep > 0:
                active_idx_found = i
                start_time_found = start_ep
            
            # Status Logic
            status = str(row.get('status', 'To Do'))
            if status not in STATUS_OPTIONS:
                status = "To Do"
            
            clean_row = {
                'id': str(row.get('id', '')),
                'name': str(row.get('name', '')),
                'category': str(row.get('category', '')),
                'total_seconds': total_sec,
                # 'status' is kept for backward compat in CSV but we don't display it anymore
                'status': status, 
                'start_epoch': start_ep,
                'notes': str(row.get('notes', '')),
                'created_date': str(row.get('created_date', '')),
                'archived': str(row.get('archived', 'False')).lower() == 'true',
                'completion_date': str(row.get('completion_date', ''))
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
                task.get('status', 'To Do'),
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
            'status': 'To Do',
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
                "Descripción", 
                "Categoría", 
                "Fecha Inicio", 
                "Fecha Fin", 
                "Tiempo"
            ])
            
        # Format Timestamps: DD/MM/AAAA HH:MM:SS
        start_dt = datetime.fromtimestamp(start_epoch)
        end_dt = datetime.fromtimestamp(end_epoch)
        
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
    new_name = st.text_input("Description", value=task.get('name', ''))
    
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
        current_date = datetime.now().strftime("%d/%m/%Y")

        st.session_state.tasks.append({
            'id': task_id,
            'name': task_name,
            'category': task_category,
            'total_seconds': 0,
            'start_epoch': 0.0,
            'notes': "",
            'created_date': current_date,
            'status': "To Do"
        })
        st.session_state.new_task_input = "" 
        # st.session_state.new_category_input = "" # Removed
        st.session_state.new_task_id = "" # Clear ID
        save_tasks()

# Old delete helpers removed in favor of dialog logic

def update_status(task_idx, new_status):
    st.session_state.tasks[task_idx]['status'] = new_status
    save_tasks()

def toggle_timer(index):
    # Rule 1: One timer global
    if st.session_state.active_task_idx is not None and st.session_state.active_task_idx != index:
        st.toast("⚠️ Another timer is running! Stop it first.", icon="🚫")
        return
        
    # Rule 2: Done means Done
    if st.session_state.tasks[index].get('status') == 'Done':
        st.toast("Task is marked as Done. Unable to start timer.", icon="✅")
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
        



@st.dialog("⚙️ Manage Categories")
def manage_categories_dialog():
    st.write("Add or remove categories below.")
    
    new_cat = st.text_input("New Category Name", placeholder="e.g. Design, Meeting...", key="dialog_new_cat")
    new_desc = st.text_area("Description (Optional)", placeholder="Context about this category...", key="dialog_new_desc")
    
    if st.button("Add Category", type="primary", use_container_width=True):
        if new_cat:
            add_category(new_cat, new_desc)
            st.rerun()
            
    st.markdown("---")
    st.markdown("##### Current Categories")
    
    if not st.session_state.categories_list:
        st.info("No categories found.")
    else:
        # Ensure desc map exists
        if 'categories_desc' not in st.session_state: st.session_state.categories_desc = {}
        
        for cat in st.session_state.categories_list:
            desc = st.session_state.categories_desc.get(cat, "")
            
            c1, c2 = st.columns([4, 1], vertical_alignment="center")
            if desc:
                c1.markdown(f"**{cat}**<br><span style='color:grey; font-size:0.8em;'>{desc}</span>", unsafe_allow_html=True)
            else:
                c1.text(cat)
                
            if c2.button("🗑️", key=f"rm_cat_dialog_{cat}"):
                remove_category(cat)
                st.rerun()
    
    if st.button("Close", key="close_cat_dialog"):
        st.session_state.show_cat_dialog = False
        st.rerun()


# Sidebar Logout & Settings
with st.sidebar:
    st.header("Configurations")
    
    # Category Management
    load_categories() # Ensure loaded
    
    # Categories Button (Primary Config)
    # Using on_click directly with the dialog function handles the state automatically
    st.button("⚙️ Categories", use_container_width=True, on_click=manage_categories_dialog)
        
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
st.title("🖥️ Tasks Monitor")
st.markdown("---")

# Tabs
tab_tracker, tab_analytics, tab_logs = st.tabs(["⏱️ Tracker", "📊 Analytics", "📜 Logs"])

with tab_tracker:
    # Input Section
    # 3 columns: ID | Description | Add
    col0, col1, col2 = st.columns([1, 4, 1], vertical_alignment="bottom")
    with col0:
        st.text_input("ID", key="new_task_id", placeholder="ID")
    with col1:
        st.text_input("Description", key="new_task_input", placeholder="Enter task description...")
    with col2:
        st.button("Add", on_click=add_task, use_container_width=True)

    # Filters
    with st.expander("🔎 Filters", expanded=False):
        col_f1, col_f2, col_f3 = st.columns([2, 1.5, 1.5])
        with col_f1:
            search_query = st.text_input("Search (ID or Description)", placeholder="Type to search...").lower()
        with col_f2:
            filter_categories = st.multiselect("Filter by Category", st.session_state.get('categories_list', DEFAULT_CATEGORIES))
        with col_f3:
            filter_date = st.date_input("Filter by Date Range", value=[], help="Select a range")
        
        # Calculate unique archived groups count
        archived_groups_count = 0
        if st.session_state.tasks:
             arch_pairs = set()
             for t in st.session_state.tasks:
                 if t.get('archived', False):
                     arch_pairs.add((t.get('id', '').strip(), t.get('name', '').strip()))
             archived_groups_count = len(arch_pairs)
        
        show_archived = st.checkbox(f"Show Archived Projects [{archived_groups_count}]", value=False)

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
                    h_cols = st.columns([2.5, 1.2, 1.5, 0.7, 0.7, 0.7, 0.7], vertical_alignment="center")
                    h_cols[0].markdown("**Category**")
                    h_cols[1].markdown("**Date**")
                    h_cols[2].markdown("**Duration**")
                    
                    for idx, task in g_tasks:
                        r_cols = st.columns([2.5, 1.2, 1.5, 0.7, 0.7, 0.7, 0.7], vertical_alignment="center")
                        
                        # Category
                        cat_name = task.get('category', '')
                        cat_desc = st.session_state.get('categories_desc', {}).get(cat_name, "")
                        if cat_desc:
                             r_cols[0].markdown(f"{cat_name}<br><span style='color:grey; font-size:0.8em;'>{cat_desc}</span>", unsafe_allow_html=True)
                        else:
                             r_cols[0].text(cat_name)
                        # Date
                        r_cols[1].text(task.get('created_date', '-'))
                        
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
                             r_cols[2].markdown(f"<span style='color:#28a745; font-weight:bold; font-family:monospace; font-size:1.1em;'>{dur_str}</span>", unsafe_allow_html=True)
                        else:
                             r_cols[2].markdown(f"<span style='font-family:monospace;'>{dur_str}</span>", unsafe_allow_html=True)
                        
                        # Buttons
                        btn_label = "⏹️" if is_running else "▶️"
                        btn_type = "primary" if is_running else "secondary"
                        # No more blocked button by status
                        
                        r_cols[3].button(
                            btn_label, 
                            key=f"btn_{idx}", 
                            type=btn_type, 
                            on_click=toggle_timer, 
                            args=(idx,), 
                            use_container_width=True,
                            disabled=show_archived # Disable play if archived
                        )
                        
                            
                        if r_cols[4].button("✏️", key=f"edit_btn_{idx}", on_click=edit_task_dialog, args=(idx,), use_container_width=True, disabled=show_archived):
                            pass

                        # Notes Button - Dynamic Icon
                        has_notes = bool(task.get('notes', '').strip())
                        note_icon = "📝" if has_notes else "📄"
                        
                        r_cols[5].button(note_icon, key=f"note_btn_{idx}", on_click=notes_dialog, args=(idx,), use_container_width=True)
                        
                        if r_cols[6].button("🗑️", key=f"del_{idx}", type="secondary", on_click=delete_confirmation, args=(idx,), use_container_width=True):
                            pass
                    
                    st.write("") # Spacer
                    
                    # Footer: Left = Add Category, Right = Archive
                    f_col1, f_col2 = st.columns([1, 1], vertical_alignment="bottom")
                    
                    with f_col1:
                        if not show_archived:
                            if st.button(f"➕ Add Category", key=f"add_sibling_{g_id}_{g_name}"):
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
        
        # Schema: ["ID", "Descripción", "Categoría", "Fecha Inicio", "Fecha Fin", "Tiempo"]
        # Convert 'Tiempo' (Seconds) to float
        df_log['Seconds'] = pd.to_numeric(df_log['Tiempo'], errors='coerce').fillna(0)
        df_log['Hours'] = df_log['Seconds'] / 3600.0
        
        # Convert Dates
        # Format in Sheet is usually DD/MM/YYYY or from epoch.
        # Actually in log_session we write "Date" column manually with DD/MM/YYYY or similar?
        # Wait, the new schema has "Fecha Inicio" which is likely a Timestamp or Date.
        # Let's check 'log_session'. It uses 'today_str' for Date, and start/end epoch.
        # Ah, 'log_session' writes: [id, name, cat_str, start_dt, end_dt, elapsed]
        # start_dt is datetime.fromtimestamp(start_epoch).strftime("%d/%m/%Y %H:%M:%S")
        
        # Parse 'Fecha Inicio' to datetime
        df_log['StartDT'] = pd.to_datetime(df_log['Fecha Inicio'], format="%d/%m/%Y %H:%M:%S", errors='coerce')
        # Fallback if format differs?
        
        df_log['Date'] = df_log['StartDT'].dt.date
        df_log['Hour'] = df_log['StartDT'].dt.hour
        
        # Filter Logic
        col_ctrl, _ = st.columns([1, 2])
        with col_ctrl:
            date_range = st.date_input("Filter Analytics by Date Range", value=[], key="video_analytics_range")
            
        if date_range:
            if len(date_range) == 2:
                s, e = date_range
                df_log = df_log[(df_log['Date'] >= s) & (df_log['Date'] <= e)]
            elif len(date_range) == 1:
                df_log = df_log[df_log['Date'] == date_range[0]]
                
        if df_log.empty:
            st.warning("No data for selected period.")
        else:
            # -------------------------------------------------------
            # Row 1: Daily Activity Trend (Bar Chart)
            # -------------------------------------------------------
            st.subheader("📅 Daily Activity Trend")
            daily_agg = df_log.groupby('Date')['Hours'].sum().reset_index()
            daily_agg['DateStr'] = daily_agg['Date'].astype(str)
            
            chart_daily = alt.Chart(daily_agg).mark_bar().encode(
                x=alt.X('DateStr', title='Date'),
                y=alt.Y('Hours', title='Total Hours'),
                tooltip=['DateStr', alt.Tooltip('Hours', format='.2f')],
                color=alt.value("#4C78A8")
            ).properties(height=300)
            
            st.altair_chart(chart_daily, use_container_width=True)
            st.markdown("---")

            # -------------------------------------------------------
            # Row 2: Hourly Productivity Heatmap
            # -------------------------------------------------------
            st.subheader("🔥 Peak Productivity Hours")
            # Group by Hour (0-23)
            hourly_agg = df_log.groupby('Hour')['Hours'].sum().reset_index()
            
            chart_hourly = alt.Chart(hourly_agg).mark_bar(color="#ff9f43").encode(
                x=alt.X('Hour', title='Hour of Day (0-23)', scale=alt.Scale(domain=[0, 23])),
                y=alt.Y('Hours', title='Total Hours Worked'),
                tooltip=['Hour', alt.Tooltip('Hours', format='.2f')]
            ).properties(height=250)
            
            st.altair_chart(chart_hourly, use_container_width=True)
            st.markdown("---")

            # -------------------------------------------------------
            # Row 3: Category Distribution
            # -------------------------------------------------------
            st.subheader("📊 Time Distribution by Category")
            cat_agg = df_log.groupby('Categoría')['Hours'].sum().reset_index()
            cat_agg = cat_agg.sort_values('Hours', ascending=False)
            
            base = alt.Chart(cat_agg).encode(theta=alt.Theta("Hours", stack=True))
            pie = base.mark_arc(outerRadius=120).encode(
                color=alt.Color("Categoría"),
                order=alt.Order("Hours", sort="descending"),
                tooltip=["Categoría", alt.Tooltip("Hours", format='.2f')]
            )
            text = base.mark_text(radius=140).encode(
                text=alt.Text("Hours", format=".1f"),
                order=alt.Order("Hours", sort="descending"),
                color=alt.value("white")  
            )
            st.altair_chart(pie + text, use_container_width=True)




with tab_logs:
    ensure_logs_loaded()
    
    if "logs_data" in st.session_state and isinstance(st.session_state.logs_data, pd.DataFrame):
        df_log = st.session_state.logs_data
        if not df_log.empty:
            # Show newest first
            st.dataframe(df_log, use_container_width=True)
        else:
            st.info("No logs found yet.")

# Auto-refresh if timer is running
if st.session_state.active_task_idx is not None:
    time.sleep(1)
    st.rerun()

