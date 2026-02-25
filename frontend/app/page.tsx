"use client";

import { useAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import Link from "next/link";
import { BookOpen, FileCheck, Search, Shield, Sparkles } from "lucide-react";

export default function HomePage() {
  const { token, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && token) {
      router.replace("/chat");
    }
  }, [token, loading, router]);

  return (
    <main className="min-h-screen flex items-center justify-center bg-bg-primary dark:bg-dark-bg-primary p-6">
      <div className="w-full max-w-3xl text-center space-y-8">
        {/* Logo */}
        <div className="flex items-center justify-center">
          <div className="w-16 h-16 rounded-2xl bg-accent/10 dark:bg-dark-accent/10 flex items-center justify-center">
            <Sparkles className="w-8 h-8 text-accent dark:text-dark-accent" />
          </div>
        </div>

        {/* Title */}
        <div className="space-y-3">
          <h1 className="text-4xl sm:text-5xl font-bold tracking-tight text-text-primary dark:text-dark-text-primary">
            AIRA
          </h1>
          <p className="text-lg text-text-secondary dark:text-dark-text-secondary max-w-lg mx-auto">
            Academic Integrity & Research Assistant.
            Your AI-powered workspace for writing, checking, and submitting research papers.
          </p>
        </div>

        {/* Features */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 max-w-xl mx-auto">
          {[
            { icon: BookOpen, label: "Chat AI" },
            { icon: FileCheck, label: "Citation Check" },
            { icon: Search, label: "Journal Match" },
            { icon: Shield, label: "AI Detection" },
          ].map(({ icon: Icon, label }) => (
            <div
              key={label}
              className="flex flex-col items-center gap-2 p-3 rounded-xl border border-border dark:border-dark-border bg-surface dark:bg-dark-surface"
            >
              <Icon size={20} className="text-accent dark:text-dark-accent" />
              <span className="text-xs text-text-secondary dark:text-dark-text-secondary font-medium">
                {label}
              </span>
            </div>
          ))}
        </div>

        {/* CTA */}
        <div className="flex items-center justify-center gap-3">
          <Link
            href="/login"
            className="px-6 py-2.5 rounded-xl bg-accent text-white text-sm font-medium hover:bg-accent-hover dark:bg-dark-accent dark:hover:bg-dark-accent-hover transition-colors"
          >
            Get Started
          </Link>
          <Link
            href="/login?tab=register"
            className="px-6 py-2.5 rounded-xl border border-border text-sm font-medium text-text-primary hover:bg-bg-secondary dark:border-dark-border dark:text-dark-text-primary dark:hover:bg-dark-surface-hover transition-colors"
          >
            Create Account
          </Link>
        </div>
      </div>
    </main>
  );
}
