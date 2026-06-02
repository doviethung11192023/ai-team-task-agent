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


def _format_project_option(project: dict) -> str:
    return (
        f"{project.get('name', 'Untitled')} "
        f"[{project.get('status', 'Unknown')}] "
        f"{project.get('progress_percentage', 0)}% "
        f"| {project.get('project_id')}"
    )


def _get_projects_for_scope(selected_scope: str, selected_user_id: str):
    if selected_scope == "Tất cả":
        return db.get_projects() or []
    if not selected_user_id:
        return []
    return db.get_projects_by_owner(selected_user_id) or []


def _build_dashboard_snapshot(project_id: str) -> dict:
    project = db.get_project(project_id) or {}
    tasks = db.get_tasks_by_project(project_id) or []
    members = db.get_project_members(project_id) or []
    assignments = db.get_task_assignments_by_project(project_id) or []
    status_summary = db.get_task_status_summary(project_id) or {}
    overdue_tasks = db.get_overdue_tasks(project_id) or []
    risks = db.get_risks_by_project(project_id) or []
    risk_summary = db.get_risk_summary(project_id) or {}
    workload = db.get_member_workload(project_id) or []
    audit_logs = db.get_audit_logs(project_id=project_id, limit=30) or []

    assignees_by_task = {}
    for assignment in assignments:
        task_id = assignment.get("task_id")
        assignee_name = assignment.get("assignee_name") or "Unknown"
        if not task_id:
            continue
        assignees_by_task.setdefault(task_id, []).append(assignee_name)

    return {
        "project": project,
        "tasks": tasks,
        "members": members,
        "assignments": assignments,
        "status_summary": status_summary,
        "overdue_tasks": overdue_tasks,
        "risks": risks,
        "risk_summary": risk_summary,
        "workload": workload,
        "audit_logs": audit_logs,
        "assignees_by_task": assignees_by_task,
    }


if "thread_id" not in st.session_state:
    st.session_state.thread_id = uuid.uuid4().hex
if "selected_user_id" not in st.session_state:
    st.session_state.selected_user_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "current_project_id" not in st.session_state:
    st.session_state.current_project_id = None
if "pending_approval" not in st.session_state:
    st.session_state.pending_approval = None
if "project_scope" not in st.session_state:
    st.session_state.project_scope = "Theo user"
if "dashboard_snapshot" not in st.session_state:
    st.session_state.dashboard_snapshot = None
if "dashboard_snapshot_project_id" not in st.session_state:
    st.session_state.dashboard_snapshot_project_id = None
# ====================== CONFIG ======================
st.set_page_config(page_title="AI Team Task Agent", page_icon="🤖", layout="wide")
st.title("🤖 AI Team Task Management Agent")
st.markdown("**Hệ thống quản lý công việc nhóm thông minh**")

# ====================== SIDEBAR ======================
with st.sidebar:
    st.header("Thông tin")

    available_users = db.get_users() or []
    user_options = [f"{user.get('name','Unknown')} ({user.get('email','')}) | {user.get('user_id')}" for user in available_users]
    user_map = {option: user for option, user in zip(user_options, available_users)}

    if user_options:
        default_index = 0
        if st.session_state.selected_user_id:
            for index, user in enumerate(available_users):
                if user.get("user_id") == st.session_state.selected_user_id:
                    default_index = index
                    break
        selected_label = st.selectbox("Chọn user", user_options, index=default_index)
        user_id = user_map[selected_label]["user_id"]
        st.session_state.selected_user_id = user_id
        st.caption(f"Đang dùng: {user_map[selected_label].get('name')} | {user_id}")
    else:
        user_id = st.text_input("User ID (fallback)")
        st.warning("Chưa có user nào trong DB, đang dùng input fallback.")

    st.divider()
    st.subheader("📁 Chọn dự án")
    selected_scope = st.radio(
        "Phạm vi",
        options=["Theo user", "Tất cả"],
        index=0 if st.session_state.project_scope == "Theo user" else 1,
        horizontal=True,
    )
    st.session_state.project_scope = selected_scope

    projects = _get_projects_for_scope(selected_scope, st.session_state.selected_user_id)
    project_options = [_format_project_option(project) for project in projects]
    project_map = {option: project for option, project in zip(project_options, projects)}

    if projects:
        selected_index = 0
        current_project_id = st.session_state.current_project_id
        if current_project_id:
            for index, project in enumerate(projects):
                if project.get("project_id") == current_project_id:
                    selected_index = index
                    break

        selected_project_label = st.selectbox(
            "Dự án hiện tại",
            options=project_options,
            index=selected_index,
            key="dashboard_project_select",
        )
        selected_project = project_map[selected_project_label]
        selected_project_id = selected_project.get("project_id")
        if selected_project_id != st.session_state.current_project_id:
            st.session_state.dashboard_snapshot = None
        st.session_state.current_project_id = selected_project_id
    else:
        st.session_state.current_project_id = None
        st.session_state.dashboard_snapshot = None
        st.session_state.dashboard_snapshot_project_id = None
        st.info("Không có dự án trong phạm vi đã chọn.")

    refresh_projects_clicked = st.button("🔄 Refresh Project List", use_container_width=True)
    if refresh_projects_clicked:
        st.session_state.dashboard_snapshot = None
        st.rerun()
    
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
            st.session_state.dashboard_snapshot = None
            st.session_state.dashboard_snapshot_project_id = None
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
            st.session_state.dashboard_snapshot = None
            st.session_state.dashboard_snapshot_project_id = None
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
                        "current_phase": "ready"
                    }
                    result = run_orchestrator(inputs)
                    response_text = result.get("messages", [])[-1].get("content", "Đã xử lý xong.") \
                                   if result.get("messages") else "Tôi đã nhận được yêu cầu."
                    
                    st.markdown(response_text)
                    if result.get("project_id"):
                        st.session_state.current_project_id = result.get("project_id")
                    st.session_state.dashboard_snapshot = None
                    st.session_state.dashboard_snapshot_project_id = None

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
    selected_project_id = st.session_state.current_project_id
    dashboard_data = None
    if selected_project_id:
        needs_refresh = (
            st.session_state.dashboard_snapshot is None
            or st.session_state.dashboard_snapshot_project_id != selected_project_id
        )
        if needs_refresh:
            st.session_state.dashboard_snapshot = _build_dashboard_snapshot(selected_project_id)
            st.session_state.dashboard_snapshot_project_id = selected_project_id
        dashboard_data = st.session_state.dashboard_snapshot

    subtab1, subtab2, subtab3, subtab4 = st.tabs(["📈 Tổng quan", "👥 Quản lý Team", "⚠️ Rủi Ro", "📊 System Monitoring"])

    # ==================== SUBTAB 1: TỔNG QUAN ====================
    with subtab1:
        if dashboard_data:
            project = dashboard_data.get("project") or {}
            tasks = dashboard_data.get("tasks") or []
            status_summary = dashboard_data.get("status_summary") or {}
            overdue_tasks = dashboard_data.get("overdue_tasks") or []
            assignees_by_task = dashboard_data.get("assignees_by_task") or {}
            
            col1, col2, col3, col4 = st.columns(4)
            with col1: st.metric("Tiến độ", f"{project.get('progress_percentage', 0)}%", "📈")
            with col2: st.metric("Tổng Task", len(tasks))
            with col3: st.metric("Chưa hoàn thành", len([t for t in (tasks or []) if t.get('status') != 'Done']))
            with col4: st.metric("Quá hạn", len(overdue_tasks))

            st.caption(
                "Todo: {todo} | InProgress: {in_progress} | Review: {review} | Done: {done}".format(
                    todo=status_summary.get("Todo", 0),
                    in_progress=status_summary.get("InProgress", 0),
                    review=status_summary.get("Review", 0),
                    done=status_summary.get("Done", 0),
                )
            )
            
            st.subheader("Danh sách Task")
            task_rows = []
            for task in tasks:
                task_id = task.get("task_id")
                task_rows.append(
                    {
                        "Task": task.get("title", "Untitled"),
                        "Status": task.get("status", "Unknown"),
                        "Priority": task.get("priority", "Medium"),
                        "Due Date": task.get("due_date"),
                        "Assignees": ", ".join(assignees_by_task.get(task_id, [])) or "Unassigned",
                    }
                )

            if task_rows:
                st.dataframe(task_rows, use_container_width=True, hide_index=True)
            else:
                st.info("Project này chưa có task.")
        else:
            st.info("Chưa có project nào trong phạm vi hiện tại. Hãy chọn scope khác hoặc tạo project mới ở tab Chat.")

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
            if dashboard_data:
                project = dashboard_data.get("project") or {}
                st.write(f"**Dự án:** {project.get('name', 'Untitled')}")

                # Lấy danh sách thành viên
                members = dashboard_data.get("members") or []
                workload = dashboard_data.get("workload") or []

                for member in (members or []):
                    col_a, col_b = st.columns([4, 1])
                    with col_a:
                        st.write(f"• **{member.get('name','Unknown')}** - {member.get('role_in_project')} ({member.get('workload_capacity',0)}%)")
                    with col_b:
                        if st.button("🗑️", key=f"del_{member.get('project_member_id')}"):
                            db.delete_project_member(member.get('project_member_id'))
                            st.success("Đã xóa thành viên")
                            st.session_state.dashboard_snapshot = None
                            st.rerun()

                st.subheader("📌 Workload Summary")
                workload_rows = []
                for row in workload:
                    workload_rows.append(
                        {
                            "Member": row.get("name"),
                            "Role": row.get("role_in_project"),
                            "Capacity (%)": row.get("workload_capacity", 0),
                            "Assigned Tasks": row.get("assigned_task_count", 0),
                            "Estimated Hours": row.get("total_estimated_hours", 0),
                            "Actual Hours": row.get("total_actual_hours", 0),
                        }
                    )
                if workload_rows:
                    st.dataframe(workload_rows, use_container_width=True, hide_index=True)
            else:
                st.warning("Chưa có project. Hãy tạo project trước.")

    # ==================== SUBTAB 3: RỦI RO ====================
    with subtab3:
        st.subheader("⚠️ Rủi Ro Dự Án")
        if dashboard_data:
            risks = dashboard_data.get("risks") or []
            risk_summary = dashboard_data.get("risk_summary") or {}
            col_a, col_b, col_c, col_d = st.columns(4)
            with col_a:
                st.metric("Tổng Risks", risk_summary.get("total_risks", 0))
            with col_b:
                st.metric("Open", risk_summary.get("open_risks", 0))
            with col_c:
                st.metric("Mitigating", risk_summary.get("mitigating_risks", 0))
            with col_d:
                st.metric("Avg Score", round(float(risk_summary.get("avg_risk_score", 0) or 0), 2))

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
                cache_keys = redis_client.client.keys("task_divider:*") + redis_client.client.keys("risk:*")
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

        if dashboard_data:
            st.divider()
            st.subheader("🧾 Audit Timeline")
            audit_logs = dashboard_data.get("audit_logs") or []
            if audit_logs:
                for log in audit_logs[:20]:
                    st.write(
                        "• {time} | {action} | {entity}".format(
                            time=log.get("created_at"),
                            action=log.get("action"),
                            entity=log.get("entity_type") or "Unknown",
                        )
                    )
            else:
                st.info("Chưa có audit log cho project này.")

st.caption("AI Team Task Agent | Version 1.0 | Deploy Ready")