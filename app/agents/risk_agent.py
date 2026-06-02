# app/agents/risk_agent.py
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.prompts.planner_prompts import RISK_SYSTEM_PROMPT
from app.models.schemas import AgentResponse
from app.database.supabase_client import db
from app.database.redis_client import redis_client
from config import config
import json
import hashlib
from langsmith import traceable
import time
from app.utils.logger import get_logger, log_event, truncate_text, summarize_sequence
from app.utils.serialization import serialize_for_json

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash", 
    temperature=0.3,
    google_api_key=config.GEMINI_API_KEY
)

logger = get_logger("app.agents.risk_agent")

@traceable(name="Risk Management Agent", run_type="chain")
def risk_agent(project_id: str, project_data: dict = None, tasks: list = None) -> AgentResponse:
    """
    Risk Agent với Redis Caching
    """
    try:
        started_at = time.perf_counter()
        if not project_id:
            log_event(logger, "risk.enter.invalid_project", level="warning")
            return AgentResponse(response="Chưa có project để phân tích rủi ro.", success=False)

        # ==================== CACHING ====================
        cache_key = f"risk:{project_id}"
        log_event(
            logger,
            "risk.enter",
            project_id=project_id,
            cache_key=cache_key,
            project_data_keys=sorted(list((project_data or {}).keys()))[:10],
            tasks_summary=summarize_sequence(tasks, sample_key="title"),
        )
        
        cached_result = redis_client.get(cache_key)
        if cached_result:
            log_event(logger, "risk.cache.hit", cache_key=cache_key, project_id=project_id)
            return AgentResponse(**cached_result)

        # ==================== GỌI LLM ====================
        project = serialize_for_json(project_data or db.get_project(project_id) or {})
        tasks = serialize_for_json(tasks or (project_data or {}).get("tasks") or db.get_tasks_by_project(project_id) or [])
        log_event(logger, "risk.data.loaded", project_id=project_id, tasks_summary=summarize_sequence(tasks, sample_key="title"))

        prompt = f"""
        {RISK_SYSTEM_PROMPT}

        Thông tin Project:
        Tên: {project.get('name') or project.get('project_name')}
        Mô tả: {project.get('description') or project.get('project_description')}
        Deadline: {project.get('end_date')}
        Kế hoạch dự án:
        {json.dumps(project, ensure_ascii=False, indent=2)}

        Danh sách Tasks ({len(tasks)} tasks):
        {json.dumps(tasks, ensure_ascii=False, indent=2)}
        """

        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content="Phân tích rủi ro chi tiết cho project này.")
        ]

        response = llm.invoke(messages)
        content = response.content.strip()
        log_event(logger, "risk.llm.response", project_id=project_id, content_preview=truncate_text(content, 220))

        try:
            if "{" in content:
                json_str = content[content.find("{"):content.rfind("}") + 1]
                result_data = json.loads(json_str)
            else:
                result_data = json.loads(content)
        except:
            result_data = {"risks": []}
            log_event(logger, "risk.parse.fallback", level="warning", project_id=project_id)

        risks = result_data.get("risks", [])

        # Lưu vào Database
        if risks:
            risks_to_save = []
            for risk in risks[:6]:
                risks_to_save.append({
                    "project_id": project_id,
                    "title": risk.get("title"),
                    "description": risk.get("description"),
                    "probability": risk.get("probability", "Medium"),
                    "impact": risk.get("impact", "Medium"),
                    "status": "Open",
                    "mitigation_plan": risk.get("mitigation_plan"),
                    "contingency_plan": risk.get("contingency_plan")
                })
            if risks_to_save:
                db.create_risks_batch(risks_to_save)
                log_event(logger, "risk.db.risks_created", project_id=project_id, risks_to_save_count=len(risks_to_save))

        result = AgentResponse(
            response=f"⚠️ Đã phân tích rủi ro. Tìm thấy {len(risks)} rủi ro.",
            risks=risks,
            success=True
        ).dict()

        # ==================== LƯU CACHE ====================
        redis_client.set(cache_key, result, expire=900)   # Cache 15 phút

        log_event(
            logger,
            "risk.cache.save",
            cache_key=cache_key,
            project_id=project_id,
            risks_count=len(risks),
            elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        return AgentResponse(**result)

    except Exception as e:
        log_event(logger, "risk.exception", level="error", project_id=project_id, error_type=type(e).__name__, error=str(e))
        return AgentResponse(
            response=f"❌ Lỗi khi phân tích rủi ro: {str(e)}",
            risks=[],
            success=False
        )