import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api/client";
import { ApiClientError } from "../api/client";
import { useChat } from "./useChat";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");

  return {
    ...actual,
    streamChatMessage: vi.fn(),
    getConversationHistory: vi.fn(),
    deleteConversationHistory: vi.fn(),
  };
});

const streamChatMessageMock = vi.mocked(api.streamChatMessage);
const getConversationHistoryMock = vi.mocked(api.getConversationHistory);
const deleteConversationHistoryMock = vi.mocked(api.deleteConversationHistory);

describe("useChat", () => {
  beforeEach(() => {
    window.localStorage.clear();
    streamChatMessageMock.mockReset();
    getConversationHistoryMock.mockReset();
    deleteConversationHistoryMock.mockReset();
  });

  it("restores persisted conversation history on startup", async () => {
    window.localStorage.setItem(
      "ai-logistics-chat.session.v3.default",
      JSON.stringify({
        conversationId: "conversation-1",
        conversationToken: "token-1",
      })
    );
    getConversationHistoryMock.mockResolvedValue({
      conversation_id: "conversation-1",
      count: 2,
      messages: [
        {
          role: "user",
          content: "我的订单在哪里？",
          timestamp: "2026-10-10T10:00:00",
        },
        {
          role: "assistant",
          content: "正在运输中。",
          timestamp: "2026-10-10T10:00:01",
        },
      ],
    });

    const { result } = renderHook(() => useChat());

    await waitFor(() => expect(result.current.isRestoring).toBe(false));
    expect(result.current.messages.map((message) => message.content)).toEqual([
      "我的订单在哪里？",
      "正在运输中。",
    ]);
    expect(getConversationHistoryMock).toHaveBeenCalledWith(
      {
        conversationId: "conversation-1",
        conversationToken: "token-1",
      },
      expect.any(AbortSignal)
    );
  });

  it("uses unique message ids and persists the server-issued session", async () => {
    streamChatMessageMock.mockImplementation(async (_message, _session, handlers) => {
      handlers.onConversation(
        { conversationId: "conversation-2", conversationToken: "token-2" },
        "request-2"
      );
      handlers.onDelta("您好，");
      handlers.onDelta("有什么可以帮您？");
    });
    const { result } = renderHook(() => useChat());

    act(() => result.current.setDraft("你好"));
    await act(async () => {
      await result.current.sendMessage();
    });

    const ids = result.current.messages.map((message) => message.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(JSON.parse(window.localStorage.getItem("ai-logistics-chat.session.v3.default") ?? "null")).toEqual(
      {
        conversationId: "conversation-2",
        conversationToken: "token-2",
      }
    );
  });

  it("keeps the current conversation when server deletion fails", async () => {
    window.localStorage.setItem(
      "ai-logistics-chat.session.v3.default",
      JSON.stringify({
        conversationId: "conversation-3",
        conversationToken: "token-3",
      })
    );
    getConversationHistoryMock.mockResolvedValue({
      conversation_id: "conversation-3",
      count: 0,
      messages: [],
    });
    deleteConversationHistoryMock.mockRejectedValue(
      new ApiClientError("http", "Internal server error.", 500)
    );
    const { result } = renderHook(() => useChat());
    await waitFor(() => expect(result.current.isRestoring).toBe(false));

    await act(async () => {
      await result.current.clearConversation();
    });

    expect(result.current.session?.conversationId).toBe("conversation-3");
    expect(result.current.notice?.message).toBe("清除会话失败，原会话已保留。");
  });

  it("cancels an in-flight request", async () => {
    streamChatMessageMock.mockImplementation((_message, _session, _handlers, signal) => {
      return new Promise((_resolve, reject) => {
        signal?.addEventListener(
          "abort",
          () => reject(new ApiClientError("aborted", "请求已取消。")),
          { once: true }
        );
      });
    });
    const { result } = renderHook(() => useChat());
    act(() => result.current.setDraft("请处理这个请求"));

    let request: Promise<boolean> | undefined;
    act(() => {
      request = result.current.sendMessage();
    });
    await waitFor(() => expect(result.current.isSending).toBe(true));
    act(() => result.current.cancelRequest());
    await act(async () => {
      await request;
    });

    expect(result.current.isSending).toBe(false);
    expect(result.current.messages[result.current.messages.length - 1]?.tone).toBe("notice");
  });
});
