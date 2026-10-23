# Frontend

React + TypeScript + Vite 的客服聊天界面。当前使用后端非流式 `/api/chat`，支持会话恢复、请求取消、服务状态、错误分类和工具调用标签。

## 开发

```bash
npm ci
npm run dev
```

默认后端地址是 `http://localhost:8000`。需要覆盖时创建 `.env.local`：

```env
VITE_API_URL=http://localhost:8000
```

## 验证

```bash
npm run lint
npm test
npm run build
npm run test:smoke
```

## 结构

```text
src/api/client.ts              API、超时、错误映射、会话 token
src/hooks/useChat.ts           消息与会话状态
src/hooks/useServiceHealth.ts  后端存活状态
src/components/                Header、消息列表、输入框
src/**/*.test.ts(x)            API 与组件测试
tests/build-smoke.test.mjs     构建产物冒烟测试
```

会话凭据以 `{ conversationId, conversationToken }` 成对保存在浏览器本地存储。继续聊天和删除历史时，客户端会发送 `X-Conversation-Token`；清空成功后会同时删除本地会话凭据。

## Docker

根目录的 Compose 会将前端构建为 Nginx 静态站点，并把 `/backend/*` 反向代理到 FastAPI：

```bash
docker compose up --build
```

访问 http://localhost:3000。

## License

Apache License 2.0。
