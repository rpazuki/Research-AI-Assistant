import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import LoginPage from "./page";

const push = vi.fn();
const refresh = vi.fn();
const login = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

vi.mock("@/lib/api", () => ({
  login: (...args: unknown[]) => login(...args),
}));

describe("LoginPage", () => {
  beforeEach(() => {
    push.mockReset();
    refresh.mockReset();
    login.mockReset();
  });

  it("submits credentials and redirects on success", async () => {
    login.mockResolvedValue(undefined);

    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(login).toHaveBeenCalledWith("user@example.com", "secret"));
    expect(push).toHaveBeenCalledWith("/chat");
    expect(refresh).toHaveBeenCalled();
  });

  it("shows backend error messages", async () => {
    login.mockRejectedValue(new Error("Invalid credentials"));

    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(screen.getByText("Invalid credentials")).toBeInTheDocument());
  });

  it("redirects inactive users to the deactivated account page", async () => {
    login.mockRejectedValue(new Error("Account is inactive. Contact your lab admin."));

    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/account-deactivated"));
    expect(screen.queryByText("Account is inactive. Contact your lab admin.")).not.toBeInTheDocument();
  });
});
