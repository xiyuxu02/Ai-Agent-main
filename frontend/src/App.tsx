import { ChatComposer } from "./components/ChatComposer";
import { AuthPage } from "./components/AuthPage";
import { ChatHeader } from "./components/ChatHeader";
import { MessageList } from "./components/MessageList";
import { useChat } from "./hooks/useChat";
import { useServiceHealth } from "./hooks/useServiceHealth";
import { useAuth } from "./hooks/useAuth";
import type { AuthUser } from "./types";

function ChatApp({
  user,
  onLogout,
  onUnauthorized,
}: {
  user: AuthUser;
  onLogout: () => void;
  onUnauthorized: () => void;
}) {
  const chat = useChat(user.user_id, onUnauthorized);
  const service = useServiceHealth();
  const isHeaderBusy = chat.isSending || chat.isClearing || chat.isRestoring;

  return (
    <div className="app">
      <section className="chat-container" aria-label="AI 物流客服对话">
        <ChatHeader
          serviceStatus={service.status}
          serviceVersion={service.version}
          isBusy={isHeaderBusy}
          isClearing={chat.isClearing}
          onNewConversation={() => {
            void chat.clearConversation();
          }}
          displayName={user.display_name}
          onLogout={onLogout}
        />

        {chat.notice && (
          <div
            className={`notice-banner notice-${chat.notice.tone}`}
            role={chat.notice.tone === "error" ? "alert" : "status"}
          >
            <span>{chat.notice.message}</span>
            <button type="button" onClick={chat.dismissNotice} aria-label="关闭提示">
              ×
            </button>
          </div>
        )}

        <MessageList
          messages={chat.messages}
          isSending={chat.isSending}
          isRestoring={chat.isRestoring}
        />

        <ChatComposer
          value={chat.draft}
          isSending={chat.isSending}
          isDisabled={chat.isClearing || chat.isRestoring}
          onChange={chat.setDraft}
          onSend={() => {
            void chat.sendMessage();
          }}
          onCancel={chat.cancelRequest}
        />
      </section>
    </div>
  );
}

function App() {
  const auth = useAuth();

  if (auth.isLoading) {
    return <div className="auth-loading">正在检查登录状态...</div>;
  }

  if (!auth.user) {
    return <AuthPage error={auth.error} onLogin={auth.login} onRegister={auth.register} />;
  }

  return (
    <ChatApp
      key={auth.user.user_id}
      user={auth.user}
      onLogout={() => void auth.logout()}
      onUnauthorized={auth.expireSession}
    />
  );
}

export default App;
