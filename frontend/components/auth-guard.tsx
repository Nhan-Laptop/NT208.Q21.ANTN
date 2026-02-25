"use client";

import { useAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";
import { ReactNode, useEffect } from "react";
import { Loader2 } from "lucide-react";

export function AuthGuard({
  children,
  requireAdmin = false,
}: {
  children: ReactNode;
  requireAdmin?: boolean;
}) {
  const { token, user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!token) {
      router.replace("/login");
      return;
    }
    if (requireAdmin && user?.role !== "admin") {
      router.replace("/chat");
    }
  }, [token, user, requireAdmin, router, loading]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-bg-primary dark:bg-dark-bg-primary">
        <Loader2 className="w-6 h-6 animate-spin text-accent dark:text-dark-accent" />
      </div>
    );
  }

  if (!token) return null;

  if (requireAdmin && user?.role !== "admin") return null;

  return <>{children}</>;
}
