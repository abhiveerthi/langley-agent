"use client";

import { ChatWindow } from "@/components/chat/ChatWindow";

export default function ChatPage() {
  return (
    <div className="h-full w-full">
      <ChatWindow agentSlug="general" />
    </div>
  );
}
