# app/database/supabase_client.py
from supabase import create_client, Client
from config import config
from typing import List, Dict, Optional
import psycopg2
from psycopg2.extras import RealDictCursor

class SupabaseDB:
    def __init__(self):
        # ==================== Supabase Client (Python SDK) ====================
        self.supabase: Client = create_client(
            config.SUPABASE_URL, 
            config.SUPABASE_KEY
        )
        print("✅ Supabase Client initialized")

        # ==================== Direct PostgreSQL Connection (psycopg2) ====================
        self.conn = None
        try:
            self.conn = psycopg2.connect(
                host=config.DB_HOST,
                port=config.DB_PORT,
                database=config.DB_NAME,
                user=config.DB_USER,
                password=config.DB_PASSWORD,
                sslmode=config.DB_SSLMODE
            )
            print("✅ Direct PostgreSQL Connection established")
        except Exception as e:
            print(f"⚠️ Không thể kết nối direct PostgreSQL: {e}")
            self.conn = None

    # ====================== SUPABASE METHODS ======================
    def get_users(self) -> List[Dict]:
        response = self.supabase.table("users").select("*").execute()
        return response.data

    def create_project(self, project_data: Dict) -> Dict:
        response = self.supabase.table("projects").insert(project_data).execute()
        return response.data[0]

    def get_project(self, project_id: str) -> Optional[Dict]:
        response = self.supabase.table("projects").select("*").eq("project_id", project_id).execute()
        return response.data[0] if response.data else None

    def get_tasks_by_project(self, project_id: str) -> List[Dict]:
        response = self.supabase.table("tasks").select("*").eq("project_id", project_id).execute()
        return response.data

    def create_tasks_batch(self, tasks: List[Dict]) -> List[Dict]:
        response = self.supabase.table("tasks").insert(tasks).execute()
        return response.data

    def update_task_status(self, task_id: str, status: str, actual_hours: float = None):
        update_data = {"status": status}
        if actual_hours is not None:
            update_data["actual_hours"] = actual_hours
        self.supabase.table("tasks").update(update_data).eq("task_id", task_id).execute()

    def create_risks_batch(self, risks: List[Dict]) -> List[Dict]:
        response = self.supabase.table("risks").insert(risks).execute()
        return response.data

    def get_risks_by_project(self, project_id: str) -> List[Dict]:
        response = self.supabase.table("risks").select("*").eq("project_id", project_id).execute()
        return response.data

    def log_audit(self, action: str, entity_type: str, entity_id: str, performed_by: str, details: Dict):
        log_data = {
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "performed_by": performed_by,
            "details": details
        }
        self.supabase.table("audit_logs").insert(log_data).execute()

    # ====================== UTILITY ======================
    def calculate_project_progress(self, project_id: str) -> int:
        tasks = self.get_tasks_by_project(project_id)
        if not tasks:
            return 0
        completed = sum(1 for t in tasks if t.get('status') == 'Done')
        return int((completed / len(tasks)) * 100) if tasks else 0


# Singleton instance
db = SupabaseDB()