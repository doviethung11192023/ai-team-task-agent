# app/agents/progress_tracker.py
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.models.schemas import AgentResponse
from app.database.supabase_client import db
from app.database.redis_client import redis_client
from config import config
from langsmith import traceable
import time
from app.utils.logger import get_logger, log_event, truncate_text

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash", 
    temperature=0.3,
    google_api_key=config.GEMINI_API_KEY
)

logger = get_logger("app.agents.progress_tracker")

@traceable(name="Progress Tracker Agent")
def progress_tracker_agent(project_id: str, user_input: str) -> AgentResponse:
    """
    Theo dõi và cập nhật tiến độ
    """
    try:
        started_at = time.perf_counter()
        log_event(logger, "progress.enter", project_id=project_id, user_input_preview=truncate_text(user_input, 180))
        if not project_id:
            log_event(logger, "progress.enter.invalid_project", level="warning")
            return AgentResponse(response="Chưa có project để theo dõi tiến độ.", success=False)

        # Cập nhật tiến độ
        progress = db.calculate_project_progress(project_id)
        db.update_project_progress(project_id, progress)
        log_event(logger, "progress.db.progress_updated", project_id=project_id, progress=progress)

        prompt = f"""
        Bạn là Progress Tracker Assistant.
        Project ID: {project_id}
        Tiến độ hiện tại: {progress}%
        Input từ user: {user_input}

        Hãy phân tích tiến độ và đưa ra phản hồi hữu ích.
        """

        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=user_input)
        ]

        response = llm.invoke(messages)
        log_event(logger, "progress.llm.response", project_id=project_id, content_preview=truncate_text(response.content, 220))

        result = AgentResponse(
            response=f"📊 Đã cập nhật tiến độ: **{progress}%**\n\n{response.content}",
            success=True
        ).dict()

        return AgentResponse(**result)

    except Exception as e:
        log_event(logger, "progress.exception", level="error", project_id=project_id, error_type=type(e).__name__, error=str(e))
        return AgentResponse(
            response=f"❌ Lỗi khi theo dõi tiến độ: {str(e)}",
            tasks=[],
            risks=[],
            success=False
        )