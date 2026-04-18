import { ChatWindow } from "@/components/chat/ChatWindow";

export default async function ThreadPage({
  params,
}: {
  params: Promise<{ threadId: string }>;
}) {
  const { threadId } = await params;
  return <ChatWindow threadId={threadId} />;
}
