import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import AdminUsersClient from "./AdminUsersClient";

const push = vi.fn();
const refresh = vi.fn();
const listAdminUsers = vi.fn();
const logout = vi.fn();
const sendInvitations = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

vi.mock("@/lib/api", () => ({
  listAdminUsers: (...args: unknown[]) => listAdminUsers(...args),
  logout: (...args: unknown[]) => logout(...args),
  sendInvitations: (...args: unknown[]) => sendInvitations(...args),
}));

describe("AdminUsersClient", () => {
  beforeEach(() => {
    push.mockReset();
    refresh.mockReset();
    listAdminUsers.mockReset();
    logout.mockReset();
    sendInvitations.mockReset();
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

  it("sends invitations from the admin form", async () => {
    listAdminUsers.mockResolvedValue([]);
    sendInvitations.mockResolvedValue({
      sent: [{ email: "new@lab.ac.uk", status: "sent", expires_at: "2026-05-27T00:00:00Z", detail: null }],
      failed: [],
    });

    render(<AdminUsersClient />);

    await waitFor(() => {
      expect(screen.getByText("No users found.")).toBeInTheDocument();
    });
    fireEvent.change(screen.getByLabelText("Recipient emails"), {
      target: { value: "new@lab.ac.uk" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send invitations" }));

    await waitFor(() => {
      expect(sendInvitations).toHaveBeenCalledWith(
        ["new@lab.ac.uk"],
        "Invitation to RLALab AI Assistant",
        expect.stringContaining("{invite_link}")
      );
    });
    expect(screen.getByText("Sent invitation to new@lab.ac.uk")).toBeInTheDocument();
  });
});
