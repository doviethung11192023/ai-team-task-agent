# app/agents/reminder_agent.py
from datetime import datetime, date
from app.database.supabase_client import db
from app.models.schemas import AgentResponse
from app.database.redis_client import redis_client
from app.utils.slack_client import send_slack_notification
from app.tools.notification_tools import notification_tools
from langsmith import traceable
import time
from app.utils.logger import get_logger, log_event, summarize_sequence


logger = get_logger("app.agents.reminder_agent")


@traceable(name="Reminder Agent")
def reminder_agent(project_id: str = None) -> AgentResponse:
    """
    Reminder Agent - Kiểm tra và gửi nhắc nhở deadline
    """
    try:
        started_at = time.perf_counter()
        notifications = []
        today = date.today()
        log_event(logger, "reminder.enter", project_id=project_id)
        
        # Lấy project(s)
        if project_id:
            projects = [db.get_project(project_id)]
        else:
            # Lấy tất cả project đang active
            projects = db.get_projects()

        log_event(logger, "reminder.projects.loaded", project_id=project_id, projects_summary=summarize_sequence(projects, sample_key="name"))

        for project in projects:
            if not project:
                continue

            tasks = db.get_tasks_by_project(project['project_id'])
            log_event(logger, "reminder.tasks.loaded", project_id=project.get("project_id"), tasks_summary=summarize_sequence(tasks, sample_key="title"))
            
            for task in tasks:
                if not task.get('due_date') or task.get('status') == 'Done':
                    continue
                
                try:
                    due_date = datetime.strptime(str(task['due_date']), "%Y-%m-%d").date()
                    days_left = (due_date - today).days
                    task_title = task['title']
                    
                    if days_left == 3:
                        msg = f"⏰ **Nhắc nhở**: Task *{task_title}* còn **3 ngày** đến hạn ({due_date}) - Project: {project['name']}"
                        notifications.append(msg)
                        notification_tools.send_notification(msg)
                    
                    elif days_left == 1:
                        msg = f"🚨 **Cảnh báo khẩn**: Task *{task_title}* còn **1 ngày** đến hạn!"
                        notifications.append(msg)
                        notification_tools.send_notification(msg)
                    
                    elif days_left < 0:
                        msg = f"❌ **QUÁ HẠN**: Task *{task_title}* đã trễ {abs(days_left)} ngày!"
                        notifications.append(msg)
                        notification_tools.send_notification(msg)
                except Exception as task_error:
                    log_event(
                        logger,
                        "reminder.task_parse_error",
                        level="warning",
                        project_id=project.get("project_id"),
                        task_id=task.get("task_id"),
                        task_title=task.get("title"),
                        error_type=type(task_error).__name__,
                        error=str(task_error),
                    )
                    continue

        if notifications:
            summary = f"📢 Đã gửi **{len(notifications)}** thông báo nhắc nhở."
        else:
            summary = "✅ Hiện tại không có task nào cần nhắc nhở."

        # Lưu log vào Redis
        redis_client.client.lpush(
            "reminder_logs", 
            f'{{"timestamp": "{datetime.now().isoformat()}", "message": "{summary}"}}'
        )
        redis_client.client.ltrim("reminder_logs", 0, 99)
        log_event(logger, "reminder.redis.log_saved", summary=summary, notifications_count=len(notifications))

        log_event(logger, "reminder.exit", elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2), notifications_count=len(notifications))

        return AgentResponse(
            response=summary,
            success=True
        )

    except Exception as e:
        log_event(logger, "reminder.exception", level="error", project_id=project_id, error_type=type(e).__name__, error=str(e))
        return AgentResponse(
            response=f"❌ Lỗi Reminder Agent: {str(e)}",
            tasks=[],
            risks=[],
            success=False
        )