import ChatClient from "@/components/chat/ChatClient";

export default async function AdminUserExperiencePage({
  params,
}: {
  params: Promise<{ userId: string }>;
}) {
  const { userId } = await params;
  return (
    <ChatClient
      adminUserId={userId}
      readOnly
      readOnlyLabel="Read-only admin view"
      backHref="/admin"
    />
  );
}
