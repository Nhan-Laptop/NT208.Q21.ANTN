"use client";

import { AuthGuard } from "@/components/auth-guard";
import { Sidebar } from "@/components/chat-shell";
import { ChatProvider } from "@/lib/chat-store";
import { ReactNode } from "react";

export default function ChatLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard>
      <ChatProvider>
        <div className="flex h-screen overflow-hidden bg-bg-primary dark:bg-dark-bg-primary">
          <Sidebar />
          <main className="flex-1 flex flex-col overflow-hidden">
            {children}
          </main>
        </div>
      </ChatProvider>
    </AuthGuard>
  );
}

