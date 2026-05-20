import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import AdminUserClient from "./AdminUserClient";

const push = vi.fn();
const getAdminUser = vi.fn();
const updateAdminUserStatus = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/api", () => ({
  getAdminUser: (...args: unknown[]) => getAdminUser(...args),
  updateAdminUserStatus: (...args: unknown[]) => updateAdminUserStatus(...args),
}));

describe("AdminUserClient", () => {
  beforeEach(() => {
    push.mockReset();
    getAdminUser.mockReset();
    updateAdminUserStatus.mockReset();
  });

  it("shows user details and updates active status from the checkbox", async () => {
    getAdminUser.mockResolvedValue({
      id: "user-1",
      email: "researcher@example.com",
      full_name: "Researcher",
      role: "researcher",
      is_active: true,
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

  it("redirects to login when unauthorized", async () => {
    getAdminUser.mockRejectedValue(new Error("Unauthorized"));

    render(<AdminUserClient userId="user-1" />);

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith("/login");
    });
  });
});
