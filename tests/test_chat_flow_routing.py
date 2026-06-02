import os
import uuid

os.environ["APP_LOG_TO_FILE"] = "false"
os.environ["APP_LOG_LEVEL"] = "CRITICAL"

from app.graph import orchestrator as orch_module
from app.models.schemas import AgentResponse
import app.agents.planner_agent as planner_module
import app.agents.task_divider as task_divider_module
import app.agents.risk_agent as risk_module
import app.agents.reminder_agent as reminder_module


def test_first_chat_turn_forces_planner_first(monkeypatch):
    call_order = []
    captured_project_data = {}

    def fake_create_project(project_data):
        captured_project_data.update(project_data)
        return {
            "project_id": str(uuid.uuid4()),
            "name": project_data["name"],
            "description": project_data["description"],
            "owner_id": project_data["owner_id"],
            "progress_percentage": 0,
        }

    def fake_planner_agent(user_input, user_id, team_members=None):
        call_order.append("planner")
        project_data = {
            "name": "Demo Shop",
            "description": "Build a souvenir app",
            "start_date": None,
            "end_date": None,
            "owner_id": user_id,
            "status": "Planning",
        }
        created_project = fake_create_project(project_data)
        return AgentResponse(
            response="✅ Đã tạo project: **Demo Shop**",
            project_id=created_project["project_id"],
            project_data={
                "project_name": "Demo Shop",
                "project_description": "Build a souvenir app",
            },
            success=True,
        )

    def fake_task_divider_agent(project_id, project_data=None, raw_tasks=None):
        call_order.append("task_divider")
        return AgentResponse(response="task divider ok", tasks=[{"task_title": "Setup"}], success=True)

    def fake_risk_agent(project_id, project_data=None, tasks=None):
        call_order.append("risk")
        return AgentResponse(response="risk ok", risks=[], success=True)

    def fake_reminder_agent(project_id=None):
        call_order.append("reminder")
        return AgentResponse(response="reminder ok", success=True)

    monkeypatch.setattr(planner_module, "planner_agent", fake_planner_agent)
    monkeypatch.setattr(task_divider_module, "task_divider_agent", fake_task_divider_agent)
    monkeypatch.setattr(risk_module, "risk_agent", fake_risk_agent)
    monkeypatch.setattr(reminder_module, "reminder_agent", fake_reminder_agent)

    inputs = {
        "user_input": "Tạo project phát triển app bán đồ lưu niệm trong vòng 2 tuần",
        "user_id": "test-user-001",
        "project_id": None,
        "messages": [],
        "tasks": [],
        "risks": [],
        "current_phase": "planning",
    }

    state = orch_module.supervisor_node(dict(inputs))

    assert orch_module.route_next(state) == "planner"

    state = orch_module.planner_node(state)
    state = orch_module.task_divider_node(state)
    state = orch_module.risk_assessment_node(state)
    assert orch_module.route_after_risk(state) == "reminder"
    state = orch_module.reminder_node(state)

    assert call_order[0] == "planner"
    assert "task_divider" in call_order
    assert captured_project_data["owner_id"] == "test-user-001"
    assert state.get("project_id")
    assert state.get("messages")


def test_missing_project_without_create_intent_does_not_force_planner():
    inputs = {
        "user_input": "cho tôi xem tiến độ dự án",
        "user_id": "test-user-001",
        "project_id": None,
        "messages": [],
        "tasks": [],
        "risks": [],
        "current_phase": "tracking",
    }

    state = orch_module.supervisor_node(dict(inputs))

    assert state.get("next_step") == "end"
    assert orch_module.route_next(state) == orch_module.END
    assert state.get("messages")


def test_missing_project_with_natural_create_intent_routes_to_planner():
    inputs = {
        "user_input": "Mở một dự án mới cho team marketing",
        "user_id": "test-user-001",
        "project_id": None,
        "messages": [],
        "tasks": [],
        "risks": [],
        "current_phase": "planning",
    }

    state = orch_module.supervisor_node(dict(inputs))

    assert state.get("next_step") == "planner"
    assert orch_module.route_next(state) == "planner"


def test_chat_endpoint_passes_valid_graph_config(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main as main_module

    captured = {}

    def fake_get_user(user_id):
        return None

    def fake_create_user(payload):
        captured["create_user"] = payload
        return {"user_id": "created-user-id"}

    def fake_build_graph_config(thread_id):
        captured["thread_id"] = thread_id
        return {"configurable": {"thread_id": thread_id}}

    def fake_invoke(inputs, config=None):
        captured["inputs"] = inputs
        captured["config"] = config
        return {"messages": [{"role": "assistant", "content": "ok"}], "project_id": "p-1"}

    monkeypatch.setattr(main_module.db, "get_user", fake_get_user)
    monkeypatch.setattr(main_module.db, "create_user", fake_create_user)
    monkeypatch.setattr(main_module, "build_graph_config", fake_build_graph_config)
    monkeypatch.setattr(main_module.orchestrator, "invoke", fake_invoke)

    client = TestClient(main_module.app)
    response = client.post("/chat", json={"user_input": "Tạo project demo"})

    assert response.status_code == 200
    assert captured["thread_id"] == "created-user-id"
    assert captured["config"] == {"configurable": {"thread_id": "created-user-id"}}
    assert captured["inputs"]["user_id"] == "created-user-id"
