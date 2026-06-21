import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import AdminUserClient from "./AdminUserClient";

const push = vi.fn();
const getAdminUser = vi.fn();
const updateAdminUserRole = vi.fn();
const updateAdminUserStatus = vi.fn();
const updateAdminUserTokenLimit = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/api", () => ({
  getAdminUser: (...args: unknown[]) => getAdminUser(...args),
  updateAdminUserRole: (...args: unknown[]) => updateAdminUserRole(...args),
  updateAdminUserStatus: (...args: unknown[]) => updateAdminUserStatus(...args),
  updateAdminUserTokenLimit: (...args: unknown[]) => updateAdminUserTokenLimit(...args),
}));

describe("AdminUserClient", () => {
  beforeEach(() => {
    push.mockReset();
    getAdminUser.mockReset();
    updateAdminUserRole.mockReset();
    updateAdminUserStatus.mockReset();
    updateAdminUserTokenLimit.mockReset();
  });

  it("shows user details and updates active status from the checkbox", async () => {
    getAdminUser.mockResolvedValue({
      id: "user-1",
      email: "researcher@example.com",
      full_name: "Researcher",
      role: "researcher",
      is_active: true,
      token_limit: 1_000_000,
      token_limit_reached: false,
      usage: {
        session_count: 3,
        user_message_count: 9,
        assistant_message_count: 8,
        prompt_token_count: 2000,
        completion_token_count: 700,
        total_token_count: 2700,
        last_active_at: null,
        avg_latency_ms: 612.2,
      },
    });
    updateAdminUserStatus.mockResolvedValue({
      id: "user-1",
      email: "researcher@example.com",
      full_name: "Researcher",
      role: "researcher",
      is_active: false,
      token_limit: 1_000_000,
      token_limit_reached: false,
      usage: {
        session_count: 3,
        user_message_count: 9,
        assistant_message_count: 8,
        prompt_token_count: 2000,
        completion_token_count: 700,
        total_token_count: 2700,
        last_active_at: null,
        avg_latency_ms: 612.2,
      },
    });

    render(<AdminUserClient userId="user-1" />);

    await waitFor(() => {
      expect(screen.getByText("researcher@example.com")).toBeInTheDocument();
    });
    expect(screen.getByText("Sessions")).toBeInTheDocument();
    expect(screen.getByText("Questions")).toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument();
    expect(screen.getByText("Total Tokens")).toBeInTheDocument();
    expect(screen.getByText("2,700")).toBeInTheDocument();
    expect(screen.getByText("2,000")).toBeInTheDocument();
    expect(screen.getByText("700")).toBeInTheDocument();
    expect(screen.getByText("612 ms")).toBeInTheDocument();
    expect(screen.getByText("2,700 of 1,000,000 tokens used")).toBeInTheDocument();

    const checkbox = screen.getByRole("checkbox", { name: /active account/i });
    expect(checkbox).toBeChecked();
    fireEvent.click(checkbox);

    await waitFor(() => {
      expect(updateAdminUserStatus).toHaveBeenCalledWith("user-1", false);
    });
    await waitFor(() => {
      expect(screen.getByRole("checkbox", { name: /active account/i })).not.toBeChecked();
    });
  });

  it("updates the user's role from the role selector", async () => {
    getAdminUser.mockResolvedValue({
      id: "user-1",
      email: "researcher@example.com",
      full_name: "Researcher",
      role: "researcher",
      is_active: true,
      token_limit: 1_000_000,
      token_limit_reached: false,
      usage: {
        session_count: 3,
        user_message_count: 9,
        assistant_message_count: 8,
        prompt_token_count: 2000,
        completion_token_count: 700,
        total_token_count: 2700,
        last_active_at: null,
        avg_latency_ms: 612.2,
      },
    });
    updateAdminUserRole.mockResolvedValue({
      id: "user-1",
      email: "researcher@example.com",
      full_name: "Researcher",
      role: "evaluator",
      is_active: true,
      token_limit: 1_000_000,
      token_limit_reached: false,
      usage: {
        session_count: 3,
        user_message_count: 9,
        assistant_message_count: 8,
        prompt_token_count: 2000,
        completion_token_count: 700,
        total_token_count: 2700,
        last_active_at: null,
        avg_latency_ms: 612.2,
      },
    });

    render(<AdminUserClient userId="user-1" />);

    const roleSelect = await screen.findByLabelText("User role");
    expect(roleSelect).toHaveValue("researcher");
    expect(screen.getByRole("option", { name: "Evaluator" })).toBeInTheDocument();
    fireEvent.change(roleSelect, { target: { value: "evaluator" } });

    await waitFor(() => {
      expect(updateAdminUserRole).toHaveBeenCalledWith("user-1", "evaluator");
    });
    await waitFor(() => {
      expect(screen.getByLabelText("User role")).toHaveValue("evaluator");
    });
  });

  it("manually edits and saves the token limit from the user page", async () => {
    getAdminUser.mockResolvedValue({
      id: "user-1",
      email: "researcher@example.com",
      full_name: "Researcher",
      role: "researcher",
      is_active: true,
      token_limit: 1_000_000,
      token_limit_reached: false,
      usage: {
        session_count: 3,
        user_message_count: 9,
        assistant_message_count: 8,
        prompt_token_count: 2000,
        completion_token_count: 700,
        total_token_count: 2700,
        last_active_at: null,
        avg_latency_ms: 612.2,
      },
    });
    updateAdminUserTokenLimit.mockResolvedValue({
      id: "user-1",
      email: "researcher@example.com",
      full_name: "Researcher",
      role: "researcher",
      is_active: true,
      token_limit: 5_000_000,
      token_limit_reached: false,
      usage: {
        session_count: 3,
        user_message_count: 9,
        assistant_message_count: 8,
        prompt_token_count: 2000,
        completion_token_count: 700,
        total_token_count: 2700,
        last_active_at: null,
        avg_latency_ms: 612.2,
      },
    });

    render(<AdminUserClient userId="user-1" />);

    fireEvent.click(await screen.findByRole("button", { name: "1,000,000 tokens" }));
    const input = await screen.findByLabelText("Editable token limit");
    fireEvent.change(input, { target: { value: "5000000" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(updateAdminUserTokenLimit).toHaveBeenCalledWith("user-1", 5_000_000);
    });
    await waitFor(() => {
      expect(screen.getByText("2,700 of 5,000,000 tokens used")).toBeInTheDocument();
    });
  });

  it("adds the selected quick amount to the current token limit", async () => {
    getAdminUser.mockResolvedValue({
      id: "user-1",
      email: "researcher@example.com",
      full_name: "Researcher",
      role: "researcher",
      is_active: true,
      token_limit: 1_000_000,
      token_limit_reached: false,
      usage: {
        session_count: 3,
        user_message_count: 9,
        assistant_message_count: 8,
        prompt_token_count: 2000,
        completion_token_count: 700,
        total_token_count: 2700,
        last_active_at: null,
        avg_latency_ms: 612.2,
      },
    });
    updateAdminUserTokenLimit.mockResolvedValue({
      id: "user-1",
      email: "researcher@example.com",
      full_name: "Researcher",
      role: "researcher",
      is_active: true,
      token_limit: 6_000_000,
      token_limit_reached: false,
      usage: {
        session_count: 3,
        user_message_count: 9,
        assistant_message_count: 8,
        prompt_token_count: 2000,
        completion_token_count: 700,
        total_token_count: 2700,
        last_active_at: null,
        avg_latency_ms: 612.2,
      },
    });

    render(<AdminUserClient userId="user-1" />);

    fireEvent.click(await screen.findByRole("button", { name: "1,000,000 tokens" }));
    fireEvent.change(await screen.findByLabelText("Token limit amount to add"), {
      target: { value: "5000000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => {
      expect(updateAdminUserTokenLimit).toHaveBeenCalledWith("user-1", 6_000_000);
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "6,000,000 tokens" })).toBeInTheDocument();
    });
  });

  it("redirects to login when unauthorized", async () => {
    getAdminUser.mockRejectedValue(new Error("Unauthorized"));

    render(<AdminUserClient userId="user-1" />);

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith("/login");
    });
  });
});
