"use client";

import Link from "next/link";
import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { listAdminUsers, logout, sendInvitations } from "@/lib/api";
import type { InvitationSendResponse, User } from "@/types";

const DEFAULT_INVITATION_TEMPLATE = `Hello,

You have been invited to use {app_name}.

Please complete your account setup here:
{invite_link}

Your email address, {email}, will be your username.

This invitation link can only be used once.`;

export default function AdminUsersClient() {
  const router = useRouter();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [recipientText, setRecipientText] = useState("");
  const [subject, setSubject] = useState("Invitation to RLALab AI Assistant");
  const [template, setTemplate] = useState(DEFAULT_INVITATION_TEMPLATE);
  const [sending, setSending] = useState(false);
  const [inviteResult, setInviteResult] = useState<InvitationSendResponse | null>(null);
  const [inviteError, setInviteError] = useState<string | null>(null);

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

  async function handleSendInvitations(event: FormEvent) {
    event.preventDefault();
    setInviteError(null);
    setInviteResult(null);

    const recipientEmails = recipientText
      .split(/[\s,;]+/)
      .map((email) => email.trim())
      .filter(Boolean);

    if (recipientEmails.length === 0) {
      setInviteError("Enter at least one recipient email.");
      return;
    }
    if (!template.includes("{invite_link}")) {
      setInviteError("Template must include {invite_link}.");
      return;
    }

    try {
      setSending(true);
      const result = await sendInvitations(recipientEmails, subject, template);
      setInviteResult(result);
      if (result.sent.length > 0) {
        setRecipientText("");
      }
    } catch (err) {
      if (err instanceof Error && err.message === "Unauthorized") {
        router.push("/login");
        return;
      }
      setInviteError(err instanceof Error ? err.message : "Failed to send invitations");
    } finally {
      setSending(false);
    }
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
        <form
          onSubmit={(event) => void handleSendInvitations(event)}
          className="mb-6 rounded-lg border border-gray-200 bg-white"
        >
          <div className="border-b border-gray-200 px-4 py-3">
            <h2 className="text-sm font-semibold text-gray-800">Invite Researchers</h2>
          </div>
          <div className="grid gap-4 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
            <div className="space-y-4">
              <div>
                <label htmlFor="invite-recipients" className="block text-sm font-medium text-gray-700">
                  Recipient emails
                </label>
                <textarea
                  id="invite-recipients"
                  required
                  rows={5}
                  value={recipientText}
                  onChange={(event) => setRecipientText(event.target.value)}
                  placeholder="researcher1@imperial.ac.uk&#10;researcher2@imperial.ac.uk"
                  className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label htmlFor="invite-subject" className="block text-sm font-medium text-gray-700">
                  Subject
                </label>
                <input
                  id="invite-subject"
                  type="text"
                  required
                  value={subject}
                  onChange={(event) => setSubject(event.target.value)}
                  className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>

            <div>
              <label htmlFor="invite-template" className="block text-sm font-medium text-gray-700">
                Email template
              </label>
              <textarea
                id="invite-template"
                required
                rows={9}
                value={template}
                onChange={(event) => setTemplate(event.target.value)}
                className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <p className="mt-2 text-xs text-gray-500">
                Available placeholders: {"{invite_link}"}, {"{email}"}, {"{app_name}"}.
              </p>
            </div>
          </div>

          {(inviteError || inviteResult) && (
            <div className="border-t border-gray-200 px-4 py-3 text-sm">
              {inviteError && <p className="text-red-700">{inviteError}</p>}
              {inviteResult && (
                <div className="space-y-1">
                  {inviteResult.sent.map((item) => (
                    <p key={`sent-${item.email}`} className="text-green-700">
                      Sent invitation to {item.email}
                    </p>
                  ))}
                  {inviteResult.failed.map((item) => (
                    <p key={`failed-${item.email}`} className="text-red-700">
                      Could not invite {item.email}: {item.detail ?? "Unknown error"}
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="flex justify-end border-t border-gray-200 px-4 py-3">
            <button
              type="submit"
              disabled={sending}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {sending ? "Sending..." : "Send invitations"}
            </button>
          </div>
        </form>

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
                    <th className="px-4 py-3 text-right">Profile</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {users.map((user) => (
                    <tr key={user.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 font-medium text-gray-900">
                        {user.full_name ?? "Unnamed user"}
                      </td>
                      <td className="px-4 py-3 text-gray-600">{user.email}</td>
                      <td className="px-4 py-3 text-gray-600">{user.role}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${
                            user.is_active
                              ? "bg-green-50 text-green-700"
                              : "bg-gray-100 text-gray-600"
                          }`}
                        >
                          {user.is_active ? "Active" : "Inactive"}
                        </span>
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
                  ))}
                  {users.length === 0 && (
                    <tr>
                      <td className="px-4 py-8 text-sm text-gray-500" colSpan={5}>
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
