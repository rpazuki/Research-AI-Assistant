import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import AdminUsersClient from "./AdminUsersClient";

const push = vi.fn();
const refresh = vi.fn();
const listAdminUsers = vi.fn();
const logout = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

vi.mock("@/lib/api", () => ({
  listAdminUsers: (...args: unknown[]) => listAdminUsers(...args),
  logout: (...args: unknown[]) => logout(...args),
}));

describe("AdminUsersClient", () => {
  beforeEach(() => {
    push.mockReset();
    refresh.mockReset();
    listAdminUsers.mockReset();
    logout.mockReset();
  });

  it("lists users with links to their user pages", async () => {
    listAdminUsers.mockResolvedValue([
      {
        id: "user-1",
        email: "researcher@example.com",
        full_name: "Researcher",
        role: "researcher",
        is_active: true,
        token_limit: 1_000_000,
        token_limit_reached: false,
        usage: {
          session_count: 2,
          user_message_count: 7,
          assistant_message_count: 6,
          prompt_token_count: 1200,
          completion_token_count: 345,
          total_token_count: 1545,
          last_active_at: null,
          avg_latency_ms: 430.7,
        },
      },
      {
        id: "user-2",
        email: "near-limit@example.com",
        full_name: "Near Limit",
        role: "researcher",
        is_active: true,
        token_limit: 1_000_000,
        token_limit_reached: false,
        usage: {
          session_count: 1,
          user_message_count: 2,
          assistant_message_count: 2,
          prompt_token_count: 600_000,
          completion_token_count: 300_000,
          total_token_count: 900_000,
          last_active_at: null,
          avg_latency_ms: null,
        },
      },
      {
        id: "user-3",
        email: "limited@example.com",
        full_name: "Limited User",
        role: "researcher",
        is_active: true,
        token_limit: 1_000_000,
        token_limit_reached: true,
        usage: {
          session_count: 1,
          user_message_count: 2,
          assistant_message_count: 2,
          prompt_token_count: 700_000,
          completion_token_count: 300_000,
          total_token_count: 1_000_000,
          last_active_at: null,
          avg_latency_ms: null,
        },
      },
      {
        id: "user-4",
        email: "inactive-limited@example.com",
        full_name: null,
        role: "researcher",
        is_active: false,
        token_limit: 1_000_000,
        token_limit_reached: true,
        usage: {
          session_count: 0,
          user_message_count: 0,
          assistant_message_count: 0,
          prompt_token_count: 0,
          completion_token_count: 0,
          total_token_count: 0,
          last_active_at: null,
          avg_latency_ms: null,
        },
      },
    ]);

    render(<AdminUsersClient />);

    await waitFor(() => {
      expect(screen.getByText("researcher@example.com")).toBeInTheDocument();
    });
    expect(screen.getByText("near-limit@example.com")).toBeInTheDocument();
    expect(screen.getByText("limited@example.com")).toBeInTheDocument();
    expect(screen.getByText("inactive-limited@example.com")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("1,545")).toBeInTheDocument();
    expect(screen.getByText("431 ms")).toBeInTheDocument();
    expect(screen.getAllByText("Never")).toHaveLength(4);
    expect(screen.getAllByText("Active")[0]).toHaveClass("bg-green-50", "text-green-700");
    expect(screen.getAllByText("Active")[1]).toHaveClass("bg-yellow-50", "text-yellow-700");
    expect(screen.getByText("Token limit")).toHaveClass("bg-red-50", "text-red-700");
    expect(screen.getByText("Inactive")).toHaveClass("bg-gray-100", "text-gray-600");
    expect(screen.getByText("inactive-limited@example.com").closest("tr")).not.toHaveTextContent(
      "Token limit"
    );
    expect(screen.getByRole("link", { name: "Invite users" })).toHaveAttribute(
      "href",
      "/admin/invitations"
    );
    expect(screen.getAllByRole("link", { name: "View user" })[0]).toHaveAttribute(
      "href",
      "/admin/users/user-1"
    );
  });

  it("redirects to login when unauthorized", async () => {
    listAdminUsers.mockRejectedValue(new Error("Unauthorized"));

    render(<AdminUsersClient />);

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith("/login");
    });
  });
});
