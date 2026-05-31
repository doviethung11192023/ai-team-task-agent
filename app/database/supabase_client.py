# app/database/supabase_client.py
from config import config
from typing import List, Dict, Optional, Any, Iterable
import psycopg2
from psycopg2.extras import RealDictCursor, Json

class SupabaseDB:
    def __init__(self):
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

    def _ensure_connection(self):
        if self.conn is None or self.conn.closed:
            self.conn = psycopg2.connect(
                host=config.DB_HOST,
                port=config.DB_PORT,
                database=config.DB_NAME,
                user=config.DB_USER,
                password=config.DB_PASSWORD,
                sslmode=config.DB_SSLMODE,
            )

    def _fetchall(self, query: str, params: Optional[tuple] = None) -> List[Dict]:
        self._ensure_connection()
        with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, params or ())
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _fetchone(self, query: str, params: Optional[tuple] = None) -> Optional[Dict]:
        rows = self._fetchall(query, params)
        return rows[0] if rows else None

    def _execute(self, query: str, params: Optional[tuple] = None, fetch: bool = False):
        self._ensure_connection()
        with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, params or ())
            result = cursor.fetchall() if fetch else None
        self.conn.commit()
        return [dict(row) for row in result] if result else []

    # ====================== USERS / PROJECTS / TASKS / RISKS ======================
    def get_users(self) -> List[Dict]:
        return self._fetchall(
            """
            SELECT
                user_id::text,
                name,
                email,
                role,
                avatar_url,
                skill_notes,
                created_at,
                updated_at
            FROM users
            ORDER BY created_at DESC
            """
        )

    def create_user(self, user_data: Dict) -> Dict:
        rows = self._execute(
            """
            INSERT INTO users (name, email, role, avatar_url, skill_notes)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING user_id::text, name, email, role, avatar_url, skill_notes, created_at, updated_at
            """,
            (
                user_data.get("name"),
                user_data.get("email"),
                user_data.get("role", "member"),
                user_data.get("avatar_url"),
                user_data.get("skill_notes"),
            ),
            fetch=True,
        )
        return rows[0] if rows else {}

    def get_projects(self) -> List[Dict]:
        return self._fetchall(
            """
            SELECT
                project_id::text,
                name,
                description,
                start_date,
                end_date,
                status,
                owner_id::text,
                progress_percentage,
                created_at,
                updated_at
            FROM projects
            ORDER BY created_at DESC
            """
        )

    def create_project(self, project_data: Dict) -> Dict:
        rows = self._execute(
            """
            INSERT INTO projects (name, description, start_date, end_date, owner_id, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING
                project_id::text,
                name,
                description,
                start_date,
                end_date,
                status,
                owner_id::text,
                progress_percentage,
                created_at,
                updated_at
            """,
            (
                project_data.get("name"),
                project_data.get("description"),
                project_data.get("start_date"),
                project_data.get("end_date"),
                project_data.get("owner_id"),
                project_data.get("status", "Planning"),
            ),
            fetch=True,
        )
        return rows[0] if rows else {}

    def get_project(self, project_id: str) -> Optional[Dict]:
        return self._fetchone(
            """
            SELECT
                project_id::text,
                name,
                description,
                start_date,
                end_date,
                status,
                owner_id::text,
                progress_percentage,
                created_at,
                updated_at
            FROM projects
            WHERE project_id = %s
            """,
            (project_id,),
        )

    def get_tasks_by_project(self, project_id: str) -> List[Dict]:
        return self._fetchall(
            """
            SELECT
                task_id::text,
                project_id::text,
                title,
                description,
                status,
                priority,
                estimated_hours,
                actual_hours,
                start_date,
                due_date,
                parent_task_id::text,
                created_at,
                updated_at
            FROM tasks
            WHERE project_id = %s
            ORDER BY created_at DESC
            """,
            (project_id,),
        )

    def create_tasks_batch(self, tasks: List[Dict]) -> List[Dict]:
        if not tasks:
            return []

        self._ensure_connection()
        try:
            inserted_rows: List[Dict] = []
            query = """
                INSERT INTO tasks (
                    project_id, title, description, status, priority,
                    estimated_hours, actual_hours, start_date, due_date, parent_task_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING
                    task_id::text,
                    project_id::text,
                    title,
                    description,
                    status,
                    priority,
                    estimated_hours,
                    actual_hours,
                    start_date,
                    due_date,
                    parent_task_id::text,
                    created_at,
                    updated_at
            """
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                for task in tasks:
                    cursor.execute(
                        query,
                        (
                            task.get("project_id"),
                            task.get("title"),
                            task.get("description"),
                            task.get("status", "Todo"),
                            task.get("priority", "Medium"),
                            task.get("estimated_hours"),
                            task.get("actual_hours"),
                            task.get("start_date"),
                            task.get("due_date"),
                            task.get("parent_task_id"),
                        ),
                    )
                    inserted_rows.append(dict(cursor.fetchone()))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return inserted_rows

    def update_task_status(self, task_id: str, status: str, actual_hours: float = None):
        update_data = [status, actual_hours, task_id]
        self._execute(
            """
            UPDATE tasks
            SET status = %s,
                actual_hours = COALESCE(%s, actual_hours),
                updated_at = NOW()
            WHERE task_id = %s
            """,
            tuple(update_data),
        )

    def create_risks_batch(self, risks: List[Dict]) -> List[Dict]:
        if not risks:
            return []

        self._ensure_connection()
        try:
            inserted: List[Dict] = []
            query = """
                INSERT INTO risks (
                    project_id, title, description, probability, impact,
                    status, owner_id, mitigation_plan, contingency_plan
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING
                    risk_id::text,
                    project_id::text,
                    title,
                    description,
                    probability,
                    impact,
                    risk_score,
                    status,
                    owner_id::text,
                    mitigation_plan,
                    contingency_plan,
                    detected_at,
                    resolved_at,
                    created_at
            """
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                for risk in risks:
                    cursor.execute(
                        query,
                        (
                            risk.get("project_id"),
                            risk.get("title"),
                            risk.get("description"),
                            risk.get("probability", "Medium"),
                            risk.get("impact", "Medium"),
                            risk.get("status", "Open"),
                            risk.get("owner_id"),
                            risk.get("mitigation_plan"),
                            risk.get("contingency_plan"),
                        ),
                    )
                    inserted.append(dict(cursor.fetchone()))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return inserted

    def get_risks_by_project(self, project_id: str) -> List[Dict]:
        return self._fetchall(
            """
            SELECT
                risk_id::text,
                project_id::text,
                title,
                description,
                probability,
                impact,
                risk_score,
                status,
                owner_id::text,
                mitigation_plan,
                contingency_plan,
                detected_at,
                resolved_at,
                created_at
            FROM risks
            WHERE project_id = %s
            ORDER BY created_at DESC
            """,
            (project_id,),
        )

    def update_risk_status(self, risk_id: str, status: str, actual_outcome: str = None):
        self._execute(
            """
            UPDATE risks
            SET status = %s,
                resolved_at = CASE WHEN %s = 'Closed' THEN NOW() ELSE resolved_at END
            WHERE risk_id = %s
            """,
            (status, status, risk_id),
        )

    def update_project_progress(self, project_id: str, progress_percentage: int):
        self._execute(
            """
            UPDATE projects
            SET progress_percentage = %s,
                updated_at = NOW()
            WHERE project_id = %s
            """,
            (progress_percentage, project_id),
        )

    def get_project_members(self, project_id: str) -> List[Dict]:
        return self._fetchall(
            """
            SELECT
                pm.project_member_id::text,
                pm.project_id::text,
                pm.user_id::text,
                pm.role_in_project,
                pm.workload_capacity,
                pm.joined_at,
                u.name,
                u.email,
                u.skill_notes
            FROM project_members pm
            JOIN users u ON u.user_id = pm.user_id
            WHERE pm.project_id = %s
            ORDER BY pm.joined_at DESC
            """,
            (project_id,),
        )

    def create_project_member(self, project_id: str, user_id: str, role_in_project: str, workload_capacity: int = 100) -> Dict:
        rows = self._execute(
            """
            INSERT INTO project_members (project_id, user_id, role_in_project, workload_capacity)
            VALUES (%s, %s, %s, %s)
            RETURNING project_member_id::text, project_id::text, user_id::text, role_in_project, workload_capacity, joined_at
            """,
            (project_id, user_id, role_in_project, workload_capacity),
            fetch=True,
        )
        return rows[0] if rows else {}

    def delete_project_member(self, project_member_id: str):
        self._execute(
            "DELETE FROM project_members WHERE project_member_id = %s",
            (project_member_id,),
        )

    def log_audit(self, action: str, entity_type: str, entity_id: str, performed_by: str, details: Dict):
        self._execute(
            """
            INSERT INTO audit_logs (action, entity_type, entity_id, performed_by, details)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (action, entity_type, entity_id, performed_by, Json(details or {})),
        )

    # ====================== UTILITY ======================
    def calculate_project_progress(self, project_id: str) -> int:
        tasks = self.get_tasks_by_project(project_id)
        if not tasks:
            return 0
        completed = sum(1 for t in tasks if t.get('status') == 'Done')
        return int((completed / len(tasks)) * 100) if tasks else 0


# Singleton instance
db = SupabaseDB()