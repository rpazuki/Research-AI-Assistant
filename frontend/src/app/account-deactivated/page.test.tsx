import React from "react";
import { render, screen } from "@testing-library/react";

import AccountDeactivatedPage from "./page";

describe("AccountDeactivatedPage", () => {
  it("explains the account status and points users back to sign in", () => {
    render(<AccountDeactivatedPage />);

    expect(
      screen.getByRole("heading", { name: /your account is currently deactivated/i })
    ).toBeInTheDocument();
    expect(screen.getByText(/contact your lab admin/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to sign in/i })).toHaveAttribute(
      "href",
      "/login"
    );
  });
});
