import ChatClient from "@/components/chat/ChatClient";

export default async function AdminUserExperienceSessionPage({
  params,
}: {
  params: Promise<{ userId: string; sessionId: string }>;
}) {
  const { userId, sessionId } = await params;
  return (
    <ChatClient
      adminUserId={userId}
      initialSessionId={sessionId}
      readOnly
      readOnlyLabel="Read-only admin view"
      backHref="/admin"
    />
  );
}
