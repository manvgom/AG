import streamlit as st
import pandas as pd
import time
import os
from datetime import datetime

# Page configuration
st.set_page_config(page_title="Time Tracker", page_icon="⏱️", layout="wide")

# Constants
TASKS_FILE = 'tasks.csv'

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

# Persistence Functions
def load_tasks():
    if os.path.exists(TASKS_FILE):
        try:
            df = pd.read_csv(TASKS_FILE)
            return df.to_dict('records')
        except Exception:
            return []
    return []

def save_tasks():
    if st.session_state.tasks:
        df = pd.DataFrame(st.session_state.tasks)
        df.to_csv(TASKS_FILE, index=False)
    else:
        # Save empty dataframe to keep structure
        df = pd.DataFrame(columns=['name', 'total_seconds', 'status'])
        df.to_csv(TASKS_FILE, index=False)

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
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

# Header
st.title("⏱️ AG Time Tracker")
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
    st.info("No tasks added yet. Start by adding one above!")
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
    # Logic to ensure we don't spam updates unnecessarily for static views
    if st.session_state.active_task_idx is not None:
        time.sleep(1)
        st.rerun()
