"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { getAdminUser, updateAdminUserStatus } from "@/lib/api";
import type { User } from "@/types";

export default function AdminUserClient({ userId }: { userId: string }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadUser();
  }, [userId]);

  async function loadUser() {
    try {
      setLoading(true);
      const data = await getAdminUser(userId);
      setUser(data);
      setError(null);
    } catch (err) {
      if (err instanceof Error && err.message === "Unauthorized") {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load user");
    } finally {
      setLoading(false);
    }
  }

  async function handleStatusChange(isActive: boolean) {
    if (!user || saving) {
      return;
    }

    const previousUser = user;
    setUser({ ...user, is_active: isActive });
    setSaving(true);
    setError(null);

    try {
      const updated = await updateAdminUserStatus(user.id, isActive);
      setUser(updated);
    } catch (err) {
      setUser(previousUser);
      setError(err instanceof Error ? err.message : "Failed to update user status");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold text-gray-900">User Profile</h1>
            <p className="text-sm text-gray-500">Access status</p>
          </div>
          <Link
            href="/admin"
            className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100"
          >
            Back to users
          </Link>
        </div>
      </header>

      <section className="mx-auto max-w-4xl px-6 py-6">
        <div className="rounded-lg border border-gray-200 bg-white">
          {error && (
            <div className="border-b border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          {loading ? (
            <div className="px-4 py-8 text-sm text-gray-500">Loading user...</div>
          ) : user ? (
            <div className="divide-y divide-gray-100">
              <div className="px-4 py-5">
                <p className="text-xs font-semibold uppercase text-gray-500">Name</p>
                <p className="mt-1 text-base font-medium text-gray-900">
                  {user.full_name ?? "Unnamed user"}
                </p>
              </div>
              <div className="grid gap-4 px-4 py-5 sm:grid-cols-2">
                <div>
                  <p className="text-xs font-semibold uppercase text-gray-500">Email</p>
                  <p className="mt-1 text-sm text-gray-800">{user.email}</p>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase text-gray-500">Role</p>
                  <p className="mt-1 text-sm text-gray-800">{user.role}</p>
                </div>
              </div>
              <div className="px-4 py-5">
                <label className="flex items-center gap-3 text-sm font-medium text-gray-800">
                  <input
                    type="checkbox"
                    checked={user.is_active}
                    disabled={saving}
                    onChange={(event) => void handleStatusChange(event.target.checked)}
                    className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  Active account
                </label>
                <p className="mt-2 text-sm text-gray-500">
                  Inactive users cannot sign in or call protected endpoints.
                </p>
                {saving && <p className="mt-2 text-sm text-gray-500">Saving...</p>}
              </div>
            </div>
          ) : (
            <div className="px-4 py-8 text-sm text-gray-500">User not found.</div>
          )}
        </div>
      </section>
    </main>
  );
}
