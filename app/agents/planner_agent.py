# app/agents/planner_agent.py
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.prompts.planner_prompts import get_planner_prompt
from app.models.schemas import AgentResponse
from app.database.supabase_client import db
from app.database.redis_client import redis_client
from config import config
import json
from langsmith import traceable
import hashlib
import time
from app.utils.logger import get_logger, log_event, truncate_text, summarize_sequence

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash", 
    temperature=0.3,
    google_api_key=config.GEMINI_API_KEY
)

logger = get_logger("app.agents.planner_agent")

@traceable(name="Planner Agent", run_type="chain")
def planner_agent(user_input: str, user_id: str, team_members: list = None) -> AgentResponse:
    """
    Planner Agent với Redis Caching
    """
    try:
        started_at = time.perf_counter()
        # ==================== CACHING ====================
        cache_key = f"planner:{hashlib.md5(user_input.encode('utf-8')).hexdigest()[:20]}"
        log_event(
            logger,
            "planner.enter",
            cache_key=cache_key,
            user_input_preview=truncate_text(user_input, 180),
            user_id=user_id,
            team_members_summary=summarize_sequence(team_members, sample_key="name"),
        )
        
        # Kiểm tra cache
        cached_result = redis_client.get(cache_key)
        if cached_result:
            log_event(logger, "planner.cache.hit", cache_key=cache_key)
            return AgentResponse(**cached_result)

        # ==================== GỌI LLM ====================
        system_prompt = get_planner_prompt(user_input, team_members)
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_input)
        ]
        #langsmith trace sẽ tự động ghi lại cuộc gọi này
        response = llm.invoke(messages)
        content = response.content.strip()
        log_event(logger, "planner.llm.response", content_preview=truncate_text(content, 220))

        # Parse JSON
        try:
            if "{" in content:
                json_str = content[content.find("{"):content.rfind("}") + 1]
                plan = json.loads(json_str)
            else:
                plan = json.loads(content)
        except:
            plan = {
                "project_name": "Dự án Mới",
                "project_description": user_input,
                "total_duration_days": 30,
                "tasks": [],
                "initial_risks": []
            }
            log_event(logger, "planner.parse.fallback", level="warning", cache_key=cache_key)

        # Lưu vào Database
        project_data = {
            "name": plan.get("project_name", "Untitled Project"),
            "description": plan.get("project_description", user_input),
            "start_date": None,
            "end_date": None,
            "owner_id": user_id,
            "status": "Planning"
        }
        
        created_project = db.create_project(project_data)
        project_id = str(created_project["project_id"])
        log_event(logger, "planner.db.project_created", project_id=project_id, project_name=plan.get("project_name"))

        result = AgentResponse(
            response=f"✅ Đã tạo project: **{plan.get('project_name')}**",
            project_id=project_id,
            project_data=plan,
            success=True
        ).dict()   # Convert sang dict để cache

        # ==================== LƯU CACHE ====================
        redis_client.set(cache_key, result, expire=1800)  # Cache 30 phút
        
        log_event(logger, "planner.cache.save", cache_key=cache_key, elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2))
        return AgentResponse(**result)

    except Exception as e:
        log_event(logger, "planner.exception", level="error", error_type=type(e).__name__, error=str(e))
        return AgentResponse(
            response=f"❌ Lỗi khi lập kế hoạch: {str(e)}",
            tasks=[],
            risks=[],
            success=False
        )