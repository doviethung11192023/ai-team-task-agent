# app/jobs/reminder_job.py
from app.agents.reminder_agent import reminder_agent
from app.database.redis_client import redis_client
import time
import json
from datetime import datetime
import schedule
import threading

class ReminderJob:
    def __init__(self):
        self.is_running = False
        self.thread = None

    def run_reminder(self):
        """Chạy reminder và đẩy kết quả vào Redis queue"""
        try:
            result = reminder_agent()  # Gọi agent hiện tại
            
            # Lưu log reminder vào Redis
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "notifications_sent": len(result.get("notifications", [])) if isinstance(result, dict) else 0,
                "message": result.response if hasattr(result, 'response') else str(result)
            }
            
            # Push vào Redis List (Queue)
            redis_client.client.lpush("reminder_logs", json.dumps(log_entry))
            
            # Giữ tối đa 100 logs
            redis_client.client.ltrim("reminder_logs", 0, 99)
            
            print(f"[{datetime.now()}] ✅ Reminder Job executed")
            
        except Exception as e:
            print(f"[{datetime.now()}] ❌ Reminder Job error: {e}")

    def start_background(self, interval_seconds=3600):
        """Chạy background job định kỳ"""
        if self.is_running:
            print("Reminder Job is already running")
            return

        self.is_running = True
        
        def run_schedule():
            schedule.every(interval_seconds).seconds.do(self.run_reminder)
            
            print(f"🚀 Background Reminder Job started - Check every {interval_seconds} seconds")
            
            while self.is_running:
                schedule.run_pending()
                time.sleep(1)

        self.thread = threading.Thread(target=run_schedule, daemon=True)
        self.thread.start()

    def stop(self):
        """Dừng job"""
        self.is_running = False
        print("⛔ Background Reminder Job stopped")


# Singleton
reminder_job = ReminderJob()