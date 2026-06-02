from datetime import datetime

import app.agents.risk_agent as risk_module


class FakeLLMResponse:
    content = (
        '{"risks": ['
        '{"title": "Timeline slip", "description": "Deadline may move", "probability": "Medium", "impact": "High", '
        '"mitigation_plan": "Track milestones", "contingency_plan": "Reduce scope"}'
        ']}'
    )


class FakeLLM:
    def invoke(self, messages):
        return FakeLLMResponse()


def test_risk_agent_uses_planner_context_and_serializes_datetimes(monkeypatch):
    project_data = {
        "name": "Demo Shop",
        "description": "Build a souvenir app",
        "end_date": datetime(2026, 7, 15, 0, 0, 0),
        "created_at": datetime(2026, 5, 31, 10, 0, 0),
        "tasks": [
            {
                "title": "Design landing page",
                "due_date": datetime(2026, 6, 5, 0, 0, 0),
                "created_at": datetime(2026, 5, 31, 11, 0, 0),
            }
        ],
    }
    tasks = [
        {
            "title": "Design landing page",
            "due_date": datetime(2026, 6, 5, 0, 0, 0),
            "created_at": datetime(2026, 5, 31, 11, 0, 0),
        }
    ]

    monkeypatch.setattr(risk_module, "llm", FakeLLM())
    monkeypatch.setattr(risk_module.redis_client, "get", lambda key: None)
    monkeypatch.setattr(risk_module.redis_client, "set", lambda *args, **kwargs: True)
    monkeypatch.setattr(risk_module.db, "get_project", lambda project_id: (_ for _ in ()).throw(AssertionError("db.get_project should not be called")))
    monkeypatch.setattr(risk_module.db, "get_tasks_by_project", lambda project_id: (_ for _ in ()).throw(AssertionError("db.get_tasks_by_project should not be called")))
    monkeypatch.setattr(risk_module.db, "create_risks_batch", lambda risks: risks)

    result = risk_module.risk_agent("project-1", project_data=project_data, tasks=tasks)

    assert result.success is True
    assert result.risks[0]["title"] == "Timeline slip"