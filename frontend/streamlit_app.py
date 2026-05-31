import streamlit as st
import sys
import os
from datetime import datetime
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.graph.orchestrator import orchestrator
from app.database.supabase_client import db
from app.models.schemas import ChatRequest
from app.database.redis_client import redis_client
from config import config
import uuid
from app.utils.helpers import build_graph_config
from app.utils.logger import read_recent_log_events
if "thread_id" not in st.session_state:
    st.session_state.thread_id = uuid.uuid4().hex
# ====================== CONFIG ======================
st.set_page_config(page_title="AI Team Task Agent", page_icon="🤖", layout="wide")
st.title("🤖 AI Team Task Management Agent")
st.markdown("**Hệ thống quản lý công việc nhóm thông minh**")

# ====================== SIDEBAR ======================
with st.sidebar:
    st.header("Thông tin")
    user_id = st.text_input("User ID (demo)", value="user-001")
    st.info("Demo Mode")
    
    if st.button("🔄 Reset Conversation"):
        st.session_state.messages = []
        st.rerun()
with st.sidebar:
    st.header("Background Jobs")
    
    if st.button("▶️ Start Reminder Job"):
        from app.jobs.reminder_job import reminder_job
        reminder_job.start_background(interval_seconds=1800)  # 30 phút
        st.success("Background Reminder Job đã bắt đầu!")
    
    if st.button("⏹️ Stop Reminder Job"):
        from app.jobs.reminder_job import reminder_job
        reminder_job.stop()
        st.info("Background Reminder Job đã dừng.")
    
    # Xem log reminder
    if st.button("📜 Xem Reminder Logs"):
        logs = redis_client.client.lrange("reminder_logs", 0, 19)
        if logs:
            st.write("**Recent Reminder Logs:**")
            for log in logs:
                data = json.loads(log)
                st.write(f"• {data['timestamp']}: {data['message']}")
        else:
            st.info("Chưa có log nào.")
# ====================== SESSION STATE ======================
if "messages" not in st.session_state:
    st.session_state.messages = []
if "current_project_id" not in st.session_state:
    st.session_state.current_project_id = None
if "pending_approval" not in st.session_state:
    st.session_state.pending_approval = None


def run_orchestrator(inputs: dict):
    """Chạy orchestrator và trả về kết quả."""
    return orchestrator.invoke(inputs,config=build_graph_config(st.session_state.thread_id))


def render_approval_panel(user_id: str):
    """Hiển thị và xử lý bước phê duyệt thủ công."""
    pending = st.session_state.pending_approval
    if not pending:
        return

    st.warning("⚠️ Cần phê duyệt thủ công cho rủi ro cao.")
    st.write(f"**Project ID:** {pending.get('project_id')}")
    if pending.get("message"):
        st.info(pending["message"])

    with st.expander("Xem các rủi ro cần duyệt", expanded=True):
        for risk in pending.get("risks", []):
            st.write(
                f"• **{risk.get('title', 'Unknown')}** — "
                f"Probability: {risk.get('probability', 'N/A')} | Impact: {risk.get('impact', 'N/A')}"
            )

    col_approve, col_reject = st.columns(2)

    with col_approve:
        if st.button("✅ Approve", key="approve_human_gate"):
            inputs = {
                "user_input": pending.get("source_input", "Phê duyệt rủi ro cao"),
                "user_id": user_id,
                "project_id": pending.get("project_id", st.session_state.current_project_id),
                "messages": [],
                "tasks": [],
                "risks": pending.get("risks", []),
                "current_phase": "monitoring",
                "needs_human_approval": True,
                "approval_response": "approved",
            }
            result = run_orchestrator(inputs)
            response_text = result.get("messages", [])[-1].get("content", "Đã duyệt.") if result.get("messages") else "Đã duyệt."
            st.session_state.messages.append({"role": "assistant", "content": response_text})
            st.session_state.pending_approval = None
            if result.get("project_id"):
                st.session_state.current_project_id = result.get("project_id")
            st.rerun()

    with col_reject:
        if st.button("⛔ Reject", key="reject_human_gate"):
            inputs = {
                "user_input": pending.get("source_input", "Từ chối rủi ro cao"),
                "user_id": user_id,
                "project_id": pending.get("project_id", st.session_state.current_project_id),
                "messages": [],
                "tasks": [],
                "risks": pending.get("risks", []),
                "current_phase": "monitoring",
                "needs_human_approval": True,
                "approval_response": "rejected",
            }
            result = run_orchestrator(inputs)
            response_text = result.get("messages", [])[-1].get("content", "Đã từ chối.") if result.get("messages") else "Đã từ chối."
            st.session_state.messages.append({"role": "assistant", "content": response_text})
            st.session_state.pending_approval = None
            if result.get("project_id"):
                st.session_state.current_project_id = result.get("project_id")
            st.rerun()

# ====================== TABS ======================
tab1, tab2 = st.tabs(["💬 Chat với AI Agent", "📊 Dashboard"])

# ====================== TAB 1: CHAT ======================
with tab1:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    render_approval_panel(user_id)

    if prompt := st.chat_input("Nhập lệnh ví dụ: Tạo project phát triển app bán hàng..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("AI Agent đang xử lý..."):
                try:
                    inputs = {
                        "user_input": prompt,
                        "user_id": user_id,
                        "project_id": st.session_state.current_project_id,
                        "messages": [],
                        "tasks": [],
                        "risks": [],
                        "current_phase": "planning"
                    }
                    result = run_orchestrator(inputs)
                    response_text = result.get("messages", [])[-1].get("content", "Đã xử lý xong.") \
                                   if result.get("messages") else "Tôi đã nhận được yêu cầu."
                    
                    st.markdown(response_text)
                    if result.get("project_id"):
                        st.session_state.current_project_id = result.get("project_id")

                    if result.get("needs_human_approval") and not result.get("approval_response"):
                        st.session_state.pending_approval = {
                            "project_id": result.get("project_id", st.session_state.current_project_id),
                            "risks": result.get("risks", []),
                            "message": response_text,
                            "source_input": prompt,
                        }
                    else:
                        st.session_state.pending_approval = None
                    
                    st.session_state.messages.append({"role": "assistant", "content": response_text})
                except Exception as e:
                    st.error(f"Lỗi: {str(e)}")

# ====================== TAB 2: DASHBOARD ======================
with tab2:
    st.header("📊 Dashboard")
    subtab1, subtab2, subtab3, subtab4 = st.tabs(["📈 Tổng quan", "👥 Quản lý Team", "⚠️ Rủi Ro", "📊 System Monitoring"])

    # ==================== SUBTAB 1: TỔNG QUAN ====================
    with subtab1:
        if st.session_state.current_project_id:
            project = db.get_project(st.session_state.current_project_id)
            tasks = db.get_tasks_by_project(st.session_state.current_project_id) or []
            
            col1, col2, col3 = st.columns(3)
            with col1: st.metric("Tiến độ", f"{project.get('progress_percentage', 0)}%", "📈")
            with col2: st.metric("Tổng Task", len(tasks))
            with col3: st.metric("Chưa hoàn thành", len([t for t in (tasks or []) if t.get('status') != 'Done']))
            
            st.subheader("Danh sách Task")
            for task in (tasks or [])[:8]:
                st.write(f"• **{task.get('title','Untitled')}** — {task.get('status','Unknown')} (Hạn: {task.get('due_date')})")
        else:
            st.info("Chưa có project nào. Hãy tạo project ở tab Chat.")

    # ==================== SUBTAB 2: QUẢN LÝ TEAM ====================
    with subtab2:
        st.subheader("👥 Quản lý Team")

        col1, col2 = st.columns([1, 1])

        # --- Tạo Team Mới (Toàn cục) ---
        with col1:
            st.subheader("➕ Tạo User / Team Mới")
            new_name = st.text_input("Tên thành viên")
            new_email = st.text_input("Email")
            new_role = st.selectbox("Vai trò", ["leader", "member"])
            new_skill = st.text_input("Kỹ năng nổi bật", "Backend, Frontend...")

            if st.button("Tạo User Mới"):
                if new_name and new_email:
                    user_data = {
                        "name": new_name,
                        "email": new_email,
                        "role": new_role,
                        "skill_notes": new_skill
                    }
                    db.create_user(user_data)
                    st.success(f"✅ Đã tạo user: {new_name}")
                    st.rerun()
                else:
                    st.error("Vui lòng nhập tên và email")

        # --- Quản lý Thành viên trong Project ---
        with col2:
            st.subheader("👤 Thành viên trong Project")
            if st.session_state.current_project_id:
                project = db.get_project(st.session_state.current_project_id)
                st.write(f"**Dự án:** {project['name']}")

                # Lấy danh sách thành viên
                members = db.get_project_members(st.session_state.current_project_id) or []

                for member in (members or []):
                    col_a, col_b = st.columns([4, 1])
                    with col_a:
                        st.write(f"• **{member.get('name','Unknown')}** - {member.get('role_in_project')} ({member.get('workload_capacity',0)}%)")
                    with col_b:
                        if st.button("🗑️", key=f"del_{member.get('project_member_id')}"):
                            db.delete_project_member(member.get('project_member_id'))
                            st.success("Đã xóa thành viên")
                            st.rerun()
            else:
                st.warning("Chưa có project. Hãy tạo project trước.")

    # ==================== SUBTAB 3: RỦI RO ====================
    with subtab3:
        st.subheader("⚠️ Rủi Ro Dự Án")
        if st.session_state.current_project_id:
            risks = db.get_risks_by_project(st.session_state.current_project_id) or []
            for risk in (risks or []):
                score = risk.get('risk_score', 0) or 0
                color = "🔴" if score >= 7 else "🟠" if score >= 4 else "🟢"
                st.write(f"{color} **{risk.get('title','Untitled')}** (Score: {score}) - {risk.get('status','Unknown')}")
        else:
            st.info("Chưa có project.")
    # ==================== SUBTAB 4: SYSTEM MONITORING ====================
    with subtab4:
        st.subheader("📊 System Monitoring (Redis)")

        col1, col2 = st.columns(2)

        with col1:
            st.metric("Redis Status", "🟢 Connected" if redis_client.client else "🔴 Disconnected")

            # Cache Statistics
            try:
                cache_keys = redis_client.client.keys("planner:*") + redis_client.client.keys("risk:*")
                st.metric("Total Cached Items", len(cache_keys))
            except:
                st.metric("Total Cached Items", "N/A")

        with col2:
            # Recent Reminder Logs
            st.subheader("Recent Reminder Logs")
            logs = redis_client.client.lrange("reminder_logs", 0, 9)
            if logs:
                for log in logs:
                    data = json.loads(log)
                    st.caption(f"{data['timestamp'][:16]} - {data['message']}")
            else:
                st.info("Chưa có reminder log nào.")

        st.divider()

        # Button controls
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            if st.button("🔄 Clear All Cache"):
                redis_client.clear_cache()
                st.success("Đã xóa toàn bộ cache!")
                st.rerun()

        with col_b:
            if st.button("📋 View All Cache Keys"):
                try:
                    keys = redis_client.client.keys("*")
                    st.write(keys[:30])  # Hiển thị 30 keys đầu
                except:
                    st.error("Không thể lấy keys")

        with col_c:
            if st.button("📈 Refresh Metrics"):
                st.rerun()

        st.divider()

        st.subheader("🧭 Orchestrator Event Log")
        log_limit = st.slider("Số dòng log gần nhất", min_value=10, max_value=100, value=25, step=5)
        event_filter = st.text_input("Lọc theo event prefix", value="")

        events = read_recent_log_events(limit=log_limit, event_prefix=event_filter.strip() or None)
        if events:
            st.caption(f"Hiển thị {len(events)} event gần nhất từ logs/app.log")
            for event in events:
                with st.expander(f"{event.get('event', 'unknown')} | {event.get('ts', '')}"):
                    st.json(event)
        else:
            st.info("Chưa có log orchestrator nào khớp bộ lọc.")

st.caption("AI Team Task Agent | Version 1.0 | Deploy Ready")