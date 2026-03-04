"use client";

import { AuthGuard } from "@/components/auth-guard";
import { ReactNode } from "react";

export default function AdminLayout({ children }: { children: ReactNode }) {
  return <AuthGuard requireAdmin>{children}</AuthGuard>;
}
