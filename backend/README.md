# Backend

FastAPI + LangChain 1.x 的智能客服后端，包含账号认证、用户隔离、工具调用、MySQL 业务写入、token 级 SSE、限流与健康检查。

## 启动

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

复制 `.env.example` 为 `.env`，配置 LLM 和 MySQL 后运行：

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API 文档位于 http://localhost:8000/docs。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/auth/register` | 注册并设置 HttpOnly Cookie |
| `POST` | `/api/auth/login` | 登录 |
| `POST` | `/api/auth/logout` | 注销当前会话 |
| `GET` | `/api/auth/me` | 读取当前用户 |
| `POST` | `/api/chat` | JSON 聊天响应 |
| `POST` | `/api/chat/stream` | SSE token 流 |
| `GET` | `/api/history/{id}` | 获取会话历史 |
| `DELETE` | `/api/history/{id}` | 删除会话历史 |
| `GET` | `/health` | 存活检查 |
| `GET` | `/ready` | 检查 API Key 和 MySQL |

首次请求示例：

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"查询 ORD2026001 的状态"}'
```

响应中的 `conversation_token` 只用于访问该会话。后续请求同时传 `conversation_id` 和请求头：

```text
X-Conversation-Token: <conversation_token>
```

## 工具

系统注册 16 个工具：

- 通用：`get_weather`、`calculate`、`get_current_time`
- 知识与商品：`search_knowledge`、`FAQ_answer`、`get_product_catalog`
- 用户与查询：`get_user_info`、`get_order_status`、`get_logistics_tracking`、`get_ticket`
- 两阶段写入：`prepare_order` / `create_order`、`prepare_cancel_order` / `cancel_order`、`prepare_ticket` / `create_ticket`

最终写工具不接受模型提供的业务参数，而是读取当前会话的待确认记录。服务端还会校验独立确认消息、不同 `request_id`、有效期、用户归属和数据库状态。

## 数据库

`../database/init/001_schema.sql` 创建业务表；`004_add_auth.sql` 创建用户与登录会话表。密码只保存 PBKDF2-SHA256 加盐哈希，登录 Cookie 为 HttpOnly，数据库只保存随机会话令牌的 SHA-256 摘要。后端启动也会自动补齐认证表，兼容已有数据卷。

## 验证

```bash
python -m pip check
python -m unittest discover -s tests -v
python -m compileall -q app evals
```

完整服务运行后执行只读评测：

```bash
python evals/run_evals.py
```

## 部署注意

- 必须设置稳定且保密的 `CONVERSATION_SIGNING_SECRET`。
- JSON 记忆只适合单实例；多 worker/多副本需要共享存储。
- HTTPS 部署必须把 `AUTH_COOKIE_SECURE` 设为 `true`。
- `AGENT_VERBOSE` 在对外环境保持 `false`。

## License

Apache License 2.0。
