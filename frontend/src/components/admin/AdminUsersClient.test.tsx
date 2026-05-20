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
        email: "inactive@example.com",
        full_name: null,
        role: "researcher",
        is_active: false,
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
    expect(screen.getByText("Inactive")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("1,545")).toBeInTheDocument();
    expect(screen.getByText("431 ms")).toBeInTheDocument();
    expect(screen.getAllByText("Never")).toHaveLength(2);
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
