import { FormEvent, KeyboardEvent, useEffect, useRef } from "react";

import { MAX_MESSAGE_LENGTH } from "../api/client";

interface ChatComposerProps {
  value: string;
  isSending: boolean;
  isDisabled: boolean;
  onChange: (value: string) => void;
  onSend: () => void;
  onCancel: () => void;
}

export function ChatComposer({
  value,
  isSending,
  isDisabled,
  onChange,
  onSend,
  onCancel,
}: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const wasSendingRef = useRef(false);
  const canSend = Boolean(value.trim()) && value.trim().length <= MAX_MESSAGE_LENGTH;

  useEffect(() => {
    const textarea = textareaRef.current;

    if (!textarea) {
      return;
    }

    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 140)}px`;
  }, [value]);

  useEffect(() => {
    if (wasSendingRef.current && !isSending && !isDisabled) {
      textareaRef.current?.focus();
    }

    wasSendingRef.current = isSending;
  }, [isDisabled, isSending]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (canSend && !isSending && !isDisabled) {
      onSend();
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    const isComposing = event.nativeEvent.isComposing || event.keyCode === 229;

    if (event.key === "Enter" && !event.shiftKey && !isComposing) {
      event.preventDefault();

      if (canSend && !isSending && !isDisabled) {
        onSend();
      }
    }
  };

  return (
    <div className="composer-shell">
      <form className="input-area" onSubmit={handleSubmit}>
        <label className="sr-only" htmlFor="chat-input">
          输入您的问题
        </label>
        <textarea
          id="chat-input"
          ref={textareaRef}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="请输入您的问题，例如：我想买一个无线蓝牙耳机"
          disabled={isDisabled}
          maxLength={MAX_MESSAGE_LENGTH}
          rows={1}
          aria-describedby="chat-input-help chat-input-count"
        />

        {isSending ? (
          <button type="button" className="stop-button" onClick={onCancel}>
            停止
          </button>
        ) : (
          <button
            type="submit"
            disabled={!canSend || isDisabled}
            className="send-button"
          >
            发送
          </button>
        )}
      </form>

      <div className="input-tip">
        <span id="chat-input-help">Enter 发送 · Shift + Enter 换行</span>
        <span id="chat-input-count" aria-live="polite">
          {value.length}/{MAX_MESSAGE_LENGTH}
        </span>
      </div>
    </div>
  );
}
