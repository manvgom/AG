import streamlit as st
import pandas as pd
import time
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import altair as alt

# Page configuration
st.set_page_config(page_title="Tasks Monitor", page_icon="⏱️", layout="wide")

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
# Added start_epoch for persistence, formatted_time for readability
REQUIRED_COLUMNS = ['id', 'name', 'category', 'formatted_time', 'start_epoch', 'notes', 'created_date', 'status']

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
                    vals = ws_cat.col_values(1) # List of categories
                    if not vals:
                         # Empty sheet -> Populate defaults
                         ws_cat.append_row(["Category Name"]) # Header (optional, usually I just list raw strings)
                         # Actually for col_values it grabs everything.
                         # Let's say Row 1 is NOT header to keep it simple, or Row 1 Is header.
                         # Plan: Row 1 is Header 'Category'.
                         ws_cat.clear()
                         ws_cat.append_row(["Category"])
                         for c in DEFAULT_CATEGORIES:
                             ws_cat.append_row([c])
                         st.session_state.categories_list = DEFAULT_CATEGORIES
                    else:
                        # vals[0] might be 'Category'
                        if vals and vals[0] == "Category":
                            loaded = vals[1:]
                        else:
                            loaded = vals
                        
                        # Filter empty
                        loaded = [x for x in loaded if x.strip()]
                        
                        if not loaded:
                            st.session_state.categories_list = DEFAULT_CATEGORIES
                        else:
                            st.session_state.categories_list = loaded
                except gspread.WorksheetNotFound:
                    # Create it
                    ws_cat = sh.add_worksheet(title="Categories", rows=100, cols=1)
                    ws_cat.append_row(["Category"])
                    for c in DEFAULT_CATEGORIES:
                        ws_cat.append_row([c])
                    st.session_state.categories_list = DEFAULT_CATEGORIES
            else:
                st.session_state.categories_list = DEFAULT_CATEGORIES
        except:
            st.session_state.categories_list = DEFAULT_CATEGORIES

def add_category(new_cat_name):
    if new_cat_name and new_cat_name not in st.session_state.categories_list:
        st.session_state.categories_list.append(new_cat_name)
        # Persist
        try:
            gc = get_gc()
            secrets = find_credentials(st.secrets)
            url = secrets.get("spreadsheet") if secrets else None
            if not url and "spreadsheet" in st.secrets: url = st.secrets["spreadsheet"]
            if url:
                sh = gc.open_by_url(url)
                ws = sh.worksheet("Categories")
                ws.append_row([new_cat_name])
                st.toast(f"Category '{new_cat_name}' added!", icon="✅")
        except:
             pass

def remove_category(cat_name):
    if cat_name in st.session_state.categories_list:
        st.session_state.categories_list.remove(cat_name)
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
                ws.append_row(["Category"])
                # Bulk update
                # Transforming list to list of lists [[cat1], [cat2]]
                rows = [[c] for c in st.session_state.categories_list]
                if rows:
                    ws.update(f"A2:A{len(rows)+1}", rows)
                st.toast(f"Category '{cat_name}' removed!", icon="🗑️")
        except Exception as e:
            st.warning(f"Error removing category: {e}")

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
                'status': status,
                'start_epoch': start_ep,
                'notes': str(row.get('notes', '')),
                'created_date': str(row.get('created_date', ''))
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
                task.get('status', 'To Do')
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

def log_session(task_name, category, elapsed_seconds, start_epoch, end_epoch):
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
            ws_logs = sh.add_worksheet(title="Logs", rows=1000, cols=8)
            # Headers with detailed info
            ws_logs.append_row([
                "Task Name", 
                "Category", 
                "Start Date", 
                "End Date", 
                "Start Time", 
                "End Time", 
                "Duration (s)", 
                "Duration (Formatted)"
            ])
            
        # Format Timestamps
        start_dt = datetime.fromtimestamp(start_epoch)
        end_dt = datetime.fromtimestamp(end_epoch)
        
        start_date_str = start_dt.strftime("%d/%m/%Y")
        end_date_str = end_dt.strftime("%d/%m/%Y")
        start_time_str = start_dt.strftime("%H:%M:%S")
        end_time_str = end_dt.strftime("%H:%M:%S")
        
        # Append log data
        ws_logs.append_row([
            task_name,
            category,
            start_date_str,
            end_date_str,
            start_time_str,
            end_time_str,
            elapsed_seconds,
            format_time(elapsed_seconds)
        ])
        
    except Exception as e:
        print(f"Log Error: {e}") # Silent fail in UI but print to console
        # st.warning(f"Could not log session: {e}")

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

def add_task():
    task_id = st.session_state.get("new_task_id", "").strip()
    task_name = st.session_state.get("new_task_input", "").strip()
    task_category = st.session_state.get("new_category_input", "") 
    
    if not task_id or not task_name or not task_category:
        st.toast("⚠️ Please fill in all fields (ID, Description, Category)", icon="⚠️")
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
        st.session_state.new_category_input = "" 
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
    
    if st.button("Add Category", type="primary", use_container_width=True):
        if new_cat:
            add_category(new_cat)
            st.rerun()
            
    st.markdown("---")
    st.markdown("##### Current Categories")
    
    if not st.session_state.categories_list:
        st.info("No categories found.")
    else:
        for cat in st.session_state.categories_list:
            c1, c2 = st.columns([4, 1], vertical_alignment="center")
            c1.text(cat)
            if c2.button("🗑️", key=f"rm_cat_dialog_{cat}"): # Changed key to avoid conflict if any phantom state
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
    
    # Initialize dialog state
    if 'show_cat_dialog' not in st.session_state:
        st.session_state.show_cat_dialog = False
        
    def open_cat_dialog():
        st.session_state.show_cat_dialog = True
    
    # Categories Button (Primary Config)
    st.button("⚙️ Categories", use_container_width=True, on_click=open_cat_dialog)

    if st.session_state.show_cat_dialog:
        manage_categories_dialog()
        
    # Logout (Bottom)
    if st.button("🔒 Logout", key="logout_btn", use_container_width=True):
        logout()

# Header
st.title("⏱️ Tasks Monitor")
st.markdown("---")

# Tabs
tab_tracker, tab_analytics, tab_logs = st.tabs(["⏱️ Tracker", "📊 Analytics", "📜 Logs"])

with tab_tracker:
    # Input Section
    # 4 columns: ID | Description | Category | Add
    col0, col1, col2, col3 = st.columns([1, 3, 2, 1], vertical_alignment="bottom")
    with col0:
        st.text_input("ID", key="new_task_id", placeholder="ID")
    with col1:
        st.text_input("Description", key="new_task_input", placeholder="Enter task description...")
    with col2:
        st.selectbox("Category", st.session_state.get('categories_list', DEFAULT_CATEGORIES), key="new_category_input")
    with col3:
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
                
            if match_search and match_cat and match_date:
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
                # Counter [X/Y]
                progress_str = f"[{completed_subtasks}/{total_subtasks}]"
                header_str = f"**{g_id if g_id else 'No ID'}** - {g_name}  (⏱️ {header_duration}) {progress_str}"
                
                if running_in_group:
                    header_str = "🟢 " + header_str
                
                # Render Group Expander
                # Default open if filtered or running
                is_expanded = (len(groups) == 1) or running_in_group
                
                with st.expander(header_str, expanded=is_expanded):
                    # Header row for the group content
                    # Col widths: Category, Date, Status, Duration, Action, Edit, Note, Del
                    h_cols = st.columns([2.5, 1.2, 1.5, 1.5, 0.7, 0.7, 0.7, 0.7], vertical_alignment="center")
                    h_cols[0].markdown("**Category**")
                    h_cols[1].markdown("**Date**")
                    h_cols[2].markdown("**Status**")
                    h_cols[3].markdown("**Duration**")
                    
                    for idx, task in g_tasks:
                        r_cols = st.columns([2.5, 1.2, 1.5, 1.5, 0.7, 0.7, 0.7, 0.7], vertical_alignment="center")
                        
                        # Category
                        r_cols[0].text(task.get('category', ''))
                        # Date
                        r_cols[1].text(task.get('created_date', '-'))
                        
                        # Status Logic
                        is_running = (idx == st.session_state.active_task_idx)
                        current_status = task.get('status', 'To Do')
                        
                        # Special "Doing" state
                        if is_running:
                            r_cols[2].markdown("**:orange[Doing ⚡]**")
                        else:
                            # Selectbox for status
                            # Find index of current status
                            try:
                                status_idx = STATUS_OPTIONS.index(current_status)
                            except:
                                status_idx = 0
                                
                            new_status = r_cols[2].selectbox(
                                "Status",
                                STATUS_OPTIONS,
                                index=status_idx,
                                key=f"status_sb_{idx}",
                                label_visibility="collapsed"
                            )
                            if new_status != current_status:
                                update_status(idx, new_status)
                                st.rerun()

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
                             r_cols[3].markdown(f"<span style='color:#28a745; font-weight:bold; font-family:monospace; font-size:1.1em;'>{dur_str}</span>", unsafe_allow_html=True)
                        else:
                             r_cols[3].markdown(f"<span style='font-family:monospace;'>{dur_str}</span>", unsafe_allow_html=True)
                        
                        # Buttons
                        btn_label = "⏹️" if is_running else "▶️"
                        btn_type = "primary" if is_running else "secondary"
                        btn_disabled = (not is_running) and (current_status == 'Done')
                        
                        r_cols[4].button(
                            btn_label, 
                            key=f"btn_{idx}", 
                            type=btn_type, 
                            on_click=toggle_timer, 
                            args=(idx,), 
                            use_container_width=True,
                            disabled=btn_disabled
                        )
                        
                        if r_cols[5].button("✏️", key=f"edit_btn_{idx}", on_click=edit_task_dialog, args=(idx,), use_container_width=True):
                            pass

                        r_cols[6].button("📄", key=f"note_btn_{idx}", on_click=toggle_notes, args=(idx,), use_container_width=True)
                        
                        if r_cols[7].button("🗑️", key=f"del_{idx}", type="secondary", on_click=delete_confirmation, args=(idx,), use_container_width=True):
                            pass
                            
                        # Notes Area
                        if st.session_state.active_note_idx == idx:
                            st.markdown(f"**Notes for: {task.get('category', '')}**")
                            st.text_area(
                                "Notes", 
                                value=task.get('notes', ''), 
                                key=f"note_content_{idx}",
                                on_change=update_notes,
                                label_visibility="collapsed",
                                placeholder="Details..."
                            )
                
        st.markdown("---")

with tab_analytics:
    if not st.session_state.tasks:
        st.info("No data available yet.")
    else:
        # Prepare Data
        df = pd.DataFrame(st.session_state.tasks)
        
        # Ensure total_seconds is numeric
        df['total_seconds'] = pd.to_numeric(df['total_seconds'], errors='coerce').fillna(0)
        # Convert to hours for charting
        df['Hours'] = df['total_seconds'] / 3600.0

        # Date Filtering Logic
        # Convert 'created_date' (DD/MM/YYYY) to datetime
        df['date_dt'] = pd.to_datetime(df['created_date'], format="%d/%m/%Y", errors='coerce')
        
        col_ctrl, _ = st.columns([1, 2])
        with col_ctrl:
            date_range = st.date_input("Filter Analytics by Date Range", value=[])
        
        if date_range:
            if len(date_range) == 2:
                start_d, end_d = date_range
                # Filter strictly by range (inclusive)
                mask = (df['date_dt'].dt.date >= start_d) & (df['date_dt'].dt.date <= end_d)
                df = df[mask]
                st.caption(f"Showing data from {start_d.strftime('%d/%m/%Y')} to {end_d.strftime('%d/%m/%Y')}")
            elif len(date_range) == 1:
                # Single date selected
                target_d = date_range[0]
                mask = (df['date_dt'].dt.date == target_d)
                df = df[mask]
                st.caption(f"Showing data for {target_d.strftime('%d/%m/%Y')}")

        if df.empty:
            st.warning("No data found for the selected date range.")
        else:
            # Chart 1: Time by Category
            st.subheader("Time by Category")
            # Aggregate for Category (Sum both Hours and Seconds for formatting)
            df_cat = df.groupby('category').agg({'total_seconds': 'sum'}).reset_index()
            df_cat['Hours'] = df_cat['total_seconds'] / 3600.0
            df_cat['Formatted Time'] = df_cat['total_seconds'].apply(format_time)
            
            # Sort descending
            df_cat = df_cat.sort_values(by="Hours", ascending=False)
            
            # Altair Donut Chart
            base = alt.Chart(df_cat).encode(theta=alt.Theta("Hours", stack=True))
            pie = base.mark_arc(outerRadius=120).encode(
                color=alt.Color("category"),
                order=alt.Order("Hours", sort="descending"),
                tooltip=["category", "Formatted Time", alt.Tooltip("Hours", format=".2f")]
            )
            text = base.mark_text(radius=140).encode(
                text=alt.Text("Formatted Time"),
                order=alt.Order("Hours", sort="descending"),
                color=alt.value("black")  
            )
            st.altair_chart(pie + text, use_container_width=True)

            st.markdown("---")

            # Chart 2: Time by Task ID
            st.subheader("Time by Task ID")
            # Aggregate by ID (or name if ID is missing)
            df['DisplayID'] = df['id'].astype(str).where(df['id'].astype(str) != "", df['name'])
            
            # Aggregate seconds first
            df_id = df.groupby('DisplayID').agg({'total_seconds': 'sum'}).reset_index()
            df_id['Hours'] = df_id['total_seconds'] / 3600.0
            df_id['Formatted Time'] = df_id['total_seconds'].apply(format_time)
            
            # Sort for Bar Chart
            df_id = df_id.sort_values(by="Hours", ascending=False)
            
            # Altair Bar Chart (Replacing st.bar_chart for better tooltip control)
            bar_chart = alt.Chart(df_id).mark_bar().encode(
                x=alt.X('Hours', title='Hours'),
                y=alt.Y('DisplayID', sort='-x', title='Task ID'),
                tooltip=['DisplayID', 'Formatted Time', alt.Tooltip('Hours', format='.2f')],
                color=alt.value("#1f77b4") # Standard Blue
            ).properties(
                height=max(300, len(df_id) * 30) # Dynamic height based on number of bars
            )
            st.altair_chart(bar_chart, use_container_width=True)





with tab_logs:
    # Load Logs Button (to avoid slow load on every refresh)
    if st.button("🔄 Refresh Logs"):
        st.session_state.logs_data = None
        
    if "logs_data" not in st.session_state or st.session_state.logs_data is None:
        # Load logic specific for logs
        try:
            gc = get_gc()
            secrets = find_credentials(st.secrets)
            url = secrets.get("spreadsheet") if secrets else None
            # Fallback
            if not url and "spreadsheet" in st.secrets: url = st.secrets["spreadsheet"]
            
            if url:
                sh = gc.open_by_url(url)
                try:
                    ws_logs = sh.worksheet("Logs")
                    data = ws_logs.get_all_values()
                    if data:
                        headers = data[0]
                        rows = data[1:]
                        st.session_state.logs_data = pd.DataFrame(rows, columns=headers)
                    else:
                        st.session_state.logs_data = pd.DataFrame()
                except gspread.WorksheetNotFound:
                    st.session_state.logs_data = pd.DataFrame() # Empty
                except Exception as e:
                    st.error(f"Error loading logs: {e}")
                    st.session_state.logs_data = pd.DataFrame()
        except:
            pass

    if "logs_data" in st.session_state and isinstance(st.session_state.logs_data, pd.DataFrame):
        df_log = st.session_state.logs_data
        if not df_log.empty:
            # Show newest first
            st.dataframe(df_log, use_container_width=True)
            
            # Optional: CSV Download for Logs
            csv_logs = df_log.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 Download Logs (CSV)",
                csv_logs,
                "session_logs.csv",
                "text/csv",
                key='download-logs'
            )
        else:
            st.info("No logs found yet.")

# Auto-refresh if timer is running
if st.session_state.active_task_idx is not None:
    time.sleep(1)
    st.rerun()

