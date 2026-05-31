# app/agents/task_divider.py
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.prompts.planner_prompts import TASK_DIVIDER_SYSTEM_PROMPT
from app.models.schemas import AgentResponse
from app.database.supabase_client import db
from app.database.redis_client import redis_client
from config import config
import json
import hashlib
from langsmith import traceable
import time
from app.utils.logger import get_logger, log_event, truncate_text, summarize_sequence

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash", 
    temperature=0.2,
    google_api_key=config.GEMINI_API_KEY
)

logger = get_logger("app.agents.task_divider")

@traceable(name="Task Divider Agent")
def task_divider_agent(project_id: str, project_data: dict = None, raw_tasks: list = None) -> AgentResponse:
    """
    Phân chia task và gán người
    """
    try:
        started_at = time.perf_counter()
        cache_key = f"task_divider:{project_id}"
        log_event(
            logger,
            "task_divider.enter",
            project_id=project_id,
            cache_key=cache_key,
            project_data_keys=sorted(list((project_data or {}).keys()))[:10],
            raw_tasks_summary=summarize_sequence(raw_tasks, sample_key="title"),
        )
        cached = redis_client.get(cache_key)
        if cached:
            log_event(logger, "task_divider.cache.hit", cache_key=cache_key, project_id=project_id)
            return AgentResponse(**cached)

        # Lấy danh sách thành viên
        team_members = db.get_users()
        log_event(logger, "task_divider.team_members.loaded", project_id=project_id, team_members_summary=summarize_sequence(team_members, sample_key="name"))

        prompt = f"""
        {TASK_DIVIDER_SYSTEM_PROMPT}

        Thông tin Project:
        {json.dumps(project_data or {}, ensure_ascii=False, indent=2)}

        Danh sách task thô:
        {json.dumps(raw_tasks or [], ensure_ascii=False, indent=2)}

        Danh sách thành viên:
        {json.dumps(team_members, ensure_ascii=False, indent=2)}
        """

        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content="Hãy phân chia task và gán người một cách hợp lý.")
        ]

        response = llm.invoke(messages)
        content = response.content.strip()
        log_event(logger, "task_divider.llm.response", project_id=project_id, content_preview=truncate_text(content, 220))

        try:
            if "{" in content:
                json_str = content[content.find("{"):content.rfind("}") + 1]
                result = json.loads(json_str)
            else:
                result = json.loads(content)
        except:
            result = {"assigned_tasks": [], "workload_summary": {}, "suggestions": ["Không parse được JSON"]}
            log_event(logger, "task_divider.parse.fallback", level="warning", project_id=project_id)

        # Lưu tasks vào database
        if result.get("assigned_tasks"):
            tasks_to_create = []
            for task in result["assigned_tasks"][:12]:  # Giới hạn
                tasks_to_create.append({
                    "project_id": project_id,
                    "title": task.get("task_title"),
                    "description": task.get("description", "Auto generated"),
                    "due_date": "2026-07-15",  # Có thể tinh chỉnh sau
                    "priority": task.get("priority", "Medium"),
                    "status": "Todo"
                })
            if tasks_to_create:
                db.create_tasks_batch(tasks_to_create)
                log_event(logger, "task_divider.db.tasks_created", project_id=project_id, tasks_to_create_count=len(tasks_to_create))

        final_result = AgentResponse(
            response=f"✅ Đã phân chia {len(result.get('assigned_tasks', []))} tasks cho team.",
            tasks=result.get("assigned_tasks", []),
            success=True
        ).dict()

        redis_client.set(cache_key, final_result, expire=1200)  # Cache 20 phút
        log_event(
            logger,
            "task_divider.cache.save",
            cache_key=cache_key,
            project_id=project_id,
            assigned_tasks_count=len(result.get("assigned_tasks", [])),
            elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        return AgentResponse(**final_result)

    except Exception as e:
        log_event(logger, "task_divider.exception", level="error", project_id=project_id, error_type=type(e).__name__, error=str(e))
        return AgentResponse(
            response=f"❌ Lỗi khi phân chia task: {str(e)}",
            tasks=[],
            success=False
        )