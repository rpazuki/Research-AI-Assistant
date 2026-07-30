"use client";

import type { FormEvent } from "react";
import { useState } from "react";
import { useRouter } from "next/navigation";

import { sendInvitations } from "@/lib/api";
import type { InvitationSendResponse } from "@/types";
import AdminHeader from "./AdminHeader";

const DEFAULT_INVITATION_TEMPLATE = `Hello,

You have been invited to use {app_name}.

Please complete your account setup here:
{invite_link}

Your email address, {email}, will be your username.

This invitation link can only be used once.`;

export default function AdminInvitationsClient() {
  const router = useRouter();
  const [recipientText, setRecipientText] = useState("");
  const [subject, setSubject] = useState("Invitation to RLALab AI Assistant");
  const [template, setTemplate] = useState(DEFAULT_INVITATION_TEMPLATE);
  const [sending, setSending] = useState(false);
  const [inviteResult, setInviteResult] = useState<InvitationSendResponse | null>(null);
  const [inviteError, setInviteError] = useState<string | null>(null);

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
      <AdminHeader subtitle="Invite researchers" maxWidthClass="max-w-4xl" />

      <section className="mx-auto max-w-4xl px-6 py-6">
        <form
          onSubmit={(event) => void handleSendInvitations(event)}
          className="rounded-lg border border-gray-200 bg-white"
        >
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
      </section>
    </main>
  );
}
