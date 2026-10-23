# AI Agent 智能客服系统

一个可运行、可测试、可用 Docker 一键启动的全栈 Agent 项目。它不是只有聊天界面的 Demo：Agent 会查询真实天气和 MySQL 业务数据，并通过“两阶段确认 + 幂等写入”安全地完成下单、取消订单和创建工单。

## 项目亮点

- FastAPI + LangChain 1.x `create_agent`，对接 OpenAI 兼容模型接口
- 16 个工具，覆盖天气、计算、时间、知识库、商品、订单、物流、用户和工单
- 写操作先生成预览，下一轮只有明确确认才执行；同一请求不能预览后直接写入
- MySQL 事务、行锁、用户归属校验和幂等键，降低重复下单与越权查询风险
- 注册/登录/退出、PBKDF2 加盐密码哈希、HttpOnly 会话 Cookie 和用户数据隔离
- 会话令牌、输入校验、CORS 白名单、限流、并发上限和超时保护
- JSON 会话记忆采用线程锁、原子替换和 LRU/TTL 边界
- React + TypeScript 前端使用 POST SSE 逐 token 展示回复，支持会话恢复和请求取消
- 前后端单元测试、构建冒烟测试、Agent 路由评测集和 GitHub Actions
- MySQL 初始化脚本、演示数据、多阶段镜像和 Docker Compose

## 架构

```text
React / TypeScript（登录/注册 + 流式聊天）
       │  HttpOnly Cookie + POST SSE + conversation token
       ▼
FastAPI ── rate limit / timeout / validation
       │
       ▼
LangChain 1.x create_agent ── 16 typed tools
       │                     ├─ Open-Meteo
       │                     ├─ static FAQ / catalog
       │                     └─ MySQL transactions
       ▼
Atomic JSON conversation memory
```

## 快速启动

需要 Docker Desktop / Docker Engine 和一个可用的 OpenAI 兼容 API Key。

```bash
cp backend/.env.example backend/.env
```

编辑 `backend/.env`，至少替换：

```env
OPENAI_API_KEY=你的密钥
CONVERSATION_SIGNING_SECRET=一段足够长的随机字符串
```

然后启动：

```bash
docker compose up --build
```

- Web UI: http://localhost:3000
- API 文档: http://localhost:8000/docs
- 存活检查: http://localhost:8000/health
- 就绪检查: http://localhost:8000/ready

后端启动时会以 `CREATE TABLE IF NOT EXISTS` 补齐认证表，因此旧数据卷无需删除；`database/init/004_add_auth.sql` 也会在新数据库首次启动时执行。

## 本地开发

### 后端

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认访问 `http://localhost:8000`；可通过 `VITE_API_URL` 覆盖。

## 安全写操作

下单、取消订单和创建工单都采用相同状态机：

```text
用户提出需求 → prepare_* 校验并持久化待确认记录
             → Agent 返回业务预览
用户下一轮明确确认 → *_final 工具检查会话、请求 ID、有效期和状态
                   → MySQL 事务执行并标记完成
```

当前实现中的最终工具名分别为 `create_order`、`cancel_order` 和 `create_ticket`。确认必须是独立、无歧义的一轮消息；重复调用通过数据库幂等键返回同一结果。

## API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/auth/register` | 注册并登录 |
| `POST` | `/api/auth/login` | 登录 |
| `POST` | `/api/auth/logout` | 退出登录 |
| `GET` | `/api/auth/me` | 当前登录用户 |
| `POST` | `/api/chat` | 非流式聊天 |
| `POST` | `/api/chat/stream` | SSE token 流（前端默认） |
| `GET` | `/api/history/{conversation_id}` | 查询历史 |
| `DELETE` | `/api/history/{conversation_id}` | 清除历史 |
| `GET` | `/health` | 进程存活 |
| `GET` | `/ready` | LLM 配置与数据库就绪状态 |

聊天接口必须先登录。浏览器通过 HttpOnly Cookie 传递登录会话；首次聊天不传 `conversation_id`，服务返回的 `conversation_token` 还会绑定当前用户，其他账号无法借用它访问该会话。

## 测试与评测

```bash
# 后端：当前覆盖记忆并发/原子写、Agent 缓存、LLM 配置、会话访问与写操作确认
cd backend
python -m unittest discover -s tests -v
python -m compileall -q app evals

# 前端：组件/API 单测、类型检查、生产构建和产物冒烟测试
cd frontend
npm run lint
npm test
npm run build
npm run test:smoke
```

启动完整服务后可运行只读 Agent 评测：

```bash
cd backend
python evals/run_evals.py
```

评测脚本读取 `evals/cases.json`，检查工具路由、禁止工具和响应延迟，不会执行下单、取消或建单。

## 目录

```text
backend/app/       FastAPI、Agent、工具、记忆与数据模型
backend/tests/     后端单元测试
backend/evals/     Agent 黑盒评测
frontend/src/      React UI、Hooks 和 API 客户端
database/init/     MySQL schema、演示数据与旧库升级脚本
.github/workflows/ CI
docker-compose.yml 完整本地环境
```

## License

Apache License 2.0，详见 [LICENSE](LICENSE)。
