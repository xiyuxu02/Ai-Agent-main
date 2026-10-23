import { useEffect, useRef, useState } from "react";

import type { Message } from "../types";

interface MessageListProps {
  messages: Message[];
  isSending: boolean;
  isRestoring: boolean;
}

function formatTimestamp(timestamp: string): string {
  const value = new Date(timestamp);

  if (Number.isNaN(value.getTime())) {
    return "";
  }

  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(value);
}

function renderInlineText(text: string) {
  return text.split(/(\*\*.*?\*\*)/g).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={`${part}-${index}`}>{part.slice(2, -2)}</strong>;
    }

    return part;
  });
}

function MessageText({ content }: { content: string }) {
  return (
    <>
      {content.split("\n").map((line, index, lines) => (
        <span key={`${line}-${index}`}>
          {renderInlineText(line)}
          {index < lines.length - 1 && <br />}
        </span>
      ))}
    </>
  );
}

export function MessageList({ messages, isSending, isRestoring }: MessageListProps) {
  const containerRef = useRef<HTMLElement | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const previousMessageCountRef = useRef(messages.length);

  useEffect(() => {
    const hasNewOwnMessage =
      messages.length > previousMessageCountRef.current &&
      messages[messages.length - 1]?.role === "user";

    if (isNearBottom || hasNewOwnMessage) {
      endRef.current?.scrollIntoView({ behavior: "smooth" });
    }

    previousMessageCountRef.current = messages.length;
  }, [isNearBottom, isSending, messages]);

  const handleScroll = () => {
    const container = containerRef.current;

    if (!container) {
      return;
    }

    const distanceFromBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight;
    setIsNearBottom(distanceFromBottom < 80);
  };

  const scrollToLatest = () => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
    setIsNearBottom(true);
  };

  return (
    <main
      ref={containerRef}
      className="message-area"
      role="log"
      aria-live="polite"
      aria-relevant="additions"
      aria-busy={isSending || isRestoring}
      onScroll={handleScroll}
    >
      <div className="welcome-message">今天有什么可以帮您？</div>

      {isRestoring && (
        <div className="restore-status" role="status">
          正在恢复上次会话...
        </div>
      )}

      {messages.map((message) => {
        const timestamp = formatTimestamp(message.timestamp);

        return (
          <article
            key={message.id}
            className={`message-row ${message.role}`}
            aria-label={message.role === "assistant" ? "AI 客服消息" : "我的消息"}
          >
            {message.role === "assistant" && (
              <div className="avatar assistant-avatar" aria-hidden="true">
                🤖
              </div>
            )}

            <div
              className={`message-content ${
                message.role === "user" ? "user-content" : "assistant-content"
              }`}
            >
              <div className="message-meta">
                <span>{message.role === "assistant" ? "AI 客服" : "我"}</span>
                {timestamp && <time dateTime={message.timestamp}>{timestamp}</time>}
              </div>

              <div
                className={`message-bubble ${
                  message.role === "user" ? "user-bubble" : "assistant-bubble"
                } ${message.tone ? `message-${message.tone}` : ""}`}
              >
                <MessageText content={message.content} />
              </div>
            </div>

            {message.role === "user" && (
              <div className="avatar user-avatar" aria-hidden="true">
                👤
              </div>
            )}
          </article>
        );
      })}

      {isSending && (
        <div className="message-row assistant" role="status" aria-label="AI 正在处理">
          <div className="avatar assistant-avatar" aria-hidden="true">
            🤖
          </div>
          <div className="message-content assistant-content">
            <div className="message-meta">AI 客服</div>
            <div className="message-bubble assistant-bubble loading-message">
              <span className="loading-text">正在处理</span>
              <span className="loading-dot" aria-hidden="true" />
              <span className="loading-dot" aria-hidden="true" />
              <span className="loading-dot" aria-hidden="true" />
            </div>
          </div>
        </div>
      )}

      <div ref={endRef} />

      {!isNearBottom && (
        <button type="button" className="latest-button" onClick={scrollToLatest}>
          查看最新消息
        </button>
      )}
    </main>
  );
}
