import Link from "next/link";

export default function AccountDeactivatedPage() {
  return (
    <main className="min-h-screen bg-gray-50">
      <div className="mx-auto flex min-h-screen max-w-lg items-center px-6 py-12">
        <section className="w-full rounded-xl border border-gray-200 bg-white p-8 shadow-sm">
          <div className="mb-6">
            <p className="text-sm font-semibold uppercase tracking-wide text-blue-600">
              Account access
            </p>
            <h1 className="mt-2 text-2xl font-bold text-gray-900">
              Your account is currently deactivated
            </h1>
            <p className="mt-3 text-sm leading-6 text-gray-600">
              This account exists, but it is not active right now. You will not be able to
              sign in or use the RLALab AI Assistant until an admin reactivates access.
            </p>
          </div>

          <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-900">
            Please contact your lab admin and ask them to review your account status.
          </div>

          <div className="mt-6 flex flex-wrap gap-3">
            <Link
              href="/login"
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
            >
              Back to sign in
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}
