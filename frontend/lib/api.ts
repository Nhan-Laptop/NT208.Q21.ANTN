import {
  AdminOverview,
  ChatCompletionResponse,
  FileAttachment,
  FileUploadResponse,
  Message,
  Session,
  StorageStats,
  StorageHealth,
  User,
} from "@/lib/types";
import { toast } from "sonner";

// Always use same-origin calls and let Next.js rewrite/proxy to the backend.
// This makes ngrok/custom-domain work without exposing the backend or dealing with CORS.
const API_BASE = "";

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export function getApiErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Phiên đăng nhập hết hạn.";
    if (error.status === 403) return "Không có quyền truy cập.";
    if (error.status === 404) return "Không tìm thấy tài nguyên.";
    if (error.status === 413) return "File vượt giới hạn kích thước.";
    if (error.status === 415) return "Loại file không được hỗ trợ.";
    if (error.status === 429) return "Thao tác quá nhanh, thử lại sau.";
    if (error.status >= 500) return "Lỗi server, vui lòng thử lại sau.";
    return error.message;
  }
  if (error instanceof TypeError && error.message.includes("fetch")) {
    return "Không thể kết nối đến server. Kiểm tra backend đang chạy.";
  }
  if (error instanceof Error) return error.message;
  return "Có lỗi xảy ra.";
}

export function showApiError(error: unknown) {
  toast.error(getApiErrorMessage(error));
}

async function parseResponse(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (response.status === 204) {
    return null;
  }
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null,
): Promise<T> {
  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type") && options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  const payload = await parseResponse(response);
  if (!response.ok) {
    const message =
      typeof payload === "object" && payload && "detail" in payload
        ? String((payload as Record<string, unknown>).detail)
        : `Request failed: ${response.status}`;
    throw new ApiError(response.status, message, payload);
  }

  return payload as T;
}

export const api = {
  async register(email: string, password: string, fullName?: string): Promise<User> {
    return request<User>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, full_name: fullName ?? null }),
    });
  },

  async login(email: string, password: string): Promise<string> {
    const body = new URLSearchParams();
    body.set("username", email);
    body.set("password", password);

    const result = await request<{ access_token: string }>("/api/v1/auth/login", {
      method: "POST",
      body,
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
    });

    return result.access_token;
  },

  async me(token: string): Promise<User> {
    return request<User>("/api/v1/auth/me", {}, token);
  },

  async listSessions(token: string): Promise<Session[]> {
    return request<Session[]>("/api/v1/sessions", {}, token);
  },

  async getSession(token: string, sessionId: string): Promise<Session> {
    return request<Session>(`/api/v1/sessions/${sessionId}`, {}, token);
  },

  async createSession(token: string, title: string, mode: Session["mode"]): Promise<Session> {
    return request<Session>(
      "/api/v1/sessions",
      {
        method: "POST",
        body: JSON.stringify({ title, mode }),
      },
      token,
    );
  },

  async updateSession(
    token: string,
    sessionId: string,
    payload: Partial<Pick<Session, "title" | "mode">>,
  ): Promise<Session> {
    return request<Session>(
      `/api/v1/sessions/${sessionId}`,
      {
        method: "PATCH",
        body: JSON.stringify(payload),
      },
      token,
    );
  },

  async deleteSession(token: string, sessionId: string): Promise<void> {
    await request<void>(`/api/v1/sessions/${sessionId}`, { method: "DELETE" }, token);
  },

  async listMessages(token: string, sessionId: string): Promise<Message[]> {
    return request<Message[]>(`/api/v1/sessions/${sessionId}/messages`, {}, token);
  },

  async sendChat(token: string, sessionId: string, userMessage: string, mode?: string): Promise<ChatCompletionResponse> {
    return request<ChatCompletionResponse>(
      `/api/v1/chat/${sessionId}`,
      {
        method: "POST",
        body: JSON.stringify({ user_message: userMessage, mode: mode || undefined }),
      },
      token,
    );
  },

  async verifyCitation(token: string, sessionId: string, text: string): Promise<void> {
    await request("/api/v1/tools/verify-citation", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, text }),
    }, token);
  },

  async journalMatch(token: string, sessionId: string, abstract: string): Promise<void> {
    await request("/api/v1/tools/journal-match", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, abstract }),
    }, token);
  },

  async retractionScan(token: string, sessionId: string, text: string): Promise<void> {
    await request("/api/v1/tools/retraction-scan", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, text }),
    }, token);
  },

  async summarizePdf(token: string, sessionId: string, fileId?: string): Promise<void> {
    await request("/api/v1/tools/summarize-pdf", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, file_id: fileId ?? null }),
    }, token);
  },

  async detectAiWriting(token: string, sessionId: string, text: string): Promise<void> {
    await request("/api/v1/tools/ai-detect", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, text }),
    }, token);
  },

  async uploadFile(token: string, sessionId: string, file: File): Promise<FileUploadResponse> {
    const body = new FormData();
    body.append("session_id", sessionId);
    body.append("upload", file);
    return request<FileUploadResponse>(
      "/api/v1/upload",
      {
        method: "POST",
        body,
      },
      token,
    );
  },

  async listFiles(token: string, sessionId?: string): Promise<FileAttachment[]> {
    const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
    const out = await request<{ files: FileAttachment[] }>(`/api/v1/upload${query}`, {}, token);
    return out.files;
  },

  async downloadFile(token: string, fileId: string): Promise<Blob> {
    const response = await fetch(`${API_BASE}/api/v1/upload/${fileId}`, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
    if (!response.ok) {
      const body = await parseResponse(response);
      const message =
        typeof body === "object" && body && "detail" in body
          ? String((body as Record<string, unknown>).detail)
          : `Request failed: ${response.status}`;
      throw new ApiError(response.status, message, body);
    }
    return response.blob();
  },

  async adminOverview(token: string): Promise<AdminOverview> {
    return request<AdminOverview>("/api/v1/admin/overview", {}, token);
  },

  async adminUsers(token: string): Promise<User[]> {
    return request<User[]>("/api/v1/admin/users", {}, token);
  },

  async adminFiles(token: string): Promise<FileAttachment[]> {
    const out = await request<{ files: FileAttachment[] }>("/api/v1/admin/files", {}, token);
    return out.files;
  },

  async adminDeleteFile(token: string, fileId: string): Promise<void> {
    await request<void>(`/api/v1/admin/files/${fileId}`, { method: "DELETE" }, token);
  },

  async promoteUser(token: string, userId: string, role: "admin" | "researcher"): Promise<User> {
    return request<User>(
      "/api/v1/auth/admin/promote",
      {
        method: "POST",
        body: JSON.stringify({ user_id: userId, role }),
      },
      token,
    );
  },

  async adminUpdateRole(token: string, userId: string, role: "admin" | "researcher"): Promise<User> {
    return request<User>(
      `/api/v1/admin/users/${userId}/role`,
      {
        method: "PATCH",
        body: JSON.stringify({ role }),
      },
      token,
    );
  },

  async adminStorage(token: string): Promise<StorageStats> {
    return request<StorageStats>("/api/v1/admin/storage", {}, token);
  },

  async adminStorageHealth(token: string): Promise<StorageHealth> {
    return request<StorageHealth>("/api/v1/admin/storage/health", {}, token);
  },
};
