import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getConversationHistory,
  sendChatMessage,
  streamChatMessage,
} from "./client";

describe("API client", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  it("sends the conversation token on an existing conversation", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          conversation_id: "conversation-1",
          conversation_token: "token-1",
          messages: [],
          count: 0,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );

    await getConversationHistory({
      conversationId: "conversation-1",
      conversationToken: "token-1",
    });

    const [, request] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(request.headers).get("X-Conversation-Token")).toBe("token-1");
  });

  it("does not send a conversation token for the first message", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          message: "您好",
          conversation_id: "conversation-2",
          conversation_token: "token-2",
          request_id: "request-2",
          tools_used: [],
          timestamp: "2026-10-10T10:00:00",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );

    await sendChatMessage("你好", null);

    const [, request] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(request.headers).has("X-Conversation-Token")).toBe(false);
  });

  it("preserves the HTTP status for classified error handling", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ error: "Invalid request." }), {
        status: 422,
        headers: { "Content-Type": "application/json" },
      })
    );

    const request = sendChatMessage("无效消息", null);

    await expect(request).rejects.toEqual(
      expect.objectContaining({ kind: "http", status: 422 })
    );
  });

  it("parses conversation metadata and incremental SSE tokens", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        'event: conversation\ndata: {"conversation_id":"conversation-3","conversation_token":"token-3","request_id":"request-3"}\n\n' +
          'event: message\ndata: {"delta":"你"}\n\n' +
          'event: message\ndata: {"delta":"好"}\n\n' +
          'event: done\ndata: {"request_id":"request-3"}\n\n',
        { status: 200, headers: { "Content-Type": "text/event-stream" } }
      )
    );
    const deltas: string[] = [];
    let issuedSession = null;

    await streamChatMessage("你好", null, {
      onConversation: (session) => {
        issuedSession = session;
      },
      onDelta: (delta) => deltas.push(delta),
    });

    expect(issuedSession).toEqual({
      conversationId: "conversation-3",
      conversationToken: "token-3",
    });
    expect(deltas).toEqual(["你", "好"]);
    const [, request] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(request.credentials).toBe("include");
  });
});
