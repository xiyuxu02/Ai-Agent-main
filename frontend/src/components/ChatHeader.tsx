import type { ServiceStatus } from "../types";

interface ChatHeaderProps {
  serviceStatus: ServiceStatus;
  serviceVersion: string | null;
  isBusy: boolean;
  isClearing: boolean;
  onNewConversation: () => void;
  displayName: string;
  onLogout: () => void;
}

const statusLabels: Record<ServiceStatus, string> = {
  checking: "正在连接",
  online: "在线服务",
  offline: "服务离线",
};

export function ChatHeader({
  serviceStatus,
  serviceVersion,
  isBusy,
  isClearing,
  onNewConversation,
  displayName,
  onLogout,
}: ChatHeaderProps) {
  return (
    <header className="chat-header">
      <div className="header-left">
        <div className="avatar assistant-avatar" aria-hidden="true">
          🤖
        </div>

        <div className="header-info">
          <h1>AI 物流客服</h1>
          <div
            className={`online-status status-${serviceStatus}`}
            aria-live="polite"
            title={serviceVersion ? `服务版本 ${serviceVersion}` : undefined}
          >
            <span className="status-dot" aria-hidden="true" />
            {statusLabels[serviceStatus]}
          </div>
        </div>
      </div>

      <div className="header-actions">
      <span className="signed-in-user" title="当前登录用户">{displayName}</span>
      <button
        type="button"
        className="clear-button"
        onClick={onNewConversation}
        disabled={isBusy}
      >
        <span className="clear-icon" aria-hidden="true">
          ＋
        </span>
        {isClearing ? "清理中..." : "新建会话"}
      </button>
      <button type="button" className="logout-button" onClick={onLogout} disabled={isBusy}>退出</button>
      </div>
    </header>
  );
}
