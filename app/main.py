# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from app.graph.orchestrator import orchestrator
from app.jobs.reminder_job import reminder_job
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
    user_id: str = "user-001"
    project_id: Optional[str] = None

@app.post("/chat")
async def chat(request: ChatRequest):
    """Endpoint chính để chat với AI Agent"""
    inputs = {
        "user_input": request.user_input,
        "user_id": request.user_id,
        "project_id": request.project_id,
        "messages": [],
        "tasks": [],
        "risks": [],
        "current_phase": "planning"
    }
    
    result = orchestrator.invoke(inputs,  config=build_graph_config(request.user_id, request.project_id))
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