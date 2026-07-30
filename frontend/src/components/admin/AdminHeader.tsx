"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { logout } from "@/lib/api";

/**
 * The single source of truth for the admin navigation.
 *
 * Every page under /admin renders this header, so the menu is identical
 * everywhere. Adding an admin page means adding one entry here — never a
 * page-local link set, which is how the menus drifted apart before.
 */
export const ADMIN_NAV_ITEMS = [
  { href: "/admin", label: "Users" },
  { href: "/admin/invitations", label: "Invitations" },
  { href: "/admin/stats", label: "Stats" },
  { href: "/admin/ingestion", label: "Ingestion" },
  { href: "/admin/ingestion/config", label: "Config" },
  { href: "/admin/ingestion/acquisition", label: "Acquisition" },
  { href: "/admin/datasheets", label: "Datasheets" },
  { href: "/admin/datasheets/templates", label: "Templates" },
  { href: "/admin/evaluation", label: "Evaluation" },
] as const;

/**
 * The most specific nav entry that covers `pathname`.
 *
 * Longest match wins, so /admin/ingestion/config highlights Config rather than
 * Ingestion, and a page with no entry of its own (e.g. /admin/users/{id})
 * falls back to the /admin root entry.
 */
export function activeAdminNavHref(pathname: string | null): string | null {
  if (!pathname) return null;

  let best: string | null = null;
  for (const item of ADMIN_NAV_ITEMS) {
    const matches = pathname === item.href || pathname.startsWith(`${item.href}/`);
    if (matches && (best === null || item.href.length > best.length)) {
      best = item.href;
    }
  }
  return best;
}

const LINK_CLASS =
  "rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100";
const ACTIVE_LINK_CLASS =
  "rounded-md border border-blue-300 bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700";

export default function AdminHeader({
  subtitle,
  maxWidthClass = "max-w-6xl",
}: {
  /** What this page is, shown under the shared "Admin" title. */
  subtitle: string;
  /** Match the page's own content width so the header aligns with it. */
  maxWidthClass?: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const activeHref = activeAdminNavHref(pathname);

  async function handleLogout() {
    await logout();
    router.push("/login");
    router.refresh();
  }

  return (
    <header className="border-b bg-white">
      <div className={`mx-auto ${maxWidthClass} px-6 py-4`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-gray-900">Admin</h1>
            <p className="text-sm text-gray-500">{subtitle}</p>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/chat" className={LINK_CLASS}>
              Chat
            </Link>
            <button type="button" onClick={() => void handleLogout()} className={LINK_CLASS}>
              Sign out
            </button>
          </div>
        </div>

        <nav aria-label="Admin sections" className="mt-3 flex flex-wrap items-center gap-2">
          {ADMIN_NAV_ITEMS.map((item) => {
            const active = item.href === activeHref;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={active ? ACTIVE_LINK_CLASS : LINK_CLASS}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
