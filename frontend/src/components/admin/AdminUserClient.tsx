"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  getAdminUser,
  updateAdminUserRole,
  updateAdminUserStatus,
  updateAdminUserTokenLimit,
} from "@/lib/api";
import type { AdminUserSummary, User } from "@/types";
import { formatCount, formatLastActive, formatLatency } from "./usage";

const TOKEN_LIMIT_INCREMENT_OPTIONS = Array.from({ length: 100 }, (_, index) => index + 1).map((millions) => ({
  label: `${millions} million`,
  value: millions * 1_000_000,
}));

export default function AdminUserClient({ userId }: { userId: string }) {
  const router = useRouter();
  const [user, setUser] = useState<AdminUserSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingRole, setSavingRole] = useState(false);
  const [savingTokenLimit, setSavingTokenLimit] = useState(false);
  const [isEditingTokenLimit, setIsEditingTokenLimit] = useState(false);
  const [tokenLimitInput, setTokenLimitInput] = useState("");
  const [tokenLimitIncrement, setTokenLimitIncrement] = useState(1_000_000);
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

  async function handleRoleChange(role: User["role"]) {
    if (!user || savingRole || role === user.role) {
      return;
    }

    const previousUser = user;
    setUser({ ...user, role });
    setSavingRole(true);
    setError(null);

    try {
      const updated = await updateAdminUserRole(user.id, role);
      setUser(updated);
    } catch (err) {
      setUser(previousUser);
      setError(err instanceof Error ? err.message : "Failed to update user role");
    } finally {
      setSavingRole(false);
    }
  }

  function startTokenLimitEdit() {
    if (!user) {
      return;
    }

    setTokenLimitInput(String(user.token_limit));
    setTokenLimitIncrement(1_000_000);
    setIsEditingTokenLimit(true);
    setError(null);
  }

  function cancelTokenLimitEdit() {
    setIsEditingTokenLimit(false);
    setTokenLimitInput("");
    setTokenLimitIncrement(1_000_000);
  }

  async function saveTokenLimit(tokenLimit: number) {
    if (!user || savingTokenLimit) {
      return;
    }

    if (!Number.isInteger(tokenLimit) || tokenLimit < 0) {
      setError("Token limit must be a whole number greater than or equal to 0.");
      return;
    }

    const previousUser = user;
    setUser({ ...user, token_limit: tokenLimit });
    setSavingTokenLimit(true);
    setError(null);

    try {
      const updated = await updateAdminUserTokenLimit(user.id, tokenLimit);
      setUser(updated);
      cancelTokenLimitEdit();
    } catch (err) {
      setUser(previousUser);
      setError(err instanceof Error ? err.message : "Failed to update token limit");
    } finally {
      setSavingTokenLimit(false);
    }
  }

  function handleManualTokenLimitSave() {
    const parsedLimit = Number(tokenLimitInput);
    void saveTokenLimit(parsedLimit);
  }

  function handleTokenLimitAdd() {
    if (!user) {
      return;
    }

    void saveTokenLimit(user.token_limit + tokenLimitIncrement);
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
                  <select
                    value={user.role}
                    disabled={savingRole}
                    onChange={(event) => void handleRoleChange(event.target.value as User["role"])}
                    className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 sm:max-w-xs"
                    aria-label="User role"
                  >
                    <option value="researcher">Researcher</option>
                    <option value="admin">Admin</option>
                  </select>
                  {savingRole && <p className="mt-2 text-sm text-gray-500">Saving role...</p>}
                </div>
              </div>
              <div className="grid gap-4 px-4 py-5 sm:grid-cols-2 lg:grid-cols-4">
                <div>
                  <p className="text-xs font-semibold uppercase text-gray-500">Sessions</p>
                  <p className="mt-1 text-sm tabular-nums text-gray-800">
                    {formatCount(user.usage.session_count)}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase text-gray-500">Questions</p>
                  <p className="mt-1 text-sm tabular-nums text-gray-800">
                    {formatCount(user.usage.user_message_count)}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase text-gray-500">Total Tokens</p>
                  <p className="mt-1 text-sm tabular-nums text-gray-800">
                    {formatCount(user.usage.total_token_count)}
                  </p>
                  {user.token_limit_reached && (
                    <p className="mt-1 text-xs font-medium text-red-600">Limit reached</p>
                  )}
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase text-gray-500">Last Active</p>
                  <p className="mt-1 text-sm text-gray-800">
                    {formatLastActive(user.usage.last_active_at)}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase text-gray-500">Avg Latency</p>
                  <p className="mt-1 text-sm tabular-nums text-gray-800">
                    {formatLatency(user.usage.avg_latency_ms)}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase text-gray-500">Prompt Tokens</p>
                  <p className="mt-1 text-sm tabular-nums text-gray-800">
                    {formatCount(user.usage.prompt_token_count)}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase text-gray-500">
                    Completion Tokens
                  </p>
                  <p className="mt-1 text-sm tabular-nums text-gray-800">
                    {formatCount(user.usage.completion_token_count)}
                  </p>
                </div>
              </div>
              <div className="px-4 py-5">
                <p className="text-xs font-semibold uppercase text-gray-500">Token Limit</p>
                {isEditingTokenLimit ? (
                  <div className="mt-2 space-y-3">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                      <input
                        type="number"
                        inputMode="numeric"
                        min={0}
                        step={1}
                        value={tokenLimitInput}
                        disabled={savingTokenLimit}
                        onChange={(event) => setTokenLimitInput(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.preventDefault();
                            handleManualTokenLimitSave();
                          }
                          if (event.key === "Escape") {
                            event.preventDefault();
                            cancelTokenLimitEdit();
                          }
                        }}
                        className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm tabular-nums text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 sm:max-w-xs"
                        aria-label="Editable token limit"
                      />
                      <button
                        type="button"
                        disabled={savingTokenLimit}
                        onClick={handleManualTokenLimitSave}
                        className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                      >
                        Save
                      </button>
                      <button
                        type="button"
                        disabled={savingTokenLimit}
                        onClick={cancelTokenLimitEdit}
                        className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50"
                      >
                        Cancel
                      </button>
                    </div>
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                      <select
                        value={tokenLimitIncrement}
                        disabled={savingTokenLimit}
                        onChange={(event) => setTokenLimitIncrement(Number(event.target.value))}
                        className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 sm:max-w-xs"
                        aria-label="Token limit amount to add"
                      >
                        {TOKEN_LIMIT_INCREMENT_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        disabled={savingTokenLimit}
                        onClick={handleTokenLimitAdd}
                        className="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium text-gray-800 hover:bg-gray-100 disabled:opacity-50"
                      >
                        Add
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={startTokenLimitEdit}
                    className="mt-1 rounded-md px-0 py-1 text-left text-sm tabular-nums text-gray-800 underline-offset-4 hover:underline"
                  >
                    {formatCount(user.token_limit)} tokens
                  </button>
                )}
                <p className="mt-2 text-sm text-gray-500">
                  {formatCount(user.usage.total_token_count)} of{" "}
                  {formatCount(user.token_limit)} tokens used
                </p>
                {savingTokenLimit && <p className="mt-2 text-sm text-gray-500">Saving...</p>}
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
