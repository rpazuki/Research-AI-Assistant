"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { listAdminUsers, logout } from "@/lib/api";
import type { AdminUserSummary } from "@/types";
import { formatCount, formatLastActive, formatLatency } from "./usage";

function getUserStatus(user: AdminUserSummary) {
  if (!user.is_active) {
    return { label: "Inactive", className: "bg-gray-100 text-gray-600" };
  }

  if (user.token_limit_reached) {
    return { label: "Token limit", className: "bg-red-50 text-red-700" };
  }

  const tokenUsageRatio =
    user.token_limit > 0 ? user.usage.total_token_count / user.token_limit : 1;
  if (tokenUsageRatio >= 0.9) {
    return { label: "Active", className: "bg-yellow-50 text-yellow-700" };
  }

  return { label: "Active", className: "bg-green-50 text-green-700" };
}

export default function AdminUsersClient() {
  const router = useRouter();
  const [users, setUsers] = useState<AdminUserSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadUsers();
  }, []);

  async function loadUsers() {
    try {
      setLoading(true);
      const data = await listAdminUsers();
      setUsers(data);
      setError(null);
    } catch (err) {
      if (err instanceof Error && err.message === "Unauthorized") {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  }

  async function handleLogout() {
    await logout();
    router.push("/login");
    router.refresh();
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold text-gray-900">Admin</h1>
            <p className="text-sm text-gray-500">User access</p>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href="/admin/invitations"
              className="rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700"
            >
              Invite users
            </Link>
            <Link
              href="/chat"
              className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100"
            >
              Chat
            </Link>
            <button
              type="button"
              onClick={handleLogout}
              className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <section className="mx-auto max-w-6xl px-6 py-6">
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
            <h2 className="text-sm font-semibold text-gray-800">Users</h2>
            <span className="text-xs text-gray-500">{users.length} total</span>
          </div>

          {error && (
            <div className="border-b border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          {loading ? (
            <div className="px-4 py-8 text-sm text-gray-500">Loading users...</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50 text-left text-xs font-semibold uppercase text-gray-500">
                  <tr>
                    <th className="px-4 py-3">Name</th>
                    <th className="px-4 py-3">Email</th>
                    <th className="px-4 py-3">Role</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3 text-right">Sessions</th>
                    <th className="px-4 py-3 text-right">Questions</th>
                    <th className="px-4 py-3 text-right">Tokens</th>
                    <th className="px-4 py-3">Last Active</th>
                    <th className="px-4 py-3 text-right">Avg Latency</th>
                    <th className="px-4 py-3 text-right">Profile</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {users.map((user) => {
                    const status = getUserStatus(user);
                    return (
                      <tr key={user.id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 font-medium text-gray-900">
                          {user.full_name ?? "Unnamed user"}
                        </td>
                        <td className="px-4 py-3 text-gray-600">{user.email}</td>
                        <td className="px-4 py-3 text-gray-600">{user.role}</td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${status.className}`}
                          >
                            {status.label}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-gray-600">
                          {user.usage.session_count}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-gray-600">
                          {user.usage.user_message_count}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-gray-600">
                          {formatCount(user.usage.total_token_count)}
                        </td>
                        <td className="px-4 py-3 text-gray-600">
                          {formatLastActive(user.usage.last_active_at)}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-gray-600">
                          {formatLatency(user.usage.avg_latency_ms)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <Link
                            href={`/admin/users/${user.id}`}
                            className="text-sm font-medium text-blue-600 hover:underline"
                          >
                            View user
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                  {users.length === 0 && (
                    <tr>
                      <td className="px-4 py-8 text-sm text-gray-500" colSpan={10}>
                        No users found.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
