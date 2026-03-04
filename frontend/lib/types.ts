export type UserRole = "admin" | "researcher";

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: UserRole;
  created_at: string;
}

export interface Session {
  id: string;
  title: string;
  mode: "general_qa" | "verification" | "journal_match" | "retraction" | "ai_detection";
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system" | "tool";
  message_type:
    | "text"
    | "citation_report"
    | "journal_list"
    | "retraction_report"
    | "pdf_summary"
    | "ai_writing_detection"
    | "file_upload";
  content: string | null;
  tool_results: Record<string, unknown> | unknown[] | null;
  created_at: string;
}

export interface ChatCompletionResponse {
  session_id: string;
  user_message: Message;
  assistant_message: Message;
}

export interface FileAttachment {
  id: string;
  session_id: string;
  message_id: string | null;
  user_id: string;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  storage_key: string;
  storage_url: string;
  storage_encrypted: boolean;
  storage_encryption_alg: string | null;
  created_at: string;
}

export interface FileUploadResponse {
  id: string;
  session_id: string;
  message_id: string | null;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  storage_url: string;
  storage_encrypted: boolean;
  storage_encryption_alg: string | null;
  created_at: string;
}

export interface AdminOverview {
  users: number;
  sessions: number;
  messages: number;
  files: number;
  total_storage_bytes: number;
  total_storage_mb: number;
  active_admins: number;
  active_researchers: number;
}

export interface StorageHealth {
  status: string;
  storage_type: string;
  accessible: boolean;
  details?: Record<string, unknown>;
  error?: string;
}

export interface StorageStats {
  storage_type: string;
  total_objects: number;
  total_size_bytes: number;
  total_size_mb: number;
  bucket_name: string | null;
  local_path: string | null;
  health_status: string;
}

export interface ApiErrorShape {
  detail?: string;
  [key: string]: unknown;
}
