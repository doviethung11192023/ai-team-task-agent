from typing import TypedDict, Annotated, List, Optional
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
import time

from ..models.schemas import ProjectState
# Agents are imported lazily inside node functions to avoid heavy import-time dependencies
from ..tools.task_tools import create_project_tool
from ..utils.helpers import log_audit
from ..utils.logger import get_logger, log_event, summarize_graph_state, truncate_text, summarize_sequence
from config import config
import os
from langsmith import traceable

HIGH_RISK_THRESHOLD = 7
MAX_MESSAGE_HISTORY = 20

# LangSmith tracing environment variables are set only when enabled in config
# to avoid external network calls during tests or local runs.


logger = get_logger("app.graph.orchestrator")


CREATE_INTENT_KEYWORDS = (
    "tạo project",
    "tao project",
    "tạo dự án",
    "tao du an",
    "dự án mới",
    "du an moi",
    "project mới",
    "project moi",
    "new project",
    "create project",
    "start project",
    "khởi tạo",
    "khoi tao",
    "lập project",
    "lap project",
)


def is_create_project_intent(user_input: str) -> bool:
    normalized_input = (user_input or "").lower()
    return any(keyword in normalized_input for keyword in CREATE_INTENT_KEYWORDS)


def normalize_agent_result(result):
    """Chuyển AgentResponse hoặc object tương tự về dict thuần."""
    if isinstance(result, dict):
        return result
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if hasattr(result, "dict"):
        return result.dict()
    return {"response": str(result)}


def merge_messages(existing: Optional[List[dict]], new: Optional[List[dict]]) -> List[dict]:
    existing_messages = list(existing or [])
    new_messages = list(new or [])

    if not existing_messages:
        combined = new_messages
    elif not new_messages:
        combined = existing_messages
    elif len(new_messages) >= len(existing_messages) and new_messages[: len(existing_messages)] == existing_messages:
        combined = new_messages
    elif len(existing_messages) >= len(new_messages) and existing_messages[: len(new_messages)] == new_messages:
        combined = existing_messages
    else:
        combined = existing_messages + new_messages

    return combined[-MAX_MESSAGE_HISTORY:]

# ====================== STATE DEFINITION ======================
class AgentState(TypedDict):
    """State chính của LangGraph - Đây là "bộ nhớ" của hệ thống"""
    user_input: str
    user_id: str
    project_id: Optional[str]
    
    # Messages & History
    messages: Annotated[List[dict], merge_messages]
    
    # Project Data
    project_data: Optional[dict]
    tasks: List[dict]
    risks: List[dict]
    
    # Control Flow
    next_step: str
    needs_human_approval: bool
    approval_response: Optional[str]  # "approved" or "rejected"
    
    # Status
    current_phase: str  # planning, risk_assessment, execution, monitoring
    error: Optional[str]


# ====================== NODES (Các Agent/Function) ======================

def supervisor_node(state: AgentState) -> AgentState:
    """Orchestrator - Quyết định bước tiếp theo"""
    started_at = time.perf_counter()
    log_event(
        logger,
        "supervisor.enter",
        user_id=state.get("user_id"),
        project_id=state.get("project_id"),
        input_preview=truncate_text(state.get("user_input"), 180),
        state=summarize_graph_state(state),
    )

    route_reason = "default"
    if state.get("needs_human_approval") and state.get("approval_response") not in {"approved", "rejected"}:
        state["next_step"] = "human_approval"
        route_reason = "approval_pending"
        log_event(logger, "supervisor.route", decision=state["next_step"], reason=route_reason, state=summarize_graph_state(state))
        log_event(logger, "supervisor.exit", elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2), state=summarize_graph_state(state))
        return state

    if state.get("approval_response") in {"approved", "rejected"}:
        state["next_step"] = "human_approval"
        route_reason = "approval_response"
        log_event(logger, "supervisor.route", decision=state["next_step"], reason=route_reason, state=summarize_graph_state(state))
        log_event(logger, "supervisor.exit", elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2), state=summarize_graph_state(state))
        return state

    user_input = state["user_input"].lower()

    if not state.get("project_id"):
        if is_create_project_intent(user_input):
            state["next_step"] = "planner"
            route_reason = "planner_forced_null_project_id_create_intent"
        else:
            state["next_step"] = "end"
            state["messages"].append(
                {
                    "role": "assistant",
                    "content": "Vui lòng chọn một project có sẵn ở sidebar Dashboard hoặc yêu cầu tạo project mới.",
                }
            )
            route_reason = "missing_project_id_require_dashboard_selection"

        log_event(logger, "supervisor.route", decision=state["next_step"], reason=route_reason, state=summarize_graph_state(state))
        log_event(logger, "supervisor.exit", elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2), state=summarize_graph_state(state))
        return state
    
    if is_create_project_intent(user_input):
        state["current_phase"] = "planning"
        state["next_step"] = "planner"
        route_reason = "create_project_keyword"
    elif "update" in user_input or "tiến độ" in user_input:
        state["current_phase"] = "tracking"
        state["next_step"] = "progress_tracker"
        route_reason = "progress_keyword"
    elif "rủi ro" in user_input:
        state["next_step"] = "risk_assessment"
        route_reason = "risk_keyword"
    else:
        # Default flow
        if state.get("current_phase") == "planning":
            state["next_step"] = "task_divider"
            route_reason = "planning_default"
        else:
            state["next_step"] = "planner"
            route_reason = "fallback_planner"
    
    log_event(logger, "supervisor.route", decision=state["next_step"], reason=route_reason, state=summarize_graph_state(state))
    log_event(logger, "supervisor.exit", elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2), state=summarize_graph_state(state))
    return state


def planner_node(state: AgentState) -> AgentState:
    """Gọi Planner Agent"""
    from app.agents.planner_agent import planner_agent
    started_at = time.perf_counter()
    log_event(logger, "planner_node.enter", state=summarize_graph_state(state))
    result = normalize_agent_result(planner_agent(state["user_input"], state["user_id"], state.get("project_data")))
    state["messages"].append({"role": "assistant", "content": result["response"]})
    state["project_data"] = result.get("project_data") or {}
    state["project_id"] = result.get("project_id")
    state["tasks"] = (state.get("project_data") or {}).get("tasks") or []
    state["risks"] = (state.get("project_data") or {}).get("initial_risks") or state.get("risks", [])
    
    log_audit("create_project", "Project", state.get("project_id"), state["user_id"], result)
    log_event(
        logger,
        "planner_node.exit",
        elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2),
        project_id=state.get("project_id"),
        project_name=(state.get("project_data") or {}).get("project_name") or (state.get("project_data") or {}).get("name"),
        state=summarize_graph_state(state),
    )
    return state


def task_divider_node(state: AgentState) -> AgentState:
    """Phân chia task và gán người"""
    from app.agents.task_divider import task_divider_agent
    started_at = time.perf_counter()
    log_event(logger, "task_divider_node.enter", state=summarize_graph_state(state))
    if not state.get("project_id"):
        message = "Chưa có project_id, bỏ qua task divider để tránh lỗi DB."
        state["messages"].append({"role": "assistant", "content": message})
        log_event(logger, "task_divider_node.skip", level="warning", reason="missing_project_id", state=summarize_graph_state(state))
        return state
    result = normalize_agent_result(task_divider_agent(
        state["project_id"], 
        state["project_data"], 
        state.get("tasks", [])
    ))
    state["tasks"] = result.get("tasks") or []
    state["messages"].append({"role": "assistant", "content": result["response"]})
    log_event(
        logger,
        "task_divider_node.exit",
        elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2),
        tasks_summary=summarize_sequence(state.get("tasks"), sample_key="task_title"),
        state=summarize_graph_state(state),
    )
    return state


def progress_tracker_node(state: AgentState) -> AgentState:
    """Theo dõi và cập nhật tiến độ"""
    from app.agents.progress_tracker import progress_tracker_agent
    started_at = time.perf_counter()
    log_event(logger, "progress_tracker_node.enter", state=summarize_graph_state(state))
    if not state.get("project_id"):
        message = "Chưa có project_id, bỏ qua progress tracker để tránh lỗi DB."
        state["messages"].append({"role": "assistant", "content": message})
        log_event(logger, "progress_tracker_node.skip", level="warning", reason="missing_project_id", state=summarize_graph_state(state))
        return state
    result = normalize_agent_result(progress_tracker_agent(state["project_id"], state.get("user_input")))
    state["messages"].append({"role": "assistant", "content": result["response"]})
    log_event(
        logger,
        "progress_tracker_node.exit",
        elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2),
        response_preview=truncate_text(result.get("response"), 180),
        state=summarize_graph_state(state),
    )
    return state


def risk_assessment_node(state: AgentState) -> AgentState:
    """Quản lý rủi ro"""
    from app.agents.risk_agent import risk_agent
    started_at = time.perf_counter()
    log_event(logger, "risk_assessment_node.enter", state=summarize_graph_state(state))
    if not state.get("project_id"):
        message = "Chưa có project_id, bỏ qua risk assessment để tránh lỗi DB."
        state["messages"].append({"role": "assistant", "content": message})
        log_event(logger, "risk_assessment_node.skip", level="warning", reason="missing_project_id", state=summarize_graph_state(state))
        return state
    result = normalize_agent_result(risk_agent(state["project_id"], state.get("project_data"), state.get("tasks")))
    state["risks"] = result.get("risks") or []
    state["needs_human_approval"] = any(risk_requires_approval(risk) for risk in (state["risks"] or []))
    state["approval_response"] = None if state["needs_human_approval"] else state.get("approval_response")
    state["next_step"] = "human_approval" if state["needs_human_approval"] else "reminder"
    state["messages"].append({"role": "assistant", "content": result["response"]})
    log_event(
        logger,
        "risk_assessment_node.exit",
        elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2),
        risks_summary=summarize_sequence(state.get("risks"), sample_key="title"),
        needs_human_approval=state.get("needs_human_approval"),
        state=summarize_graph_state(state),
    )
    return state


def reminder_node(state: AgentState) -> AgentState:
    """Nhắc deadline"""
    from app.agents.reminder_agent import reminder_agent
    started_at = time.perf_counter()
    log_event(logger, "reminder_node.enter", state=summarize_graph_state(state))
    # Prevent repeated re-entry to this node within the same invoke
    visited = state.get("_visited_nodes") or []
    if "reminder" in visited:
        log_event(logger, "reminder_node.already_visited", state=summarize_graph_state(state))
        state["next_step"] = "end"
        return state
    visited.append("reminder")
    state["_visited_nodes"] = visited
    result = normalize_agent_result(reminder_agent(state.get("project_id")))
    state["messages"].append({"role": "assistant", "content": result["response"]})
    log_event(
        logger,
        "reminder_node.exit",
        elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2),
        response_preview=truncate_text(result.get("response"), 180),
        state=summarize_graph_state(state),
    )
    # Ensure we don't loop back into reminder repeatedly
    state["next_step"] = "end"
    return state


def human_approval_node(state: AgentState) -> AgentState:
    """Human-in-the-Loop"""
    started_at = time.perf_counter()
    log_event(logger, "human_approval_node.enter", state=summarize_graph_state(state))
    approval_response = state.get("approval_response")

    if approval_response == "approved":
        state["needs_human_approval"] = False
        state["messages"].append({
            "role": "assistant",
            "content": "✅ Đã được duyệt thủ công. Tiếp tục sang bước nhắc nhở và theo dõi."
        })
    elif approval_response == "rejected":
        state["needs_human_approval"] = False
        state["messages"].append({
            "role": "assistant",
            "content": "⛔ Yêu cầu đã bị từ chối. Quy trình dừng tại bước phê duyệt."
        })
    else:
        state["messages"].append({
            "role": "assistant",
            "content": "⚠️ Có rủi ro cao cần phê duyệt thủ công. Hãy Approve hoặc Reject trước khi tiếp tục."
        })
    log_event(
        logger,
        "human_approval_node.exit",
        elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2),
        state=summarize_graph_state(state),
    )
    return state


def risk_requires_approval(risk: dict) -> bool:
    """Xác định rủi ro nào cần phê duyệt thủ công."""
    risk_score = risk.get("risk_score")
    if risk_score is not None:
        try:
            return int(risk_score) >= HIGH_RISK_THRESHOLD
        except (TypeError, ValueError):
            return False

    probability = str(risk.get("probability", "")).lower()
    impact = str(risk.get("impact", "")).lower()
    return probability == "high" and impact == "high"


# ====================== CONDITIONAL EDGE ======================

def route_next(state: AgentState) -> str:
    """Routing logic"""
    next_step = state.get("next_step")

    if state.get("needs_human_approval") and state.get("approval_response") not in {"approved", "rejected"}:
        decision = "human_approval"
        log_event(logger, "route_next", decision=decision, state=summarize_graph_state(state))
        return decision
    
    if next_step == "planner":
        decision = "planner"
    elif next_step == "task_divider":
        decision = "task_divider"
    elif next_step == "progress_tracker":
        decision = "progress_tracker"
    elif next_step == "risk_assessment":
        decision = "risk_assessment"
    elif next_step == "human_approval":
        decision = "human_approval"
    elif next_step == "end":
        decision = END
    else:
        decision = END

    log_event(logger, "route_next", decision=decision, state=summarize_graph_state(state))
    return decision


def route_after_risk(state: AgentState) -> str:
    """Routing sau khi đánh giá rủi ro."""
    if state.get("approval_response") == "rejected":
        decision = END
    elif state.get("needs_human_approval"):
        decision = "human_approval"
    else:
        decision = "reminder"

    log_event(logger, "route_after_risk", decision=decision, state=summarize_graph_state(state))
    return decision


def route_after_approval(state: AgentState) -> str:
    """Routing sau khi phê duyệt thủ công."""
    if state.get("approval_response") == "approved":
        decision = "reminder"
    else:
        decision = END

    log_event(logger, "route_after_approval", decision=decision, state=summarize_graph_state(state))
    return decision


# ====================== BUILD GRAPH ======================

def build_graph():
    """Xây dựng LangGraph"""
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("planner", planner_node)
    workflow.add_node("task_divider", task_divider_node)
    workflow.add_node("progress_tracker", progress_tracker_node)
    workflow.add_node("risk_assessment", risk_assessment_node)
    workflow.add_node("reminder", reminder_node)
    workflow.add_node("human_approval", human_approval_node)
    
    # Add edges
    workflow.set_entry_point("supervisor")
    
    workflow.add_conditional_edges(
        "supervisor",
        route_next,
        {
            "planner": "planner",
            "task_divider": "task_divider",
            "progress_tracker": "progress_tracker",
            "risk_assessment": "risk_assessment",
            "human_approval": "human_approval",
            END: END
        }
    )
    
    workflow.add_edge("planner", "task_divider")
    workflow.add_edge("task_divider", "risk_assessment")
    workflow.add_conditional_edges(
        "risk_assessment",
        route_after_risk,
        {
            "human_approval": "human_approval",
            "reminder": "reminder",
            END: END,
        }
    )
    workflow.add_edge("progress_tracker", "reminder")
    workflow.add_conditional_edges(
        "human_approval",
        route_after_approval,
        {
            "reminder": "reminder",
            END: END,
        }
    )
    workflow.add_edge("reminder", END)
    
    # Initialize optional tracing/checkpointer only when configured to avoid
    # network calls during unit tests or local runs without LangSmith enabled.
    memory = None
    if getattr(config, "LANGSMITH_TRACING", False):
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"
        os.environ["LANGCHAIN_API_KEY"] = config.LANGSMITH_API_KEY or ""
        os.environ["LANGCHAIN_PROJECT"] = config.LANGSMITH_PROJECT or ""
        memory = MemorySaver()

    app = workflow.compile(checkpointer=memory)
    
    return app


# Export graph
orchestrator = build_graph()