"use client";

import { api, showApiError } from "@/lib/api";
import { Message, Session } from "@/lib/types";
import { createContext, ReactNode, useCallback, useContext, useMemo, useReducer } from "react";
import { toast } from "sonner";

/* ── State ── */
interface ChatState {
  sessions: Session[];
  activeSessionId: string | null;
  messages: Message[];
  isLoadingSessions: boolean;
  isLoadingMessages: boolean;
  isSending: boolean;
  mode: Session["mode"];
}

const DEFAULT_NEW_CHAT_TITLE = "Trò chuyện mới";

function upsertSession(sessions: Session[], nextSession: Session): Session[] {
  const existingIndex = sessions.findIndex((session) => session.id === nextSession.id);
  if (existingIndex === -1) {
    return [nextSession, ...sessions];
  }

  const updatedSessions = [...sessions];
  updatedSessions[existingIndex] = nextSession;
  return updatedSessions;
}

const initialState: ChatState = {
  sessions: [],
  activeSessionId: null,
  messages: [],
  isLoadingSessions: false,
  isLoadingMessages: false,
  isSending: false,
  mode: "general_qa",
};

/* ── Actions ── */
type Action =
  | { type: "SET_SESSIONS"; sessions: Session[] }
  | { type: "SET_ACTIVE_SESSION"; sessionId: string | null }
  | { type: "SET_MESSAGES"; messages: Message[] }
  | { type: "ADD_MESSAGES"; messages: Message[] }
  | { type: "SET_LOADING_SESSIONS"; loading: boolean }
  | { type: "SET_LOADING_MESSAGES"; loading: boolean }
  | { type: "SET_SENDING"; sending: boolean }
  | { type: "SET_MODE"; mode: Session["mode"] }
  | { type: "NEW_CHAT" }
  | { type: "ADD_SESSION"; session: Session }
  | { type: "UPSERT_SESSION"; session: Session }
  | { type: "REMOVE_SESSION"; sessionId: string };

function reducer(state: ChatState, action: Action): ChatState {
  switch (action.type) {
    case "SET_SESSIONS":
      return { ...state, sessions: action.sessions, isLoadingSessions: false };
    case "SET_ACTIVE_SESSION":
      return { ...state, activeSessionId: action.sessionId };
    case "SET_MESSAGES":
      return { ...state, messages: action.messages, isLoadingMessages: false };
    case "ADD_MESSAGES":
      return { ...state, messages: [...state.messages, ...action.messages] };
    case "SET_LOADING_SESSIONS":
      return { ...state, isLoadingSessions: action.loading };
    case "SET_LOADING_MESSAGES":
      return { ...state, isLoadingMessages: action.loading };
    case "SET_SENDING":
      return { ...state, isSending: action.sending };
    case "SET_MODE":
      return { ...state, mode: action.mode };
    case "NEW_CHAT":
      return { ...state, activeSessionId: null, messages: [], mode: "general_qa" };
    case "ADD_SESSION":
      return {
        ...state,
        sessions: [action.session, ...state.sessions],
        activeSessionId: action.session.id,
      };
    case "UPSERT_SESSION":
      return {
        ...state,
        sessions: upsertSession(state.sessions, action.session),
      };
    case "REMOVE_SESSION": {
      const sessions = state.sessions.filter((s) => s.id !== action.sessionId);
      const activeSessionId =
        state.activeSessionId === action.sessionId ? null : state.activeSessionId;
      return {
        ...state,
        sessions,
        activeSessionId,
        messages: activeSessionId === null ? [] : state.messages,
      };
    }
    default:
      return state;
  }
}

/* ── Context ── */
interface ChatContextValue {
  state: ChatState;
  loadSessions: (token: string) => Promise<void>;
  loadMessages: (token: string, sessionId: string) => Promise<void>;
  selectSession: (sessionId: string) => void;
  startNewChat: () => void;
  setMode: (mode: Session["mode"]) => void;
  sendMessage: (token: string, text: string) => Promise<void>;
  deleteSession: (token: string, sessionId: string) => Promise<void>;
}

const ChatContext = createContext<ChatContextValue | null>(null);

export function ChatProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  const loadSessions = useCallback(async (token: string) => {
    dispatch({ type: "SET_LOADING_SESSIONS", loading: true });
    try {
      const sessions = await api.listSessions(token);
      dispatch({ type: "SET_SESSIONS", sessions });
    } catch (err) {
      dispatch({ type: "SET_LOADING_SESSIONS", loading: false });
      showApiError(err);
    }
  }, []);

  const loadMessages = useCallback(async (token: string, sessionId: string) => {
    dispatch({ type: "SET_LOADING_MESSAGES", loading: true });
    try {
      const messages = await api.listMessages(token, sessionId);
      dispatch({ type: "SET_MESSAGES", messages });
    } catch (err) {
      dispatch({ type: "SET_LOADING_MESSAGES", loading: false });
      showApiError(err);
    }
  }, []);

  const selectSession = useCallback((sessionId: string) => {
    dispatch({ type: "SET_ACTIVE_SESSION", sessionId });
  }, []);

  const startNewChat = useCallback(() => {
    dispatch({ type: "NEW_CHAT" });
  }, []);

  const setMode = useCallback((mode: Session["mode"]) => {
    dispatch({ type: "SET_MODE", mode });
  }, []);

  const sendMessage = useCallback(
    async (token: string, text: string) => {
      dispatch({ type: "SET_SENDING", sending: true });
      let sessionId = state.activeSessionId;

      try {

        // Auto-create session on first message
        if (!sessionId) {
          const session = await api.createSession(token, DEFAULT_NEW_CHAT_TITLE, state.mode);
          dispatch({ type: "ADD_SESSION", session });
          sessionId = session.id;
        }

        // Optimistic user message
        const optimisticMsg: Message = {
          id: `temp-${Date.now()}`,
          session_id: sessionId,
          role: "user",
          message_type: "text",
          content: text,
          tool_results: null,
          created_at: new Date().toISOString(),
        };
        dispatch({ type: "ADD_MESSAGES", messages: [optimisticMsg] });

        // Send to backend (include mode so backend routes to correct tool)
        const response = await api.sendChat(token, sessionId, text, state.mode);
        dispatch({ type: "UPSERT_SESSION", session: response.session });

        // Replace optimistic message with real messages
        const realMessages = await api.listMessages(token, sessionId);
        dispatch({ type: "SET_MESSAGES", messages: realMessages });
      } catch (err) {
        showApiError(err);
        // Reload messages to remove optimistic message — use local sessionId
        // (state.activeSessionId may be stale after ADD_SESSION dispatch)
        if (sessionId) {
          try {
            const messages = await api.listMessages(token, sessionId);
            dispatch({ type: "SET_MESSAGES", messages });
          } catch {
            // ignore
          }
        }
      } finally {
        dispatch({ type: "SET_SENDING", sending: false });
      }
    },
    [state.activeSessionId, state.mode],
  );

  const deleteSession = useCallback(async (token: string, sessionId: string) => {
    try {
      await api.deleteSession(token, sessionId);
      dispatch({ type: "REMOVE_SESSION", sessionId });
      toast.success("Đã xóa session");
    } catch (err) {
      showApiError(err);
    }
  }, []);

  const value = useMemo(
    () => ({
      state,
      loadSessions,
      loadMessages,
      selectSession,
      startNewChat,
      setMode,
      sendMessage,
      deleteSession,
    }),
    [state, loadSessions, loadMessages, selectSession, startNewChat, setMode, sendMessage, deleteSession],
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat() {
  const context = useContext(ChatContext);
  if (!context) throw new Error("useChat must be used within ChatProvider");
  return context;
}
