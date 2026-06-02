from datetime import datetime

import app.agents.task_divider as task_divider_module


class FakeLLMResponse:
    content = (
        '{"assigned_tasks": ['
        '{"task_title": "Design landing page", "assigned_to": "Linh", "reason": "Designer", "priority": "High", "due_date_offset": 5}'
        '], "workload_summary": {}, "suggestions": []}'
    )


class FakeLLM:
    def invoke(self, messages):
        return FakeLLMResponse()


def test_task_divider_serializes_datetime_and_persists_assignments(monkeypatch):
    team_members = [
        {
            "user_id": "user-1",
            "name": "Linh",
            "email": "linh@example.com",
            "joined_at": datetime(2026, 5, 31, 9, 0, 0),
            "updated_at": datetime(2026, 5, 31, 10, 0, 0),
        }
    ]
    captured_tasks = []
    captured_assignments = []

    monkeypatch.setattr(task_divider_module.db, "get_users", lambda: team_members)
    monkeypatch.setattr(task_divider_module.redis_client, "get", lambda key: None)
    monkeypatch.setattr(task_divider_module.redis_client, "set", lambda *args, **kwargs: True)
    monkeypatch.setattr(task_divider_module, "llm", FakeLLM())

    def fake_create_tasks_batch(tasks):
        captured_tasks.extend(tasks)
        return [
            {
                "task_id": "task-1",
                "project_id": tasks[0]["project_id"],
                "title": tasks[0]["title"],
                "description": tasks[0]["description"],
                "status": tasks[0]["status"],
                "priority": tasks[0]["priority"],
                "due_date": tasks[0]["due_date"],
            }
        ]

    def fake_create_task_assignments_batch(assignments):
        captured_assignments.extend(assignments)
        return [{"assignment_id": "assignment-1", **assignments[0]}]

    monkeypatch.setattr(task_divider_module.db, "create_tasks_batch", fake_create_tasks_batch)
    monkeypatch.setattr(task_divider_module.db, "create_task_assignments_batch", fake_create_task_assignments_batch)

    result = task_divider_module.task_divider_agent(
        "project-1",
        project_data={"project_name": "Demo Shop", "project_description": "Build a souvenir app"},
        raw_tasks=[{"title": "Design landing page"}],
    )

    assert result.success is True
    assert captured_tasks[0]["due_date"].isoformat()  # date object was created
    assert captured_assignments[0]["user_id"] == "user-1"
    assert result.tasks[0]["task_id"] == "task-1"
    assert result.tasks[0]["assigned_user_id"] == "user-1"