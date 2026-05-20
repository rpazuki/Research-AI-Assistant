"use client";

import Link from "next/link";
import type { FormEvent } from "react";
import { useEffect, useState } from "react";

import { acceptInvitation, getInvitation } from "@/lib/api";
import type { InvitationPreview, User } from "@/types";

export default function InviteAcceptClient({ token }: { token: string }) {
  const [invitation, setInvitation] = useState<InvitationPreview | null>(null);
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdUser, setCreatedUser] = useState<User | null>(null);

  useEffect(() => {
    async function loadInvitation() {
      try {
        setLoading(true);
        const data = await getInvitation(token);
        setInvitation(data);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Invitation could not be loaded");
      } finally {
        setLoading(false);
      }
    }

    void loadInvitation();
  }, [token]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);

    if (password !== passwordConfirm) {
      setError("Passwords do not match.");
      return;
    }

    try {
      setSaving(true);
      const user = await acceptInvitation(token, fullName, password, passwordConfirm);
      setCreatedUser(user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Account setup failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-8">
      <section className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-8 shadow-sm">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-bold text-gray-900">Set Up Your Account</h1>
          <p className="mt-2 text-sm text-gray-500">
            Your email address is your username for RLALab AI Assistant.
          </p>
        </div>

        {loading ? (
          <p className="text-sm text-gray-500">Loading invitation...</p>
        ) : createdUser ? (
          <div className="space-y-4">
            <div className="rounded-lg bg-green-50 px-3 py-2 text-sm text-green-700">
              Account created for {createdUser.email}.
            </div>
            <Link
              href="/login"
              className="block w-full rounded-lg bg-blue-600 py-2 text-center text-sm font-semibold text-white hover:bg-blue-700"
            >
              Continue to sign in
            </Link>
          </div>
        ) : invitation ? (
          <form onSubmit={(event) => void handleSubmit(event)} className="space-y-4">
            <div>
              <label htmlFor="invite-email" className="block text-sm font-medium text-gray-700">
                Email username
              </label>
              <input
                id="invite-email"
                type="email"
                value={invitation.email}
                disabled
                className="mt-1 w-full rounded-lg border border-gray-300 bg-gray-100 px-4 py-2 text-sm text-gray-700"
              />
            </div>

            <div>
              <label htmlFor="full-name" className="block text-sm font-medium text-gray-700">
                Display name
              </label>
              <input
                id="full-name"
                type="text"
                required
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
                className="mt-1 w-full rounded-lg border border-gray-300 px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700">
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="mt-1 w-full rounded-lg border border-gray-300 px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div>
              <label htmlFor="password-confirm" className="block text-sm font-medium text-gray-700">
                Confirm password
              </label>
              <input
                id="password-confirm"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={passwordConfirm}
                onChange={(event) => setPasswordConfirm(event.target.value)}
                className="mt-1 w-full rounded-lg border border-gray-300 px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            {error && (
              <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
            )}

            <button
              type="submit"
              disabled={saving}
              className="w-full rounded-lg bg-blue-600 py-2 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? "Creating account..." : "Create account"}
            </button>
          </form>
        ) : (
          <div className="space-y-4">
            <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
              {error ?? "Invitation could not be loaded."}
            </p>
            <Link
              href="/login"
              className="block w-full rounded-lg border border-gray-300 py-2 text-center text-sm font-semibold text-gray-700 hover:bg-gray-50"
            >
              Back to sign in
            </Link>
          </div>
        )}
      </section>
    </main>
  );
}
