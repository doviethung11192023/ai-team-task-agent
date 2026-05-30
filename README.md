#  AI Team Task Management Agent

Hệ thống **AI Agent quản lý công việc nhóm** thông minh, hỗ trợ tạo dự án, phân chia task, theo dõi tiến độ, nhắc deadline và quản lý rủi ro tự động.

---

##  Tính Năng Chính

- **Tạo Project**: Tạo dự án từ mô tả ngôn ngữ tự nhiên
- **Phân Chia Task**: Tự động phân task và gán người dựa trên kỹ năng & workload
- **Theo Dõi Tiến Độ**: Cập nhật status task, tự động tính % hoàn thành
- **Nhắc Nhở Deadline**: Gửi thông báo qua Slack (3 ngày, 1 ngày, quá hạn)
- **Quản Lý Rủi Ro**: Phân tích, chấm điểm và đưa ra giải pháp
- **Quản Lý Team**: Tạo user, thêm/xóa thành viên project
- **Dashboard**: Theo dõi tổng quan tiến độ và rủi ro
- **Background Job**: Reminder chạy ngầm
- **Caching**: Sử dụng Redis để tối ưu tốc độ & chi phí
- **Tracing**: LangSmith theo dõi chi tiết từng agent

---

## 🛠 Công Nghệ Sử Dụng

- **Backend**: Python + FastAPI
- **Orchestration**: LangGraph (Multi-Agent)
- **LLM**: Gemini 2.0 Flash
- **Database**: Supabase (PostgreSQL + pgvector)
- **Cache**: Redis
- **Frontend**: Streamlit
- **Tracing**: LangSmith
- **Notification**: Slack
- **Container**: Docker + docker-compose

---

## 📋 Cài Đặt & Chạy Local

### 1. Clone Project
```bash
git clone https://github.com/yourusername/ai-team-task-agent.git
cd ai-team-task-agent