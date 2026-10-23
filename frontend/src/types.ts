export type MessageRole = "user" | "assistant";

export type MessageTone = "default" | "error" | "notice";

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: string;
  tone?: MessageTone;
}

export interface ConversationSession {
  conversationId: string;
  conversationToken: string;
}

export type ServiceStatus = "checking" | "online" | "offline";

export interface UiNotice {
  tone: "info" | "error";
  message: string;
}

export interface AuthUser {
  user_id: string;
  username: string;
  display_name: string;
}
