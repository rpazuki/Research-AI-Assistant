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
      },
      {
        id: "user-2",
        email: "inactive@example.com",
        full_name: null,
        role: "researcher",
        is_active: false,
      },
    ]);

    render(<AdminUsersClient />);

    await waitFor(() => {
      expect(screen.getByText("researcher@example.com")).toBeInTheDocument();
    });
    expect(screen.getByText("Inactive")).toBeInTheDocument();
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
