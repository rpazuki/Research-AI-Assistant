import ChatClient from "@/components/chat/ChatClient";

export default async function SessionChatPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  return <ChatClient initialSessionId={sessionId} />;
}