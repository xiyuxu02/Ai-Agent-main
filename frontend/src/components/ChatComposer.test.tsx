import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { ChatComposer } from "./ChatComposer";

function renderComposer(overrides: Partial<ComponentProps<typeof ChatComposer>> = {}) {
  const props: ComponentProps<typeof ChatComposer> = {
    value: "查询订单",
    isSending: false,
    isDisabled: false,
    onChange: vi.fn(),
    onSend: vi.fn(),
    onCancel: vi.fn(),
    ...overrides,
  };

  render(<ChatComposer {...props} />);
  return props;
}

describe("ChatComposer", () => {
  it("does not send while a Chinese IME composition is active", () => {
    const props = renderComposer();
    const input = screen.getByLabelText("输入您的问题");

    fireEvent.keyDown(input, {
      key: "Enter",
      code: "Enter",
      isComposing: true,
    });
    expect(props.onSend).not.toHaveBeenCalled();

    fireEvent.keyDown(input, {
      key: "Enter",
      code: "Enter",
      isComposing: false,
    });
    expect(props.onSend).toHaveBeenCalledTimes(1);
  });

  it("shows a stop action while a request is running", () => {
    const props = renderComposer({ isSending: true });

    fireEvent.click(screen.getByRole("button", { name: "停止" }));

    expect(props.onCancel).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("输入您的问题")).not.toBeDisabled();
  });
});
