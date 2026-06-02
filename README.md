# 🤖 AI Team Task Management Agent

> **Hệ thống AI Agent quản lý công việc nhóm thông minh** — hỗ trợ tạo dự án, phân chia task, theo dõi tiến độ, nhắc deadline và quản lý rủi ro tự động. Xây dựng trên kiến trúc Multi-Agent với LangGraph + Google Gemini.

---

## 📑 Mục lục

1. [Tổng Quan Kiến Trúc](#-tổng-quan-kiến-trúc)
2. [Công Nghệ Sử Dụng](#-công-nghệ-sử-dụng)
3. [Cấu Trúc Thư Mục](#-cấu-trúc-thư-mục)
4. [Database Schema (PostgreSQL)](#-database-schema-postgresql)
5. [Các Agent](#-các-agent)
6. [LangGraph Orchestrator](#-langgraph-orchestrator)
7. [End-to-End Flows](#-end-to-end-flows)
8. [Frontend (Streamlit)](#-frontend-streamlit)
9. [API Endpoints (FastAPI)](#-api-endpoints-fastapi)
10. [Tools Layer](#-tools-layer)
11. [Background Jobs](#-background-jobs)
12. [Redis Caching](#-redis-caching)
13. [Logging & Monitoring](#-logging--monitoring)
14. [Configuration & Environment](#-configuration--environment)
15. [Testing](#-testing)
16. [Hướng Dẫn Cài Đặt & Chạy](#-hướng-dẫn-cài-đặt--chạy)

---

## 🏗 Tổng Quan Kiến Trúc

```
┌─────────────────────────────────────────────────────────────────────┐
│                      FRONTEND (Streamlit)                           │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Tab 1: Chat với AI Agent    │  Tab 2: Dashboard              │  │
│  │  - Chat messages             │  - Overview (progress, tasks)  │  │
│  │  - Human-in-loop approval    │  - Team Management             │  │
│  │  - User input field          │  - Risks                       │  │
│  │                              │  - System Monitoring           │  │
│  └──────────────────────────────┴────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ HTTP (POST /chat)
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       BACKEND (FastAPI :8000)                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  POST /chat  │  POST /start-reminder  │  GET /health         │  │
│  └──────────────────────────┬───────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   LANGGRAPH ORCHESTRATOR                            │
│                                                                     │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │supervisor│───▶│   planner    │───▶│ task_divider │              │
│  └──────────┘    └──────────────┘    └──────┬───────┘              │
│       │                                     │                      │
│       │  ┌──────────────────┐               ▼                      │
│       ├──▶ progress_tracker │         ┌──────────────┐              │
│       │  └──────────────────┘         │    risk      │              │
│       │                               └──────┬───────┘              │
│       │  ┌──────────────────┐                │                     │
│       └──▶    reminder      │◀───────────────┤                     │
│          └──────────────────┘                │                     │
│                                        ┌─────▼──────┐              │
│                                        │human_approval│ (nếu rủi ro │
│                                        └─────┬───────┘  cao >= 7)  │
│                                              │                     │
│                                              └──▶ reminder         │
└─────────────────────────────────────────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
┌─────────────────┐ ┌──────────┐ ┌──────────────┐
│  PostgreSQL DB  │ │  Redis   │ │  Slack API   │
│  (Supabase)     │ │  Cache   │ │  Notifications│
└─────────────────┘ └──────────┘ └──────────────┘
```

### Luồng dữ liệu tổng quát:

1. **User** nhập input qua Streamlit Chat (hoặc API)
2. **FastAPI** nhận request → gọi `orchestrator.invoke()`
3. **Supervisor Node** xác định intent → route tới agent phù hợp
4. **Agent** gọi **Gemini LLM** với system prompt chuyên biệt
5. **Kết quả** được lưu xuống **PostgreSQL**, cache vào **Redis**
6. Nếu có rủi ro cao → chờ **Human-in-the-Loop** approve/reject
7. Cuối cùng **Reminder** kiểm tra deadline và gửi **Slack notification**

---

## 🛠 Công Nghệ Sử Dụng

| Layer | Công Nghệ | Version |
|-------|-----------|---------|
| **Runtime** | Python 3.10+ | - |
| **Backend Framework** | FastAPI | 0.115.0 |
| **ASGI Server** | Uvicorn | 0.30.6 |
| **AI Orchestration** | LangGraph | 0.2.0 |
| **LLM Framework** | LangChain | 0.2.16 |
| **LLM Model** | Google Gemini 2.5 Flash | gemini-2.5-flash |
| **Database** | PostgreSQL (Supabase) | - |
| **Cache** | Redis (Docker: redis:7-alpine) | 5.2.1 |
| **Frontend** | Streamlit | 1.38.0 |
| **Tracing** | LangSmith | - |
| **Notifications** | Slack SDK | 3.31.0 |
| **Validation** | Pydantic v2 | 2.9.2 |
| **Scheduling** | schedule | 1.2.2 |

---

## 📁 Cấu Trúc Thư Mục Chi Tiết

```
E:\agent\ai-team-task-agent\
│
├── app/                                    # Backend source code
│   ├── main.py                             # FastAPI entry point (port 8000)
│   │
│   ├── agents/                             # Các AI Agent (5 agents)
│   │   ├── planner_agent.py                # Planner: tạo project từ NL
│   │   ├── task_divider.py                 # Task Divider: chia task, gán người
│   │   ├── risk_agent.py                   # Risk: phân tích rủi ro
│   │   ├── progress_tracker.py             # Progress: theo dõi tiến độ
│   │   └── reminder_agent.py              # Reminder: nhắc deadline Slack
│   │
│   ├── database/                           # Database clients
│   │   ├── supabase_client.py              # PostgreSQL direct (psycopg2)
│   │   └── redis_client.py                 # Redis caching (singleton)
│   │
│   ├── graph/                              # LangGraph orchestration
│   │   └── orchestrator.py                 # State graph, nodes, edges, routing
│   │
│   ├── jobs/                               # Background jobs
│   │   └── reminder_job.py                 # ReminderJob: scheduled reminders
│   │
│   ├── models/                             # Pydantic data models
│   │   └── schemas.py                      # User, Project, Task, Risk, State, Response
│   │
│   ├── prompts/                            # LLM system prompts
│   │   └── planner_prompts.py              # 4 prompts + 1 helper function
│   │
│   ├── tools/                              # Tool functions cho agents
│   │   ├── task_tools.py                   # create_project, create_tasks_batch, etc.
│   │   ├── risk_tools.py                   # RiskTools class
│   │   └── notification_tools.py           # NotificationTools (Slack)
│   │
│   └── utils/                              # Utilities
│       ├── serialization.py                # serialize_for_json (datetime, UUID, Decimal)
│       ├── logger.py                       # JSON logger + event helpers
│       ├── helpers.py                      # log_audit, build_graph_config
│       └── slack_client.py                 # send_slack_notification wrapper
│
├── frontend/                               # Streamlit UI
│   ├── streamlit_app.py                    # Main UI (2 tabs, 4 subtabs)
│   ├── components/
│   │   ├── chat.py                         # [PLACEHOLDER] chưa triển khai
│   │   └── dashboard.py                    # [PLACEHOLDER] chưa triển khai
│
├── langgraph/                              # Test stubs (khi không có langgraph thật)
│   ├── graph/
│   │   └── __init__.py                     # StateGraph stub với invoke()
│   └── checkpoint/
│       └── memory.py                       # MemorySaver stub (no-op)
│
├── supabase/                               # Database SQL
│   ├── schema.sql                          # 7 tables, indexes, triggers
│   └── seed_data.sql                       # Seed data (trống)
│
├── tests/                                  # Pytest tests
│   ├── test_chat_flow_routing.py           # 4 tests: flow, routing, endpoint
│   ├── test_none_list_regression.py        # 1 test: None-list edge case
│   ├── test_risk_agent_context.py          # 1 test: risk agent context
│   └── test_task_divider_serialization.py  # 1 test: datetime serialization
│
├── config.py                               # Config singleton từ .env
├── requirements.txt                        # Python dependencies
├── docker-compose.yml                      # Redis service
├── .env                                    # [GITIGNORED] Secrets
└── README.md                               # This file (project brain)
```

---

## 🗄 Database Schema (PostgreSQL)

### 7 Tables

#### 1. `users`
| Column | Type | Notes |
|--------|------|-------|
| `user_id` | UUID PK | Default: `gen_random_uuid()` |
| `name` | VARCHAR(255) NOT NULL | |
| `email` | VARCHAR(255) UNIQUE NOT NULL | |
| `role` | VARCHAR(50) | Default: 'member' |
| `avatar_url` | TEXT | Nullable |
| `skill_notes` | TEXT | Lưu kỹ năng thành viên |
| `created_at` | TIMESTAMPTZ | Default: NOW() |
| `updated_at` | TIMESTAMPTZ | Default: NOW() |

#### 2. `projects`
| Column | Type | Notes |
|--------|------|-------|
| `project_id` | UUID PK | |
| `name` | VARCHAR(255) NOT NULL | |
| `description` | TEXT | |
| `start_date` | DATE | |
| `end_date` | DATE | Overall deadline |
| `status` | VARCHAR(50) | Planning, InProgress, Completed, Cancelled |
| `owner_id` | UUID FK → users | |
| `progress_percentage` | INTEGER | Default: 0, tính từ % task Done |
| `created_at` / `updated_at` | TIMESTAMPTZ | Trigger auto-update |

#### 3. `project_members`
| Column | Type | Notes |
|--------|------|-------|
| `project_member_id` | UUID PK | |
| `project_id` | UUID FK → projects (CASCADE) | |
| `user_id` | UUID FK → users (CASCADE) | |
| `role_in_project` | VARCHAR(100) | PM, Developer, Designer, Tester... |
| `workload_capacity` | INTEGER | Default: 100 (= full capacity) |
| `joined_at` | TIMESTAMPTZ | Default: NOW() |
| **UNIQUE** | `(project_id, user_id)` | |

#### 4. `tasks`
| Column | Type | Notes |
|--------|------|-------|
| `task_id` | UUID PK | |
| `project_id` | UUID FK → projects (CASCADE) | |
| `title` | VARCHAR(255) NOT NULL | |
| `description` | TEXT | |
| `status` | VARCHAR(50) | Todo, InProgress, Review, Done |
| `priority` | VARCHAR(20) | Low, Medium, High |
| `estimated_hours` | DECIMAL(5,2) | |
| `actual_hours` | DECIMAL(5,2) | |
| `start_date` | DATE | |
| `due_date` | DATE NOT NULL | |
| `parent_task_id` | UUID FK → tasks (self) | Subtask support |
| `created_at` / `updated_at` | TIMESTAMPTZ | Trigger auto-update |

#### 5. `task_assignments`
| Column | Type | Notes |
|--------|------|-------|
| `assignment_id` | UUID PK | |
| `task_id` | UUID FK → tasks (CASCADE) | |
| `user_id` | UUID FK → users (CASCADE) | |
| `assigned_at` | TIMESTAMPTZ | Default: NOW() |
| `assigned_by` | UUID FK → users | |
| **UNIQUE** | `(task_id, user_id)` | |

#### 6. `risks`
| Column | Type | Notes |
|--------|------|-------|
| `risk_id` | UUID PK | |
| `project_id` | UUID FK → projects (CASCADE) | |
| `title` | VARCHAR(255) NOT NULL | |
| `description` | TEXT | |
| `probability` | VARCHAR(20) NOT NULL | Low, Medium, High |
| `impact` | VARCHAR(20) NOT NULL | Low, Medium, High |
| `risk_score` | INTEGER **GENERATED ALWAYS** | Auto-computed: High+High=9, High+Medium=6, Medium+High=6, else=3 |
| `status` | VARCHAR(50) | Open, Mitigating, Closed |
| `owner_id` | UUID FK → users | |
| `mitigation_plan` | TEXT | |
| `contingency_plan` | TEXT | |
| `detected_at` / `resolved_at` | TIMESTAMPTZ | |
| `created_at` | TIMESTAMPTZ | Default: NOW() |

#### 7. `audit_logs`
| Column | Type | Notes |
|--------|------|-------|
| `log_id` | UUID PK | |
| `action` | VARCHAR(100) NOT NULL | create_project, assign_task... |
| `entity_type` | VARCHAR(50) | Project, Task, Risk |
| `entity_id` | UUID | |
| `performed_by` | UUID FK → users | |
| `details` | JSONB | Chi tiết linh hoạt |
| `created_at` | TIMESTAMPTZ | Default: NOW() |

### Indexes
- `idx_projects_owner` ON projects(owner_id)
- `idx_tasks_project` ON tasks(project_id)
- `idx_tasks_due_date` ON tasks(due_date)
- `idx_tasks_status` ON tasks(status)
- `idx_risks_project` ON risks(project_id)
- `idx_risks_score` ON risks(risk_score)
- `idx_audit_logs_entity` ON audit_logs(entity_type, entity_id)

### Triggers
- `update_timestamp()` — BEFORE UPDATE on projects, tasks → tự động cập nhật `updated_at`

---

## 🤖 Các Agent

Tất cả agent đều dùng **ChatGoogleGenerativeAI** với model **gemini-2.5-flash**, và được decorate với `@traceable` (LangSmith).

| Agent | File | Temperature | Cache TTL | Mô tả |
|-------|------|-------------|-----------|-------|
| **Planner** | `planner_agent.py` | 0.3 | 30 min | Phân tích yêu cầu → tạo project + task thô + rủi ro ban đầu |
| **Task Divider** | `task_divider.py` | 0.2 | 20 min | Chia task chi tiết, gán người dựa trên kỹ năng & workload |
| **Risk Agent** | `risk_agent.py` | 0.3 | 15 min | Phân tích rủi ro từ project data + tasks |
| **Progress Tracker** | `progress_tracker.py` | 0.3 | No cache | Tính % hoàn thành từ tasks → cập nhật DB → response |
| **Reminder** | `reminder_agent.py` | N/A | No cache | Check deadline, gửi Slack notification |

### Chi tiết từng Agent:

#### 1. Planner Agent
- **Input:** `user_input`, `user_id`, `team_members`
- **Output:** `AgentResponse` với `project_id`, `project_data`
- **Cache key:** `planner:{md5(input)[:20]}`
- **Flow:**
  1. Check Redis cache
  2. Build prompt từ `PLANNER_SYSTEM_PROMPT` + user input
  3. LLM trả về JSON: project_name, tasks (8-15), initial_risks
  4. Parse JSON (fallback nếu parse lỗi)
  5. `db.create_project()` → lưu project
  6. Cache result (30 min)
  7. Trả về AgentResponse

#### 2. Task Divider Agent
- **Input:** `project_id`, `project_data`, `raw_tasks`
- **Output:** `AgentResponse` với danh sách task đã gán người
- **Cache key:** `task_divider:{project_id}` (20 min)
- **Flow:**
  1. Check cache
  2. Lấy `team_members` từ DB
  3. Build prompt với `TASK_DIVIDER_SYSTEM_PROMPT`
  4. LLM trả về JSON: assigned_tasks (mỗi task có `assigned_to`)
  5. Parse JSON
  6. `_resolve_assignee_user_id()` → match user_id/name/email
  7. `db.create_tasks_batch()` (max 12 tasks)
  8. Tự động tạo `project_members` nếu user chưa có trong project
  9. `db.create_task_assignments_batch()`
  10. Cache result

#### 3. Risk Agent
- **Input:** `project_id`, `project_data`, `tasks`
- **Output:** `AgentResponse` với danh sách risks
- **Cache key:** `risk:{project_id}` (15 min)
- **Flow:**
  1. Check cache
  2. Load project + tasks từ `project_data` hoặc DB fallback
  3. Build prompt với `RISK_SYSTEM_PROMPT`
  4. LLM trả về JSON: risks array
  5. `db.create_risks_batch()` (max 6 risks)
  6. Cache result

#### 4. Progress Tracker Agent
- **Input:** `project_id`, `user_input`
- **Output:** `AgentResponse` với progress %
- **Flow:**
  1. Guard: cần valid project_id
  2. `db.calculate_project_progress()` → % task Done
  3. `db.update_project_progress()`
  4. LLM tạo response phân tích tiến độ

#### 5. Reminder Agent
- **Input:** `project_id` (optional — nếu None thì check all active projects)
- **Output:** `AgentResponse` với thông báo tổng kết
- **Flow:**
  1. Load project(s)
  2. Với mỗi project, load tasks
  3. Check từng task's due_date:
     - `days_left == 3` → ⏰ normal reminder
     - `days_left == 1` → 🚨 urgent
     - `days_left < 0` → ❌ quá hạn
  4. Mỗi notification → `notification_tools.send_notification()` (Slack)
  5. Push summary log vào Redis list `reminder_logs` (max 100)

---

## 🔄 LangGraph Orchestrator

**File:** `app/graph/orchestrator.py`

### State Definition (`AgentState` — TypedDict)

```python
class AgentState(TypedDict):
    user_input: str                    # Input từ user
    user_id: str                       # User ID
    project_id: Optional[str]          # Project hiện tại
    messages: Annotated[List[dict], merge_messages]  # Lịch sử chat (max 20)
    project_data: Optional[dict]       # Data project từ planner
    tasks: List[dict]                  # Danh sách tasks
    risks: List[dict]                  # Danh sách risks
    next_step: str                     # Node tiếp theo
    needs_human_approval: bool         # Cần phê duyệt?
    approval_response: Optional[str]   # "approved" | "rejected"
    current_phase: str                 # planning | risk_assessment | execution | monitoring
    error: Optional[str]               # Error message
```

### Message Reducer (`merge_messages`)
- Custom reducer để trộn message lists
- Chống duplicate messages (prefix matching)
- Giới hạn `MAX_MESSAGE_HISTORY = 20`

### Nodes (7 nodes)

| Node | Function | Responsibility |
|------|----------|----------------|
| `supervisor` | `supervisor_node()` | Entry point — route dựa trên intent & state |
| `planner` | `planner_node()` | Gọi Planner Agent, set project_data + project_id |
| `task_divider` | `task_divider_node()` | Gọi Task Divider Agent, tạo tasks + assignments |
| `risk_assessment` | `risk_assessment_node()` | Gọi Risk Agent, set needs_human_approval |
| `progress_tracker` | `progress_tracker_node()` | Gọi Progress Tracker, update progress |
| `reminder` | `reminder_node()` | Gọi Reminder Agent, có guard chống re-entry |
| `human_approval` | `human_approval_node()` | Xử lý approval/rejection |

### Routing Logic (Supervisor)

```
SUPERVISOR ROUTING:
├── needs_human_approval & chưa có response → human_approval
├── approval_response == "approved"/"rejected" → human_approval
├── KHÔNG có project_id:
│   ├── Có CREATE_INTENT_KEYWORDS → planner
│   └── Không → END (yêu cầu chọn project)
├── CÓ project_id:
│   ├── CREATE_INTENT_KEYWORDS → planner (phase=planning)
│   ├── "update" / "tiến độ" → progress_tracker
│   ├── "rủi ro" → risk_assessment
│   └── default: phase=planning → task_divider, else → planner
```

### Graph Edges

```
supervisor → [conditional] → planner / task_divider / progress_tracker / risk_assessment / human_approval / END
planner → task_divider
task_divider → risk_assessment
risk_assessment → [conditional] → human_approval (nếu rủi ro >= 7) / reminder (nếu an toàn) / END (nếu reject)
progress_tracker → reminder
human_approval → [conditional] → reminder (approve) / END (reject)
reminder → END
```

### Thresholds
- `HIGH_RISK_THRESHOLD = 7` — risk_score >= 7 → cần human approval
- `risk_requires_approval()` — fallback: probability="High" AND impact="High"

### Checkpointer
- `MemorySaver()` — optional, chỉ init khi `config.LANGSMITH_TRACING == True`

### Conditional Edge Functions
- `route_next(state)` — router chính cho supervisor
- `route_after_risk(state)` — sau risk assessment
- `route_after_approval(state)` — sau human approval

### Intent Keywords (`CREATE_INTENT_KEYWORDS`)
26 phrases (Vietnamese + English): "tạo project", "tao du an", "dự án mới", "new project", "khởi tạo", v.v.

---

## 🔄 End-to-End Flows

### Flow 1: Tạo Project Mới (Complete Pipeline)
```
User: "Tao project phat trien app ban hang"
  → Streamlit: POST /chat (hoặc orchestrator.invoke directly)
  → FastAPI: _ensure_user() → orchestrator.invoke()
  → supervisor: phát hiện CREATE_INTENT_KEYWORDS → "planner"
  → planner: planner_agent()
      → LLM tạo project plan (name, tasks, risks)
      → db.create_project()
      → Redis cache (30 min)
  → task_divider: task_divider_agent()
      → LLM chia task, gán người
      → db.create_tasks_batch()
      → db.create_task_assignments_batch()
      → Redis cache (20 min)
  → risk_assessment: risk_agent()
      → LLM phân tích rủi ro
      → db.create_risks_batch()
      → Redis cache (15 min)
      → [nếu risk_score >= 7]: needs_human_approval = True
  → Nếu cần approval:
      → human_approval: chờ user Approve/Reject
      → [approved] → reminder
      → [rejected] → END
  → Nếu không cần approval:
      → reminder: kiểm tra deadline → Slack notification
  → END
```

### Flow 2: Theo Dõi Tiến Độ
```
User: "Cap nhat tien do du an"
  → supervisor: detect "tiến độ" → "progress_tracker"
  → progress_tracker: progress_tracker_agent()
      → db.calculate_project_progress() ( % task Done )
      → db.update_project_progress()
      → LLM tạo response
  → reminder: reminder_agent()
      → Kiểm tra deadline
      → Slack notifications
  → END
```

### Flow 3: Phân Tích Rủi Ro
```
User: "Phan tich rui ro"
  → supervisor: detect "rủi ro" → "risk_assessment"
  → risk_assessment: risk_agent()
      → LLM phân tích rủi ro
      → db.create_risks_batch()
      → [high risk] → human_approval → [approved] → reminder → END
      → [low risk] → reminder → END
```

### Flow 4: Background Reminder (Job tự động)
```
  → ReminderJob.run_reminder() (mỗi 30 phút, daemon thread)
  → reminder_agent(project_id=None)
      → Load tất cả active projects
      → Với mỗi project, load tasks
      → Check due_date vs today
      → 3 ngày → Slack: ⏰ normal
      → 1 ngày → Slack: 🚨 urgent
      → Quá hạn → Slack: ❌ overdue
      → Push log vào Redis reminder_logs
```

### Flow 5: Chat Khi Chưa Có Project
```
User: "Cho toi xem tien do" (không có project_id)
  → supervisor: no project_id, no create intent
  → END
  → Response: "Vui lòng chọn một project có sẵn ở sidebar Dashboard..."
```

---

## 🖥 Frontend (Streamlit)

**File:** `frontend/streamlit_app.py`

### Session State Variables
| Variable | Type | Mục đích |
|----------|------|----------|
| `thread_id` | str | Thread ID cho LangGraph config |
| `selected_user_id` | str | User đang dùng |
| `messages` | list[dict] | Lịch sử chat |
| `current_project_id` | str | Project hiện tại |
| `pending_approval` | dict | Dữ liệu chờ human approval |
| `project_scope` | str | "Theo user" hoặc "Tất cả" |
| `dashboard_snapshot` | dict | Cache dữ liệu dashboard |
| `dashboard_snapshot_project_id` | str | Project ID của snapshot |

### Sidebar
- **User Selector:** Dropdown chọn user từ DB (hoặc fallback text input)
- **Project Scope:** Radio "Theo user" / "Tất cả"
- **Project Selector:** Dropdown dự án, hiển thị `[Tên] [Status] [Progress%] | [ID]`
- **Buttons:** Refresh Project List, Reset Conversation
- **Background Jobs:** Start/Stop Reminder Job, Xem Reminder Logs

### Tab 1: Chat với AI Agent (`💬`)
- Hiển thị messages history
- Human-in-the-loop approval panel (Approve ✅ / Reject ⛔)
- Chat input → `orchestrator.invoke()`
- Xử lý `needs_human_approval` flag

### Tab 2: Dashboard (`📊`)

#### Subtabs:
1. **📈 Tổng quan (Overview)**
   - 4 metrics: Tiến độ %, Tổng Task, Chưa hoàn thành, Quá hạn
   - Status summary: Todo / InProgress / Review / Done counts
   - DataTable task list với assignees

2. **👥 Quản lý Team**
   - Form tạo User mới (name, email, role, skill)
   - Danh sách thành viên trong project (có nút xóa)
   - Workload Summary table (member, role, capacity, tasks, hours)

3. **⚠️ Rủi Ro**
   - 4 metrics: Tổng Risks, Open, Mitigating, Avg Score
   - Risk list với color coding (🔴 >=7, 🟠 >=4, 🟢 <4)

4. **📊 System Monitoring**
   - Redis Status (🟢/🔴)
   - Cache statistics (keys count)
   - Recent Reminder Logs
   - Cache management buttons (Clear All, View Keys, Refresh Metrics)
   - Orchestrator Event Log viewer (filter by event prefix)
   - Audit Timeline

### Dashboard Data Snapshot
`_build_dashboard_snapshot(project_id)` — gọi 9 DB queries:
1. `get_project()`
2. `get_tasks_by_project()`
3. `get_project_members()`
4. `get_task_assignments_by_project()`
5. `get_task_status_summary()`
6. `get_overdue_tasks()`
7. `get_risks_by_project()`
8. `get_risk_summary()`
9. `get_member_workload()`
10. `get_audit_logs(project_id=project_id, limit=30)`

---

## 📡 API Endpoints (FastAPI)

**File:** `app/main.py`

### `POST /chat`
- **Request body:** `ChatRequest { user_input, user_id?, project_id? }`
- **Logic:**
  - `_ensure_user()` — auto-tạo user nếu chưa tồn tại
  - `orchestrator.invoke()` với thread config
- **Response:** `{ response, project_id, success }`

### `POST /start-reminder`
- Start `ReminderJob.start_background(interval_seconds=1800)` (30 phút)
- **Response:** `{ status: "Reminder job started" }`

### `GET /health`
- **Response:** `{ status: "healthy", message: "AI Team Task Agent is running" }`

---

## 🧰 Tools Layer

### Task Tools (`app/tools/task_tools.py`)
| Function | Purpose |
|----------|---------|
| `create_project_tool()` | Tạo project + audit log |
| `create_tasks_batch_tool()` | Batch tạo tasks |
| `update_task_status_tool()` | Update task status |
| `get_project_tasks_tool()` | Fetch tasks |
| `get_project_risks_tool()` | Fetch risks |

### Risk Tools (`app/tools/risk_tools.py` — class `RiskTools`)
| Method | Purpose |
|--------|---------|
| `create_risks()` | Batch tạo risks |
| `get_project_risks()` | Fetch risks |
| `update_risk_status()` | Update risk status |

### Notification Tools (`app/tools/notification_tools.py` — class `NotificationTools`)
| Method | Purpose |
|--------|---------|
| `send_notification()` | Gửi Slack message + Redis log |
| `send_risk_alert()` | Gửi alert nếu risk_score >= 7 |
| `get_recent_notifications()` | Fetch notification history từ Redis |

---

## ⏰ Background Jobs

**File:** `app/jobs/reminder_job.py`

### Class `ReminderJob` (Singleton)
- `run_reminder()` — gọi `reminder_agent()` → push log vào Redis `reminder_logs` (trim 100)
- `start_background(interval_seconds=3600)` — daemon thread dùng `schedule` library
- `stop()` — set `is_running = False`

**UI controls:** Start / Stop từ sidebar Streamlit, interval mặc định 30 phút.

---

## ⚡ Redis Caching

**File:** `app/database/redis_client.py`

### Class `RedisClient` (Singleton via `__new__`)
- **Connection priority:** `REDIS_URL` > `REDIS_HOST` + `REDIS_PORT` + `REDIS_PASSWORD`
- **Graceful degradation:** Nếu Redis unavailable → `self.client = None`, all methods return safe defaults

### Cache Strategy
| Cache Key | TTL | Set by | Purpose |
|-----------|-----|--------|---------|
| `planner:{md5[:20]}` | 30 min | Planner Agent | Tránh gọi LLM cho cùng yêu cầu |
| `task_divider:{project_id}` | 20 min | Task Divider | Tránh chia task lại cho project cũ |
| `risk:{project_id}` | 15 min | Risk Agent | Tránh phân tích rủi ro lại |
| `reminder_logs` | N/A (list) | Reminder Agent + ReminderJob | Log lịch sử reminder (max 100) |
| `notification_logs` | N/A (list) | NotificationTools | Log lịch sử notification (max 100) |

### Methods
- `set(key, value, expire=3600)` — JSON-serialized với TTL
- `get(key)` — JSON-deserialized
- `delete(key)` — xóa key
- `clear_cache()` — flushall
- `get_reminder_logs(limit=20)` — lấy logs từ list

---

## 📝 Logging & Monitoring

**File:** `app/utils/logger.py`

### Structured JSON Logger
- Tất cả log đều là JSON với format: `{ "ts": ISO datetime, "event": event_name, ...fields }`
- `get_logger(name)` — tạo/retrieve named logger
- `log_event(logger, event, level, **fields)` — ghi structured log
- Output: stream + file (`logs/app.log`)

### Helper Functions
- `truncate_text(value, limit=200)` — safe truncation
- `summarize_sequence(items, sample_key, sample_size)` — tạo sample-based summaries
- `summarize_graph_state(state)` — extract key fields từ state cho log
- `read_recent_log_events(limit, event_prefix)` — đọc lại từ file log với bộ lọc

### Audit Logging (`app/utils/helpers.py`)
- `log_audit(action, entity_type, entity_id, performed_by, details)` — ghi vào `audit_logs` table

### Log Events (prefix conventions)
- `supervisor.enter / supervisor.exit / supervisor.route`
- `planner.enter / planner.llm.response / planner.db.project_created / planner.cache.hit|save`
- `task_divider.enter / task_divider.llm.response / task_divider.db.tasks_created`
- `risk.enter / risk.llm.response / risk.db.risks_created / risk.cache.hit|save`
- `progress.enter / progress.db.progress_updated / progress.llm.response`
- `reminder.enter / reminder.tasks.loaded / reminder.exception`
- `redis.connect.success|failure / redis.set.success|failure`
- `audit.write.enter|exit|exception`

---

## ⚙ Configuration & Environment

**File:** `config.py`

### Class `Config` (singleton instance: `config`)

| Variable | Default | Mô tả |
|----------|---------|-------|
| `GEMINI_API_KEY` | — | Google Gemini API key |
| `DB_HOST` | — | PostgreSQL host |
| `DB_PORT` | 6543 | PostgreSQL port |
| `DB_NAME` | — | Database name |
| `DB_USER` | — | Database user |
| `DB_PASSWORD` | — | Database password |
| `DB_SSLMODE` | "require" | SSL mode |
| `SUPABASE_URL` | — | (Legacy) |
| `SUPABASE_KEY` | — | (Legacy) |
| `SLACK_BOT_TOKEN` | — | Slack bot token |
| `SLACK_CHANNEL_ID` | — | Slack channel ID |
| `REDIS_HOST` | "localhost" | Redis host |
| `REDIS_PORT` | 6379 | Redis port |
| `REDIS_PASSWORD` | — | Redis password |
| `REDIS_URL` | — | Full Redis URL (ưu tiên cao nhất) |
| `LANGSMITH_API_KEY` | — | LangSmith API key |
| `LANGSMITH_TRACING` | false | Enable/disable tracing |
| `LANGSMITH_PROJECT` | "ai-team-task-agent" | LangSmith project name |
| `ENV` | "development" | Environment |
| `DEBUG` | true | Debug mode |

### Runtime env vars
- `APP_LOG_LEVEL` (default "INFO")
- `APP_LOG_TO_FILE` (default "true")
- `PYTEST_CURRENT_TEST` / `ENV=test` — tắt Slack notifications

---

## 🧪 Testing

**Framework:** pytest với monkeypatch

### Test Files

| File | Tests | Coverage |
|------|-------|----------|
| `test_chat_flow_routing.py` | 4 tests | Full flow routing, missing project, create intent, FastAPI endpoint |
| `test_none_list_regression.py` | 1 test | Risk agent returns no risks (None-list edge case) |
| `test_risk_agent_context.py` | 1 test | Risk agent uses planner context + datetime serialization |
| `test_task_divider_serialization.py` | 1 test | Datetime serialization + assignment persistence |

### Testing Patterns

1. **FakeLLM classes** — mocks `ChatGoogleGenerativeAI` với hardcoded JSON responses
2. **Monkeypatch DB calls** — replace `db.create_tasks_batch()`, `db.get_users()`, etc.
3. **Monkeypatch Redis** — `redis_client.get()` / `redis_client.set()` with no-op
4. **Module stubs** — `langgraph/graph/__init__.py` cung cấp `StateGraph` stub với `invoke()`
5. **Runtime stubbing** — `test_none_list_regression.py` dùng `types.ModuleType` để tạo synthetic modules
6. **Environment control:** tests set `APP_LOG_TO_FILE=false`, `APP_LOG_LEVEL=CRITICAL`

### Test Stubs (langgraph/)
- `langgraph/graph/__init__.py`: `StateGraph` stub với `add_node()`, `add_conditional_edges()`, `compile()` → `App.invoke()`
- `langgraph/checkpoint/memory.py`: `MemorySaver` stub (no-op)

### Chưa có test cho:
- Streamlit frontend (not tested)
- `progress_tracker_agent`
- `reminder_agent`
- `ReminderJob`
- DB update operations (`update_task_status`, `update_risk_status`)

---

## 🚀 Hướng Dẫn Cài Đặt & Chạy

### 1. Yêu Cầu Hệ Thống
- Python 3.9+
- Docker & Docker Compose (cho Redis)
- Tài khoản Supabase (PostgreSQL)
- API Keys: Gemini, Slack (tùy chọn), LangSmith (tùy chọn)

### 2. Clone & Setup
```bash
git clone <repo-url>
cd ai-team-task-agent
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### 3. Cấu Hình .env
```env
GEMINI_API_KEY=your_key
DB_HOST=your_db_host
DB_PORT=6543
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=your_password

SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL_ID=C...

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=yourpassword123
REDIS_URL=redis://:yourpassword123@localhost:6379

LANGSMITH_API_KEY=...    # Optional
LANGSMITH_TRACING=false
```

### 4. Start Redis
```bash
docker-compose up -d
```

### 5. Database Setup
Chạy `supabase/schema.sql` trong SQL Editor của Supabase.

### 6. Run Backend
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# API Docs: http://localhost:8000/docs
```

### 7. Run Frontend
```bash
streamlit run frontend/streamlit_app.py
# UI: http://localhost:8501
```

### 8. Run Tests
```bash
pytest tests/ -v
```

---

## 🔧 Ghi Chú Kỹ Thuật

### Serialization
- `app/utils/serialization.py`: `serialize_for_json()` — chuyển đổi `datetime→ISO`, `UUID→str`, `Decimal→str`, đệ quy qua dict/list/tuple
- Dùng ở: DB queries, Redis cache, LLM prompt building

### Error Handling Patterns
- **Agent-level:** `try/except Exception` → `log_event(level="error")` → `AgentResponse(success=False)`
- **DB:** `_ensure_connection()` → reconnect nếu closed; `conn.rollback()` trên lỗi
- **Redis:** Graceful degradation — nếu Redis offline, trả về safe defaults
- **Graph:** Reminder node guard chống re-entry qua `_visited_nodes`

### Key Design Decisions
- **Lazy imports** trong orchestrator nodes — tránh import-time dependencies nặng
- **Direct PostgreSQL** (psycopg2) thay vì Supabase client — bypass rate limits
- **`normalize_agent_result()`** — xử lý cả dict và Pydantic model output
- **`serialize_for_json()`** — dùng ở DB layer thay vì model layer
- **Test stubs** trong `langgraph/` — cho phép chạy test không cần langgraph thật
- **`FRONTEND/components/chat.py`** và **`dashboard.py`** — đang là placeholder, code chính vẫn trong `streamlit_app.py`

---

## 📈 Trạng Thái Dự Án (6/2026)

- **Branch hiện tại:** `debug` (đã modify so với `main`)
- **Modified files:** `.gitignore`, `README.md`, hầu hết agents, DB clients, orchestrator, frontend, logger
- **New files:** `app/utils/serialization.py`, `tests/test_chat_flow_routing.py`, `tests/test_risk_agent_context.py`, `tests/test_task_divider_serialization.py`
- **Hoạt động:** Backend + Frontend + Database + Redis đều kết nối được
- **Cần cải thiện:**
  - Tách `streamlit_app.py` thành components riêng
  - Thêm tests cho progress_tracker, reminder_agent, reminder_job
  - CI/CD pipeline
  - Dockerfile cho toàn bộ app (không chỉ Redis)

---

> *Last updated: 2026-06-02 | Maintained as the central brain document for the AI Team Task Agent project.*