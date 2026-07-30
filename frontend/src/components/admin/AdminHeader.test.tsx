import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminHeader, { ADMIN_NAV_ITEMS, activeAdminNavHref } from "./AdminHeader";

const push = vi.fn();
const refresh = vi.fn();
const logout = vi.fn();
let pathname = "/admin";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
  usePathname: () => pathname,
}));

vi.mock("@/lib/api", () => ({
  logout: (...args: unknown[]) => logout(...args),
}));

describe("activeAdminNavHref", () => {
  it("prefers the most specific entry so sub-pages do not highlight their parent", () => {
    expect(activeAdminNavHref("/admin/ingestion/config")).toBe("/admin/ingestion/config");
    expect(activeAdminNavHref("/admin/ingestion/acquisition")).toBe(
      "/admin/ingestion/acquisition"
    );
    expect(activeAdminNavHref("/admin/ingestion")).toBe("/admin/ingestion");
  });

  it("falls back to the admin root for pages without an entry of their own", () => {
    expect(activeAdminNavHref("/admin/users/user-1")).toBe("/admin");
    expect(activeAdminNavHref("/admin")).toBe("/admin");
  });

  it("returns null outside the admin area", () => {
    expect(activeAdminNavHref("/chat")).toBeNull();
    expect(activeAdminNavHref(null)).toBeNull();
  });
});

describe("AdminHeader", () => {
  beforeEach(() => {
    push.mockReset();
    refresh.mockReset();
    logout.mockReset();
    logout.mockResolvedValue(undefined);
    pathname = "/admin";
  });

  it("renders every admin section, so the menu cannot differ between pages", () => {
    render(<AdminHeader subtitle="User access" />);

    const nav = screen.getByRole("navigation", { name: "Admin sections" });
    const links = Array.from(nav.querySelectorAll("a"));

    expect(links.map((link) => link.textContent)).toEqual(
      ADMIN_NAV_ITEMS.map((item) => item.label)
    );
    expect(links.map((link) => link.getAttribute("href"))).toEqual(
      ADMIN_NAV_ITEMS.map((item) => item.href)
    );
  });

  it("marks exactly one section as the current page", () => {
    pathname = "/admin/ingestion/config";
    render(<AdminHeader subtitle="Ingestion config" />);

    const current = screen.getAllByRole("link", { current: "page" });
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveAttribute("href", "/admin/ingestion/config");
  });

  it("shows the shared title with the page subtitle", () => {
    render(<AdminHeader subtitle="Datasheet templates" />);

    expect(screen.getByRole("heading", { name: "Admin" })).toBeInTheDocument();
    expect(screen.getByText("Datasheet templates")).toBeInTheDocument();
  });

  it("signs out and returns to the login page", async () => {
    render(<AdminHeader subtitle="Statistics" />);

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(logout).toHaveBeenCalled());
    expect(push).toHaveBeenCalledWith("/login");
    expect(refresh).toHaveBeenCalled();
  });
});
