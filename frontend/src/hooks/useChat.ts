import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiClientError,
  deleteConversationHistory,
  getConversationHistory,
  MAX_MESSAGE_LENGTH,
  streamChatMessage,
} from "../api/client";
import type { ConversationSession, Message, UiNotice } from "../types";

const SESSION_STORAGE_KEY_PREFIX = "ai-logistics-chat.session.v3";
const CONVERSATION_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;

export const WELCOME_MESSAGE =
  "您好！我是星星科技 AI 物流客服，很高兴为您服务 😊\n\n" +
  "您可以直接告诉我您的需求，例如：\n" +
  "• 我想买一个无线蓝牙耳机\n" +
  "• 帮我查询订单状态\n" +
  "• 帮我跟踪物流进度\n" +
  "• 我想取消一个订单";

let messageSequence = 0;

function createMessageId(prefix: string): string {
  messageSequence += 1;
  return `${prefix}-${Date.now()}-${messageSequence}`;
}

function createWelcomeMessage(): Message {
  return {
    id: createMessageId("welcome"),
    role: "assistant",
    content: WELCOME_MESSAGE,
    timestamp: new Date().toISOString(),
  };
}

function isConversationSession(value: unknown): value is ConversationSession {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const session = value as Partial<ConversationSession>;
  return (
    typeof session.conversationId === "string" &&
    CONVERSATION_ID_PATTERN.test(session.conversationId) &&
    typeof session.conversationToken === "string" &&
    session.conversationToken.length > 0
  );
}

function sessionStorageKey(userId: string): string {
  return `${SESSION_STORAGE_KEY_PREFIX}.${userId}`;
}

function readStoredSession(userId: string): ConversationSession | null {
  try {
    const storageKey = sessionStorageKey(userId);
    const rawValue = window.localStorage.getItem(storageKey);

    if (!rawValue) {
      return null;
    }

    const parsed = JSON.parse(rawValue) as unknown;

    if (isConversationSession(parsed)) {
      return parsed;
    }

    window.localStorage.removeItem(storageKey);
  } catch {
    try {
      window.localStorage.removeItem(sessionStorageKey(userId));
    } catch {
      // Ignore storage access failures in privacy-restricted browser contexts.
    }
  }

  return null;
}

function writeStoredSession(userId: string, session: ConversationSession | null): void {
  try {
    if (session) {
      window.localStorage.setItem(sessionStorageKey(userId), JSON.stringify(session));
    } else {
      window.localStorage.removeItem(sessionStorageKey(userId));
    }
  } catch {
    // localStorage may be unavailable in privacy-restricted browser contexts.
  }
}

function describeChatError(error: unknown): string {
  if (!(error instanceof ApiClientError)) {
    return "发生了未知错误，请稍后重试。";
  }

  if (error.kind === "aborted") {
    return "已停止本次请求，您可以继续发送其他问题。";
  }

  if (error.kind === "timeout") {
    return "请求超过 60 秒仍未完成，请稍后重试。";
  }

  if (error.kind === "network") {
    return "无法连接客服服务，请检查网络或确认后端已经启动。";
  }

  if (error.kind === "invalid-response") {
    return "服务响应格式异常，请刷新页面后重试。";
  }

  if (error.status === 401) {
    return "登录已过期，请重新登录。";
  }

  if (error.status === 403) {
    return "会话凭证已失效，下一条消息将开启新会话。";
  }

  if (error.status === 422) {
    return "消息格式不符合要求，请检查内容和长度后重试。";
  }

  if (error.status === 429) {
    return "请求过于频繁，请稍等片刻后再试。";
  }

  if (error.status === 502) {
    return "Agent 暂时无法完成该请求，请稍后重试。";
  }

  if (error.status && error.status >= 500) {
    return "客服服务内部出错，请稍后重试。";
  }

  return "请求未能完成，请稍后重试。";
}

function describeConversationError(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (error.kind === "network" || error.kind === "timeout") {
      return "暂时无法连接服务，会话尚未清除。";
    }

    if (error.status === 401 || error.status === 403) {
      return "会话凭证已失效，请刷新页面后重试。";
    }
  }

  return "清除会话失败，原会话已保留。";
}

export function useChat(userId = "default", onUnauthorized?: () => void) {
  const [initialSession] = useState<ConversationSession | null>(() => readStoredSession(userId));
  const initialSessionRef = useRef<ConversationSession | null>(initialSession);
  const [session, setSession] = useState<ConversationSession | null>(
    initialSessionRef.current
  );
  const [messages, setMessages] = useState<Message[]>(() => [createWelcomeMessage()]);
  const [draft, setDraft] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const [isRestoring, setIsRestoring] = useState(Boolean(initialSessionRef.current));
  const [notice, setNotice] = useState<UiNotice | null>(null);

  const mountedRef = useRef(true);
  const sendingRef = useRef(false);
  const clearingRef = useRef(false);
  const chatControllerRef = useRef<AbortController | null>(null);
  const clearControllerRef = useRef<AbortController | null>(null);

  const commitSession = useCallback((nextSession: ConversationSession | null) => {
    setSession(nextSession);
    writeStoredSession(userId, nextSession);
  }, [userId]);

  useEffect(() => {
    mountedRef.current = true;

    return () => {
      mountedRef.current = false;
      chatControllerRef.current?.abort();
      clearControllerRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    const storedSession = initialSessionRef.current;

    if (!storedSession) {
      setIsRestoring(false);
      return;
    }

    const controller = new AbortController();

    const restoreHistory = async () => {
      try {
        const response = await getConversationHistory(storedSession, controller.signal);
        const restoredMessages = response.messages
          .filter((message) => message.role === "user" || message.role === "assistant")
          .map<Message>((message) => ({
            id: createMessageId("history"),
            role: message.role === "user" ? "user" : "assistant",
            content: message.content,
            timestamp: message.timestamp,
          }));

        if (mountedRef.current) {
          setMessages(restoredMessages.length > 0 ? restoredMessages : [createWelcomeMessage()]);
          setNotice(null);
        }
      } catch (error) {
        if (
          error instanceof ApiClientError &&
          error.kind === "aborted"
        ) {
          return;
        }

        if (!mountedRef.current) {
          return;
        }

        if (
          error instanceof ApiClientError &&
          (error.status === 401 || error.status === 403 || error.status === 422)
        ) {
          commitSession(null);
          if (error.status === 401) onUnauthorized?.();
          setNotice({
            tone: "error",
            message: "保存的会话已失效，已为您准备一个新会话。",
          });
        } else {
          setNotice({
            tone: "error",
            message: "暂时无法恢复历史消息；会话标识仍已保留，可稍后刷新重试。",
          });
        }
      } finally {
        if (mountedRef.current && !controller.signal.aborted) {
          setIsRestoring(false);
        }
      }
    };

    void restoreHistory();

    return () => controller.abort();
  }, [commitSession, onUnauthorized]);

  const sendMessage = useCallback(async (): Promise<boolean> => {
    const message = draft.trim();

    if (
      !message ||
      message.length > MAX_MESSAGE_LENGTH ||
      sendingRef.current ||
      clearingRef.current ||
      isRestoring
    ) {
      return false;
    }

    const userMessage: Message = {
      id: createMessageId("user"),
      role: "user",
      content: message,
      timestamp: new Date().toISOString(),
    };

    sendingRef.current = true;
    setIsSending(true);
    setMessages((current) => [...current, userMessage]);
    setDraft("");
    setNotice(null);

    const controller = new AbortController();
    chatControllerRef.current = controller;
    const assistantId = createMessageId("assistant");
    let receivedText = false;

    try {
      await streamChatMessage(
        message,
        session,
        {
          onConversation: (nextSession) => {
            if (mountedRef.current) commitSession(nextSession);
          },
          onDelta: (delta) => {
            if (!mountedRef.current || !delta) return;
            receivedText = true;
            setMessages((current) => {
              const existingIndex = current.findIndex((item) => item.id === assistantId);
              if (existingIndex === -1) {
                return [
                  ...current,
                  {
                    id: assistantId,
                    role: "assistant",
                    content: delta,
                    timestamp: new Date().toISOString(),
                  },
                ];
              }
              return current.map((item) =>
                item.id === assistantId
                  ? { ...item, content: item.content + delta }
                  : item
              );
            });
          },
        },
        controller.signal
      );

      if (!mountedRef.current) {
        return false;
      }

      if (!receivedText) {
        setMessages((current) => [
          ...current,
          {
            id: assistantId,
            role: "assistant",
            content: "抱歉，我暂时无法生成回复，请稍后重试。",
            timestamp: new Date().toISOString(),
            tone: "error",
          },
        ]);
      }
      return true;
    } catch (error) {
      if (!mountedRef.current) {
        return false;
      }

      const isExpiredSession =
        error instanceof ApiClientError &&
        (error.status === 401 || error.status === 403);

      if (isExpiredSession) {
        commitSession(null);
        if (error instanceof ApiClientError && error.status === 401) {
          onUnauthorized?.();
        }
      }

      setMessages((current) => [
        ...current,
        {
          id: createMessageId("error"),
          role: "assistant",
          content: describeChatError(error),
          timestamp: new Date().toISOString(),
          tone:
            error instanceof ApiClientError && error.kind === "aborted"
              ? "notice"
              : "error",
        },
      ]);
      return false;
    } finally {
      if (chatControllerRef.current === controller) {
        chatControllerRef.current = null;
      }

      sendingRef.current = false;

      if (mountedRef.current) {
        setIsSending(false);
      }
    }
  }, [commitSession, draft, isRestoring, onUnauthorized, session]);

  const cancelRequest = useCallback(() => {
    chatControllerRef.current?.abort();
  }, []);

  const clearConversation = useCallback(async (): Promise<boolean> => {
    if (sendingRef.current || clearingRef.current || isRestoring) {
      return false;
    }

    clearingRef.current = true;
    setIsClearing(true);
    setNotice(null);

    const controller = new AbortController();
    clearControllerRef.current = controller;

    try {
      if (session) {
        await deleteConversationHistory(session, controller.signal);
      }

      if (!mountedRef.current) {
        return false;
      }

      commitSession(null);
      setMessages([createWelcomeMessage()]);
      setDraft("");
      return true;
    } catch (error) {
      if (
        error instanceof ApiClientError &&
        error.kind === "aborted" &&
        !mountedRef.current
      ) {
        return false;
      }

      if (mountedRef.current) {
        setNotice({ tone: "error", message: describeConversationError(error) });
      }
      return false;
    } finally {
      if (clearControllerRef.current === controller) {
        clearControllerRef.current = null;
      }

      clearingRef.current = false;

      if (mountedRef.current) {
        setIsClearing(false);
      }
    }
  }, [commitSession, isRestoring, session]);

  return {
    messages,
    draft,
    setDraft,
    session,
    isSending,
    isClearing,
    isRestoring,
    notice,
    dismissNotice: () => setNotice(null),
    sendMessage,
    cancelRequest,
    clearConversation,
  };
}
