"use client";

import { AuthGuard } from "@/components/auth-guard";
import { api, ApiError, showApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import { FileAttachment, User, UserRole } from "@/lib/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { toast } from "sonner";
import {
  ArrowLeft,
  Database,
  FileText,
  HardDrive,
  Moon,
  RefreshCw,
  Sun,
  Trash2,
  Users,
} from "lucide-react";
import Link from "next/link";

export default function AdminPage() {
  return (
    <AuthGuard requireAdmin>
      <AdminContent />
    </AuthGuard>
  );
}

function AdminContent() {
  const { token, user } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const queryClient = useQueryClient();

  const overviewQuery = useQuery({
    queryKey: ["admin", "overview"],
    queryFn: () => api.adminOverview(token!),
    enabled: Boolean(token),
    refetchInterval: 15000,
  });

  const usersQuery = useQuery({
    queryKey: ["admin", "users"],
    queryFn: () => api.adminUsers(token!),
    enabled: Boolean(token),
  });

  const filesQuery = useQuery({
    queryKey: ["admin", "files"],
    queryFn: () => api.adminFiles(token!),
    enabled: Boolean(token),
  });

  const storageQuery = useQuery({
    queryKey: ["admin", "storage"],
    queryFn: () => api.adminStorage(token!),
    enabled: Boolean(token),
  });

  const healthQuery = useQuery({
    queryKey: ["admin", "storage-health"],
    queryFn: () => api.adminStorageHealth(token!),
    enabled: Boolean(token),
  });

  const promoteMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: UserRole }) =>
      api.promoteUser(token!, userId, role),
    onSuccess: (updatedUser) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success(`Updated ${updatedUser.email} to ${updatedUser.role}`);
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

  const users = useMemo(() => usersQuery.data ?? [], [usersQuery.data]);
  const files = useMemo(() => filesQuery.data ?? [], [filesQuery.data]);
  const ov = overviewQuery.data;

  const stats = [
    { label: "Users", value: ov?.users ?? "-", icon: Users },
    { label: "Sessions", value: ov?.sessions ?? "-", icon: Database },
    { label: "Messages", value: ov?.messages ?? "-", icon: FileText },
    { label: "Files", value: ov?.files ?? "-", icon: FileText },
    { label: "Storage", value: ov ? `${ov.total_storage_mb} MB` : "-", icon: HardDrive },
    {
      label: "Health",
      value: healthQuery.data?.status ?? "unknown",
      icon: HardDrive,
    },
  ];

  return (
    <div className="min-h-screen bg-bg-primary dark:bg-dark-bg-primary">
      {/* Header */}
      <header className="sticky top-0 z-10 border-b border-border dark:border-dark-border bg-surface/80 dark:bg-dark-surface/80 backdrop-blur-sm">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link
              href="/chat"
              className="p-1.5 rounded-lg text-text-secondary hover:bg-bg-secondary dark:text-dark-text-secondary dark:hover:bg-dark-surface-hover transition-colors"
            >
              <ArrowLeft size={18} />
            </Link>
            <h1 className="text-lg font-semibold text-text-primary dark:text-dark-text-primary">
              Admin Dashboard
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={toggleTheme}
              className="p-1.5 rounded-lg text-text-secondary hover:bg-bg-secondary dark:text-dark-text-secondary dark:hover:bg-dark-surface-hover transition-colors"
            >
              {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <button
              onClick={() => queryClient.invalidateQueries({ queryKey: ["admin"] })}
              className="p-1.5 rounded-lg text-text-secondary hover:bg-bg-secondary dark:text-dark-text-secondary dark:hover:bg-dark-surface-hover transition-colors"
              title="Refresh"
            >
              <RefreshCw size={18} />
            </button>
          </div>
        </div>
      </header>

      <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">
        {/* Stats Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {stats.map(({ label, value, icon: Icon }) => (
            <div
              key={label}
              className="rounded-xl border border-border bg-surface p-4 dark:border-dark-border dark:bg-dark-surface"
            >
              <div className="flex items-center gap-2 mb-1">
                <Icon size={14} className="text-text-tertiary dark:text-dark-text-tertiary" />
                <span className="text-xs text-text-secondary dark:text-dark-text-secondary">
                  {label}
                </span>
              </div>
              <div className="text-lg font-semibold text-text-primary dark:text-dark-text-primary">
                {value}
              </div>
            </div>
          ))}
        </div>

        {/* Users & Storage */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Users Table */}
          <div className="rounded-xl border border-border bg-surface p-4 dark:border-dark-border dark:bg-dark-surface">
            <h2 className="text-sm font-semibold text-text-primary dark:text-dark-text-primary mb-3">
              Users
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border dark:border-dark-border">
                    <th className="text-left py-2 px-2 text-text-secondary dark:text-dark-text-secondary font-medium">
                      Email
                    </th>
                    <th className="text-left py-2 px-2 text-text-secondary dark:text-dark-text-secondary font-medium">
                      Role
                    </th>
                    <th className="text-left py-2 px-2 text-text-secondary dark:text-dark-text-secondary font-medium">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr
                      key={u.id}
                      className="border-b border-border/50 dark:border-dark-border/50"
                    >
                      <td className="py-2 px-2 text-text-primary dark:text-dark-text-primary">
                        {u.email}
                      </td>
                      <td className="py-2 px-2">
                        <span className="inline-block px-2 py-0.5 rounded-full text-xs bg-accent/10 text-accent dark:bg-dark-accent/10 dark:text-dark-accent capitalize">
                          {u.role}
                        </span>
                      </td>
                      <td className="py-2 px-2">
                        <div className="flex gap-1">
                          <button
                            disabled={
                              promoteMutation.isPending || u.role === "researcher"
                            }
                            onClick={() =>
                              promoteMutation.mutate({
                                userId: u.id,
                                role: "researcher",
                              })
                            }
                            className="px-2 py-1 rounded-lg text-xs border border-border hover:bg-bg-secondary disabled:opacity-40 dark:border-dark-border dark:hover:bg-dark-surface-hover transition-colors"
                          >
                            Researcher
                          </button>
                          <button
                            disabled={
                              promoteMutation.isPending || u.role === "admin"
                            }
                            onClick={() =>
                              promoteMutation.mutate({ userId: u.id, role: "admin" })
                            }
                            className="px-2 py-1 rounded-lg text-xs border border-border hover:bg-bg-secondary disabled:opacity-40 dark:border-dark-border dark:hover:bg-dark-surface-hover transition-colors"
                          >
                            Admin
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Storage Info */}
          <div className="rounded-xl border border-border bg-surface p-4 dark:border-dark-border dark:bg-dark-surface">
            <h2 className="text-sm font-semibold text-text-primary dark:text-dark-text-primary mb-3">
              Storage
            </h2>
            <div className="space-y-2 text-sm">
              {[
                { label: "Type", value: storageQuery.data?.storage_type },
                { label: "Objects", value: storageQuery.data?.total_objects },
                { label: "Total Size", value: storageQuery.data ? `${storageQuery.data.total_size_mb} MB` : undefined },
                { label: "Health", value: storageQuery.data?.health_status },
                { label: "Bucket", value: storageQuery.data?.bucket_name },
                { label: "Local Path", value: storageQuery.data?.local_path },
              ].map(({ label, value }) => (
                <div
                  key={label}
                  className="flex justify-between py-1.5 border-b border-border/50 dark:border-dark-border/50"
                >
                  <span className="text-text-secondary dark:text-dark-text-secondary">
                    {label}
                  </span>
                  <span className="text-text-primary dark:text-dark-text-primary font-medium">
                    {value ?? "-"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Files Table */}
        <div className="rounded-xl border border-border bg-surface p-4 dark:border-dark-border dark:bg-dark-surface">
          <h2 className="text-sm font-semibold text-text-primary dark:text-dark-text-primary mb-3">
            Files
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border dark:border-dark-border">
                  {["Name", "User", "MIME", "Size", ""].map((h) => (
                    <th
                      key={h}
                      className="text-left py-2 px-2 text-text-secondary dark:text-dark-text-secondary font-medium"
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
                    className="border-b border-border/50 dark:border-dark-border/50"
                  >
                    <td className="py-2 px-2 text-text-primary dark:text-dark-text-primary">
                      {file.file_name}
                    </td>
                    <td className="py-2 px-2 text-text-secondary dark:text-dark-text-secondary text-xs font-mono">
                      {file.user_id.slice(0, 8)}
                    </td>
                    <td className="py-2 px-2 text-text-secondary dark:text-dark-text-secondary">
                      {file.mime_type}
                    </td>
                    <td className="py-2 px-2 text-text-secondary dark:text-dark-text-secondary">
                      {Math.round(file.size_bytes / 1024)} KB
                    </td>
                    <td className="py-2 px-2">
                      <button
                        onClick={() => deleteFileMutation.mutate(file.id)}
                        disabled={deleteFileMutation.isPending}
                        className="p-1 rounded text-text-tertiary hover:text-danger dark:text-dark-text-tertiary dark:hover:text-danger transition-colors"
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
                {files.length === 0 && (
                  <tr>
                    <td
                      colSpan={5}
                      className="py-4 text-center text-text-tertiary dark:text-dark-text-tertiary"
                    >
                      No files uploaded yet
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
