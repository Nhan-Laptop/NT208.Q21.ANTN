"use client";

import { ChatView } from "@/components/chat-view";
import { useChat } from "@/lib/chat-store";
import { useParams } from "next/navigation";
import { useEffect } from "react";

export default function ChatSessionPage() {
  const params = useParams<{ sessionId: string }>();
  const { selectSession } = useChat();

  useEffect(() => {
    if (params.sessionId) {
      selectSession(params.sessionId);
    }
  }, [params.sessionId, selectSession]);

  return <ChatView />;
}
