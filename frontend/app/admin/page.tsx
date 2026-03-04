"use client";

import { api, showApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import { AdminOverview, User, UserRole } from "@/lib/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import {
  ArrowLeft,
  FileText,
  HardDrive,
  MessageSquare,
  Moon,
  RefreshCw,
  Shield,
  ShieldCheck,
  Sun,
  Trash2,
  UserCheck,
  Users,
} from "lucide-react";
import Link from "next/link";
import clsx from "clsx";

/* ------------------------------------------------------------------ */
/*  Stat Card                                                          */
/* ------------------------------------------------------------------ */

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  color,
}: {
  label: string;
  value: string | number;
  sub?: string;
  icon: React.ElementType;
  color: string;
}) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-5 dark:border-dark-border dark:bg-dark-surface transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-text-tertiary dark:text-dark-text-tertiary">
            {label}
          </p>
          <p className="mt-2 text-3xl font-bold text-text-primary dark:text-dark-text-primary">
            {value}
          </p>
          {sub && (
            <p className="mt-1 text-xs text-text-secondary dark:text-dark-text-secondary">
              {sub}
            </p>
          )}
        </div>
        <div className={clsx("p-2.5 rounded-xl", color)}>
          <Icon size={20} className="text-white" />
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Role Badge                                                         */
/* ------------------------------------------------------------------ */

function RoleBadge({ role }: { role: UserRole }) {
  const isAdmin = role === "admin";
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold",
        isAdmin
          ? "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400"
          : "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400",
      )}
    >
      {isAdmin ? <ShieldCheck size={12} /> : <UserCheck size={12} />}
      {isAdmin ? "Admin" : "Researcher"}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  User Row                                                           */
/* ------------------------------------------------------------------ */

function UserRow({
  u,
  currentUserId,
  onToggleRole,
  isPending,
}: {
  u: User;
  currentUserId: string;
  onToggleRole: (userId: string, newRole: UserRole) => void;
  isPending: boolean;
}) {
  const isSelf = u.id === currentUserId;
  const newRole: UserRole = u.role === "admin" ? "researcher" : "admin";

  return (
    <tr className="border-b border-border/40 dark:border-dark-border/40 hover:bg-bg-secondary/50 dark:hover:bg-dark-surface-hover/50 transition-colors">
      <td className="py-3 px-4">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-accent/10 dark:bg-dark-accent/10 flex items-center justify-center text-xs font-bold text-accent dark:text-dark-accent shrink-0">
            {u.email.charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium text-text-primary dark:text-dark-text-primary truncate">
              {u.full_name || u.email.split("@")[0]}
            </p>
            <p className="text-xs text-text-tertiary dark:text-dark-text-tertiary truncate">
              {u.email}
            </p>
          </div>
        </div>
      </td>
      <td className="py-3 px-4">
        <RoleBadge role={u.role} />
      </td>
      <td className="py-3 px-4 text-xs text-text-secondary dark:text-dark-text-secondary whitespace-nowrap">
        {new Date(u.created_at).toLocaleDateString("vi-VN", {
          day: "2-digit",
          month: "2-digit",
          year: "numeric",
        })}
      </td>
      <td className="py-3 px-4">
        {isSelf ? (
          <span className="text-xs text-text-tertiary dark:text-dark-text-tertiary italic">
            You
          </span>
        ) : (
          <button
            onClick={() => onToggleRole(u.id, newRole)}
            disabled={isPending}
            className={clsx(
              "px-3 py-1.5 rounded-lg text-xs font-medium transition-all disabled:opacity-40",
              u.role === "admin"
                ? "border border-amber-300 text-amber-700 hover:bg-amber-50 dark:border-amber-700 dark:text-amber-400 dark:hover:bg-amber-900/20"
                : "border border-blue-300 text-blue-700 hover:bg-blue-50 dark:border-blue-700 dark:text-blue-400 dark:hover:bg-blue-900/20",
            )}
          >
            {u.role === "admin" ? "Demote to Researcher" : "Promote to Admin"}
          </button>
        )}
      </td>
    </tr>
  );
}

/* ------------------------------------------------------------------ */
/*  Admin Dashboard Content                                            */
/* ------------------------------------------------------------------ */

export default function AdminPage() {
  const { token, user } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"users" | "files">("users");

  /* ---- Queries ---- */

  const overviewQuery = useQuery({
    queryKey: ["admin", "overview"],
    queryFn: () => api.adminOverview(token!),
    enabled: Boolean(token),
    refetchInterval: 15_000,
  });

  const usersQuery = useQuery({
    queryKey: ["admin", "users"],
    queryFn: () => api.adminUsers(token!),
    enabled: Boolean(token),
  });

  const filesQuery = useQuery({
    queryKey: ["admin", "files"],
    queryFn: () => api.adminFiles(token!),
    enabled: Boolean(token) && tab === "files",
  });

  const storageQuery = useQuery({
    queryKey: ["admin", "storage"],
    queryFn: () => api.adminStorage(token!),
    enabled: Boolean(token),
  });

  /* ---- Mutations ---- */

  const roleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: UserRole }) =>
      api.adminUpdateRole(token!, userId, role),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["admin"] });
      toast.success(`${updated.email} is now ${updated.role}`);
    },
    onError: showApiError,
  });

  const deleteFileMutation = useMutation({
    mutationFn: (fileId: string) => api.adminDeleteFile(token!, fileId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin"] });
      toast.success("File deleted");
    },
    onError: showApiError,
  });

  /* ---- Derived data ---- */

  const ov = overviewQuery.data;
  const users = useMemo(() => usersQuery.data ?? [], [usersQuery.data]);
  const files = useMemo(() => filesQuery.data ?? [], [filesQuery.data]);

  const handleToggleRole = (userId: string, newRole: UserRole) => {
    roleMutation.mutate({ userId, role: newRole });
  };

  return (
    <div className="min-h-screen bg-bg-primary dark:bg-dark-bg-primary">
      {/* ───────── Header ───────── */}
      <header className="sticky top-0 z-20 border-b border-border dark:border-dark-border bg-surface/90 dark:bg-dark-surface/90 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              href="/chat"
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium text-text-secondary hover:text-text-primary hover:bg-bg-secondary dark:text-dark-text-secondary dark:hover:text-dark-text-primary dark:hover:bg-dark-surface-hover transition-all"
            >
              <ArrowLeft size={16} />
              <span className="hidden sm:inline">Return to Chat</span>
            </Link>
            <div className="h-5 w-px bg-border dark:bg-dark-border" />
            <div className="flex items-center gap-2">
              <Shield size={20} className="text-accent dark:text-dark-accent" />
              <h1 className="text-lg font-bold text-text-primary dark:text-dark-text-primary">
                Admin Dashboard
              </h1>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={toggleTheme}
              className="p-2 rounded-lg text-text-secondary hover:bg-bg-secondary dark:text-dark-text-secondary dark:hover:bg-dark-surface-hover transition-colors"
              title="Toggle theme"
            >
              {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <button
              onClick={() => queryClient.invalidateQueries({ queryKey: ["admin"] })}
              className="p-2 rounded-lg text-text-secondary hover:bg-bg-secondary dark:text-dark-text-secondary dark:hover:bg-dark-surface-hover transition-colors"
              title="Refresh all data"
            >
              <RefreshCw
                size={18}
                className={clsx(overviewQuery.isFetching && "animate-spin")}
              />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-6 space-y-6">
        {/* ───────── Stat Cards ───────── */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            label="Total Users"
            value={ov?.users ?? "—"}
            sub={
              ov
                ? `${ov.active_admins} admin${ov.active_admins !== 1 ? "s" : ""} · ${ov.active_researchers} researcher${ov.active_researchers !== 1 ? "s" : ""}`
                : undefined
            }
            icon={Users}
            color="bg-blue-500"
          />
          <StatCard
            label="Chat Sessions"
            value={ov?.sessions ?? "—"}
            sub={ov ? `${ov.messages} total messages` : undefined}
            icon={MessageSquare}
            color="bg-purple-500"
          />
          <StatCard
            label="Files Uploaded"
            value={ov?.files ?? "—"}
            sub={ov ? `${ov.total_storage_mb} MB used` : undefined}
            icon={FileText}
            color="bg-emerald-500"
          />
          <StatCard
            label="Storage"
            value={storageQuery.data?.health_status ?? "—"}
            sub={
              storageQuery.data
                ? `${storageQuery.data.storage_type} · ${storageQuery.data.total_objects} objects`
                : undefined
            }
            icon={HardDrive}
            color="bg-orange-500"
          />
        </div>

        {/* ───────── Tab Switcher ───────── */}
        <div className="flex items-center gap-1 border-b border-border dark:border-dark-border">
          <button
            onClick={() => setTab("users")}
            className={clsx(
              "px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px",
              tab === "users"
                ? "border-accent text-accent dark:border-dark-accent dark:text-dark-accent"
                : "border-transparent text-text-secondary hover:text-text-primary dark:text-dark-text-secondary dark:hover:text-dark-text-primary",
            )}
          >
            <span className="flex items-center gap-2">
              <Users size={15} />
              User Management
            </span>
          </button>
          <button
            onClick={() => setTab("files")}
            className={clsx(
              "px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px",
              tab === "files"
                ? "border-accent text-accent dark:border-dark-accent dark:text-dark-accent"
                : "border-transparent text-text-secondary hover:text-text-primary dark:text-dark-text-secondary dark:hover:text-dark-text-primary",
            )}
          >
            <span className="flex items-center gap-2">
              <FileText size={15} />
              File Management
            </span>
          </button>
        </div>

        {/* ───────── Users Tab ───────── */}
        {tab === "users" && (
          <div className="rounded-2xl border border-border bg-surface dark:border-dark-border dark:bg-dark-surface overflow-hidden">
            <div className="px-5 py-4 border-b border-border dark:border-dark-border flex items-center justify-between">
              <h2 className="text-sm font-semibold text-text-primary dark:text-dark-text-primary">
                All Users ({users.length})
              </h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-bg-secondary/50 dark:bg-dark-surface-hover/50">
                    {["User", "Role", "Joined", "Actions"].map((h) => (
                      <th
                        key={h}
                        className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-text-tertiary dark:text-dark-text-tertiary"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <UserRow
                      key={u.id}
                      u={u}
                      currentUserId={user?.id ?? ""}
                      onToggleRole={handleToggleRole}
                      isPending={roleMutation.isPending}
                    />
                  ))}
                  {usersQuery.isLoading && (
                    <tr>
                      <td
                        colSpan={4}
                        className="py-8 text-center text-sm text-text-tertiary dark:text-dark-text-tertiary"
                      >
                        Loading users…
                      </td>
                    </tr>
                  )}
                  {!usersQuery.isLoading && users.length === 0 && (
                    <tr>
                      <td
                        colSpan={4}
                        className="py-8 text-center text-sm text-text-tertiary dark:text-dark-text-tertiary"
                      >
                        No users found
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ───────── Files Tab ───────── */}
        {tab === "files" && (
          <div className="rounded-2xl border border-border bg-surface dark:border-dark-border dark:bg-dark-surface overflow-hidden">
            <div className="px-5 py-4 border-b border-border dark:border-dark-border flex items-center justify-between">
              <h2 className="text-sm font-semibold text-text-primary dark:text-dark-text-primary">
                All Files ({files.length})
              </h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-bg-secondary/50 dark:bg-dark-surface-hover/50">
                    {["File", "Owner", "Type", "Size", "Uploaded", ""].map((h) => (
                      <th
                        key={h}
                        className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-text-tertiary dark:text-dark-text-tertiary"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {files.map((file) => (
                    <tr
                      key={file.id}
                      className="border-b border-border/40 dark:border-dark-border/40 hover:bg-bg-secondary/50 dark:hover:bg-dark-surface-hover/50 transition-colors"
                    >
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <FileText
                            size={16}
                            className="text-text-tertiary dark:text-dark-text-tertiary shrink-0"
                          />
                          <span className="text-sm text-text-primary dark:text-dark-text-primary truncate max-w-[200px]">
                            {file.file_name}
                          </span>
                        </div>
                      </td>
                      <td className="py-3 px-4 text-xs font-mono text-text-secondary dark:text-dark-text-secondary">
                        {file.user_id.slice(0, 8)}…
                      </td>
                      <td className="py-3 px-4">
                        <span className="inline-block px-2 py-0.5 rounded text-xs bg-bg-secondary dark:bg-dark-surface-hover text-text-secondary dark:text-dark-text-secondary">
                          {file.mime_type.split("/")[1] ?? file.mime_type}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-sm text-text-secondary dark:text-dark-text-secondary whitespace-nowrap">
                        {file.size_bytes < 1024 * 1024
                          ? `${Math.round(file.size_bytes / 1024)} KB`
                          : `${(file.size_bytes / (1024 * 1024)).toFixed(1)} MB`}
                      </td>
                      <td className="py-3 px-4 text-xs text-text-secondary dark:text-dark-text-secondary whitespace-nowrap">
                        {new Date(file.created_at).toLocaleDateString("vi-VN")}
                      </td>
                      <td className="py-3 px-4">
                        <button
                          onClick={() => deleteFileMutation.mutate(file.id)}
                          disabled={deleteFileMutation.isPending}
                          className="p-1.5 rounded-lg text-text-tertiary hover:text-danger hover:bg-danger/10 dark:text-dark-text-tertiary dark:hover:text-danger transition-colors disabled:opacity-40"
                          title="Delete file"
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {filesQuery.isLoading && (
                    <tr>
                      <td
                        colSpan={6}
                        className="py-8 text-center text-sm text-text-tertiary dark:text-dark-text-tertiary"
                      >
                        Loading files…
                      </td>
                    </tr>
                  )}
                  {!filesQuery.isLoading && files.length === 0 && (
                    <tr>
                      <td
                        colSpan={6}
                        className="py-8 text-center text-sm text-text-tertiary dark:text-dark-text-tertiary"
                      >
                        No files uploaded yet
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
