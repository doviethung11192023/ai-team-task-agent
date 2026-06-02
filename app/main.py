# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from app.graph.orchestrator import orchestrator
from app.jobs.reminder_job import reminder_job
from app.database.supabase_client import db
from app.utils.helpers import build_graph_config
app = FastAPI(
    title="AI Team Task Management Agent",
    description="Hệ thống quản lý công việc nhóm bằng AI",
    version="1.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    user_input: str
    user_id: Optional[str] = None
    project_id: Optional[str] = None


def _ensure_user(user_id: str) -> str:
    existing_user = db.get_user(user_id)
    if existing_user:
        return user_id

    created_user = db.create_user({
        "name": user_id,
        "email": f"{user_id}@internal.local",
        "role": "member",
        "skill_notes": "Auto-created for chat runtime",
    })
    return str(created_user["user_id"])

@app.post("/chat")
async def chat(request: ChatRequest):
    """Endpoint chính để chat với AI Agent"""
    user_id = _ensure_user(request.user_id or "anonymous")
    inputs = {
        "user_input": request.user_input,
        "user_id": user_id,
        "project_id": request.project_id,
        "messages": [],
        "tasks": [],
        "risks": [],
        "current_phase": "planning"
    }
    
    result = orchestrator.invoke(inputs, config=build_graph_config(user_id))
    return {
        "response": result.get("messages", [])[-1].get("content") if result.get("messages") else "Đã xử lý",
        "project_id": result.get("project_id"),
        "success": True
    }

@app.post("/start-reminder")
async def start_reminder():
    """Khởi động background reminder job"""
    reminder_job.start_background(interval_seconds=1800)  # 30 phút
    return {"status": "Reminder job started"}

@app.get("/health")
async def health():
    return {"status": "healthy", "message": "AI Team Task Agent is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)