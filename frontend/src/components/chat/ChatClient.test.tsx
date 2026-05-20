import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import ChatClient from "./ChatClient";

const push = vi.fn();

const createSession = vi.fn();
const getChatQuota = vi.fn();
const getSession = vi.fn();
const listSessions = vi.fn();
const deleteSession = vi.fn();
const logout = vi.fn();
const streamMessage = vi.fn();
const updateSessionTitle = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/api", () => ({
  createSession: (...args: unknown[]) => createSession(...args),
  getChatQuota: (...args: unknown[]) => getChatQuota(...args),
  getSession: (...args: unknown[]) => getSession(...args),
  listSessions: (...args: unknown[]) => listSessions(...args),
  deleteSession: (...args: unknown[]) => deleteSession(...args),
  logout: (...args: unknown[]) => logout(...args),
  streamMessage: (...args: unknown[]) => streamMessage(...args),
  updateSessionTitle: (...args: unknown[]) => updateSessionTitle(...args),
}));

describe("ChatClient", () => {
  beforeEach(() => {
    push.mockReset();
    createSession.mockReset();
    getChatQuota.mockReset();
    getSession.mockReset();
    listSessions.mockReset();
    deleteSession.mockReset();
    logout.mockReset();
    streamMessage.mockReset();
    updateSessionTitle.mockReset();

    listSessions.mockResolvedValue([
      { id: "session-1", title: "Initial title", mode: "researcher", updated_at: "2026-05-16T00:00:00Z" },
    ]);
    getChatQuota.mockResolvedValue({
      token_limit: 1_000_000,
      total_token_count: 500,
      token_limit_reached: false,
      message: null,
    });
    getSession.mockResolvedValue({
      id: "session-1",
      mode: "researcher",
      messages: [],
    });
    updateSessionTitle.mockResolvedValue({
      id: "session-1",
      title: "Updated title",
      mode: "researcher",
      updated_at: "2026-05-16T00:00:00Z",
    });
    deleteSession.mockResolvedValue(undefined);
  });

  it("renders assistant responses as markdown", async () => {
    getSession.mockResolvedValueOnce({
      id: "session-1",
      mode: "researcher",
      messages: [
        {
          id: "message-1",
          session_id: "session-1",
          role: "assistant",
          content: "# Findings\n\n- First point\n- Second point",
          created_at: "2026-05-16T00:00:00Z",
        },
      ],
    });

    render(<ChatClient initialSessionId="session-1" />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Findings" })).toBeInTheDocument();
    });
    expect(screen.getByText("First point")).toBeInTheDocument();
    expect(screen.getByText("Second point")).toBeInTheDocument();
  });

  it("allows renaming a chat title from right-click menu", async () => {
    render(<ChatClient initialSessionId="session-1" />);

    await waitFor(() => {
      expect(screen.getByText("Initial title")).toBeInTheDocument();
    });

    fireEvent.contextMenu(screen.getByRole("button", { name: "Initial title" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Rename" }));

    const input = await screen.findByLabelText("Edit chat title");
    fireEvent.change(input, { target: { value: "Updated title" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(updateSessionTitle).toHaveBeenCalledWith("session-1", "Updated title");
    });
    await waitFor(() => {
      expect(screen.getByText("Updated title")).toBeInTheDocument();
    });
  });

  it("deletes a chat from right-click menu", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<ChatClient initialSessionId="session-1" />);

    await waitFor(() => {
      expect(screen.getByText("Initial title")).toBeInTheDocument();
    });

    fireEvent.contextMenu(screen.getByRole("button", { name: "Initial title" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));

    await waitFor(() => {
      expect(deleteSession).toHaveBeenCalledWith("session-1");
    });
    expect(push).toHaveBeenCalledWith("/chat");

    confirmSpy.mockRestore();
  });

  it("shows the token limit message when a new chat is blocked", async () => {
    createSession.mockRejectedValue(
      new Error("Your token limit has been reached. Please ask your lab admin for more tokens.")
    );

    render(<ChatClient />);

    fireEvent.click(await screen.findByRole("button", { name: /\+ new chat/i }));

    await waitFor(() => {
      expect(screen.getByText(/token limit has been reached/i)).toBeInTheDocument();
    });
  });

  it("shows token limit status on load while keeping existing chats browsable", async () => {
    getChatQuota.mockResolvedValue({
      token_limit: 1_000_000,
      total_token_count: 1_000_000,
      token_limit_reached: true,
      message: "Your token limit has been reached. Please ask your lab admin for more tokens.",
    });

    render(<ChatClient />);

    await waitFor(() => {
      expect(screen.getByText(/token limit has been reached/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /\+ new chat/i })).toBeDisabled();
    expect(screen.getByPlaceholderText("Token limit reached")).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Initial title" }));
    expect(push).toHaveBeenCalledWith("/chat/session-1");
  });
});
