import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import AdminInvitationsClient from "./AdminInvitationsClient";

const push = vi.fn();
const refresh = vi.fn();
const logout = vi.fn();
const sendInvitations = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
  usePathname: () => "/admin/invitations",
}));

vi.mock("@/lib/api", () => ({
  logout: (...args: unknown[]) => logout(...args),
  sendInvitations: (...args: unknown[]) => sendInvitations(...args),
}));

describe("AdminInvitationsClient", () => {
  beforeEach(() => {
    push.mockReset();
    refresh.mockReset();
    logout.mockReset();
    sendInvitations.mockReset();
  });

  it("sends invitations from the admin invitation page", async () => {
    sendInvitations.mockResolvedValue({
      sent: [
        {
          email: "new@lab.ac.uk",
          status: "sent",
          expires_at: "2026-05-27T00:00:00Z",
          detail: null,
        },
      ],
      failed: [],
    });

    render(<AdminInvitationsClient />);

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
    expect(screen.getByRole("link", { name: "Users" })).toHaveAttribute("href", "/admin");
  });

  it("redirects to login when invitation send is unauthorized", async () => {
    sendInvitations.mockRejectedValue(new Error("Unauthorized"));

    render(<AdminInvitationsClient />);

    fireEvent.change(screen.getByLabelText("Recipient emails"), {
      target: { value: "new@lab.ac.uk" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send invitations" }));

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith("/login");
    });
  });
});
