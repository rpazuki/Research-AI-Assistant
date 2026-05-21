"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

import {
  createSession,
  deleteSession,
  getAdminUserSession,
  getChatQuota,
  getSession,
  listAdminUserSessions,
  listSessions,
  logout,
  streamMessage,
  updateSessionTitle,
} from "@/lib/api";
import type { ChatMessage, ChatQuota, ChatSession, Source } from "@/types";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  streaming?: boolean;
}

type SessionSummary = Pick<ChatSession, "id" | "title" | "mode" | "updated_at">;

interface SessionContextMenuState {
  x: number;
  y: number;
  session: SessionSummary;
}

function parseSSELine(line: string): { type: string; [key: string]: unknown } | null {
  if (!line.startsWith("data: ")) {
    return null;
  }
  try {
    return JSON.parse(line.slice(6));
  } catch {
    return null;
  }
}

function toUiMessage(message: ChatMessage): Message {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    sources: message.sources ?? undefined,
  };
}

export default function ChatClient({
  initialSessionId,
  adminUserId,
  readOnly = false,
  readOnlyLabel = "Read-only admin view",
  backHref = "/admin",
}: {
  initialSessionId?: string;
  adminUserId?: string;
  readOnly?: boolean;
  readOnlyLabel?: string;
  backHref?: string;
}) {
  const router = useRouter();
  const isReadOnly = readOnly || Boolean(adminUserId);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(initialSessionId ?? null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<"researcher" | "lab_manager">("researcher");
  const [activeSources, setActiveSources] = useState<Source[]>([]);
  const [quota, setQuota] = useState<ChatQuota | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [isSavingTitle, setIsSavingTitle] = useState(false);
  const [isDeletingSession, setIsDeletingSession] = useState(false);
  const [contextMenu, setContextMenu] = useState<SessionContextMenuState | null>(null);
  const skipBlurSaveRef = useRef(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  
  // Sidebar state
  const [showChatList, setShowChatList] = useState(true);
  const [rightSidebarVisible, setRightSidebarVisible] = useState(true);
  const [leftSidebarWidth, setLeftSidebarWidth] = useState(256);
  const [rightSidebarWidth, setRightSidebarWidth] = useState(320);
  const [isDraggingLeft, setIsDraggingLeft] = useState(false);
  const [isDraggingRight, setIsDraggingRight] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void loadSessions();
    if (!isReadOnly) {
      void loadQuota();
    }
  }, [adminUserId, isReadOnly]);

  useEffect(() => {
    if (!initialSessionId) {
      setActiveSessionId(null);
      setMessages([]);
      setActiveSources([]);
      return;
    }
    void loadSession(initialSessionId);
  }, [adminUserId, initialSessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (!contextMenu) {
      return;
    }

    const closeMenu = () => setContextMenu(null);
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setContextMenu(null);
      }
    };

    document.addEventListener("click", closeMenu);
    document.addEventListener("contextmenu", closeMenu);
    document.addEventListener("keydown", closeOnEscape);

    return () => {
      document.removeEventListener("click", closeMenu);
      document.removeEventListener("contextmenu", closeMenu);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [contextMenu]);

  // Toggle functions
  function toggleLeftSidebar() {
    setShowChatList((prev) => !prev);
  }

  function toggleRightSidebar() {
    setRightSidebarVisible((prev) => !prev);
  }

  // Drag effect for resizing sidebars
  useEffect(() => {
    if (!isDraggingLeft && !isDraggingRight) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!containerRef.current) return;

      if (isDraggingLeft) {
        const containerRect = containerRef.current.getBoundingClientRect();
        const newWidth = Math.max(200, Math.min(400, e.clientX - containerRect.left));
        setLeftSidebarWidth(newWidth);
      }

      if (isDraggingRight) {
        const containerRect = containerRef.current.getBoundingClientRect();
        const newWidth = Math.max(200, Math.min(500, containerRect.right - e.clientX));
        setRightSidebarWidth(newWidth);
      }
    };

    const handleMouseUp = () => {
      setIsDraggingLeft(false);
      setIsDraggingRight(false);
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDraggingLeft, isDraggingRight]);

  async function loadSessions() {
    try {
      const data = adminUserId ? await listAdminUserSessions(adminUserId) : await listSessions();
      setSessions(data);
    } catch (err) {
      if (err instanceof Error && err.message === "Unauthorized") {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load sessions");
    }
  }

  async function loadQuota() {
    if (isReadOnly) {
      return;
    }

    try {
      const data = await getChatQuota();
      setQuota(data);
    } catch (err) {
      if (err instanceof Error && err.message === "Unauthorized") {
        router.push("/login");
      }
    }
  }

  function applyTokenLimitError(err: unknown) {
    const message = err instanceof Error ? err.message : "";
    if (message.toLowerCase().includes("token limit")) {
      setQuota((previous) => ({
        token_limit: previous?.token_limit ?? 0,
        total_token_count: previous?.total_token_count ?? 0,
        token_limit_reached: true,
        message,
      }));
      void loadQuota();
    }
  }

  function getDisplaySessionTitle(session: SessionSummary) {
    const cleaned = session.title?.trim();
    return cleaned ? cleaned : "Untitled Chat";
  }

  async function loadSession(sessionId: string) {
    try {
      const session = adminUserId
        ? await getAdminUserSession(adminUserId, sessionId)
        : await getSession(sessionId);
      setActiveSessionId(session.id);
      setMode((session.mode as "researcher" | "lab_manager") ?? "researcher");
      const nextMessages = session.messages.map(toUiMessage);
      setMessages(nextMessages);
      const lastAssistant = [...nextMessages].reverse().find((msg) => msg.role === "assistant");
      setActiveSources(lastAssistant?.sources ?? []);
      setError(null);
    } catch (err) {
      if (err instanceof Error && err.message === "Unauthorized") {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load session");
    }
  }

  async function handleLogout() {
    await logout();
    router.push("/login");
    router.refresh();
  }

  async function handleNewChat() {
    if (isReadOnly) {
      return;
    }

    if (quota?.token_limit_reached) {
      return;
    }

    try {
      const session = await createSession(mode);
      setActiveSessionId(session.id);
      setMessages([]);
      setActiveSources([]);
      setError(null);
      await loadSessions();
      router.push(getSessionHref(session.id));
    } catch (err) {
      applyTokenLimitError(err);
      setError(err instanceof Error ? err.message : "Failed to create session");
    }
  }

  function handleSelectSession(sessionId: string) {
    router.push(getSessionHref(sessionId));
  }

  function handleSessionContextMenu(
    event: ReactMouseEvent<HTMLButtonElement>,
    session: SessionSummary
  ) {
    if (isReadOnly) {
      return;
    }

    event.preventDefault();
    setContextMenu({ x: event.clientX, y: event.clientY, session });
  }

  function handleStartTitleEdit(session: SessionSummary) {
    setEditingSessionId(session.id);
    setEditingTitle(session.title?.trim() ?? "");
    setError(null);
  }

  function handleCancelTitleEdit() {
    setEditingSessionId(null);
    setEditingTitle("");
  }

  async function handleSaveTitle(sessionId: string, rawTitle?: string) {
    if (isReadOnly) {
      return;
    }

    if (isSavingTitle) {
      return;
    }

    const nextTitle = (rawTitle ?? editingTitle).trim();
    if (!nextTitle) {
      setError("Chat title cannot be empty");
      return;
    }

    try {
      setIsSavingTitle(true);
      await updateSessionTitle(sessionId, nextTitle);
      setSessions((prev) =>
        prev.map((session) =>
          session.id === sessionId ? { ...session, title: nextTitle } : session
        )
      );
      setEditingSessionId(null);
      setEditingTitle("");
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update title");
    } finally {
      setIsSavingTitle(false);
    }
  }

  async function handleDeleteSession(sessionId: string) {
    if (isReadOnly) {
      return;
    }

    if (isDeletingSession) {
      return;
    }

    const selectedSession = sessions.find((session) => session.id === sessionId);
    const label = selectedSession ? getDisplaySessionTitle(selectedSession) : "this chat";
    const shouldDelete = window.confirm(`Delete \"${label}\"? This cannot be undone.`);
    if (!shouldDelete) {
      return;
    }

    try {
      setIsDeletingSession(true);
      await deleteSession(sessionId);
      const remaining = sessions.filter((session) => session.id !== sessionId);
      setSessions(remaining);
      if (editingSessionId === sessionId) {
        handleCancelTitleEdit();
      }

      if (activeSessionId === sessionId) {
        if (remaining.length > 0) {
          const nextSessionId = remaining[0].id;
          setActiveSessionId(nextSessionId);
          router.push(getSessionHref(nextSessionId));
        } else {
          setActiveSessionId(null);
          setMessages([]);
          setActiveSources([]);
          router.push("/chat");
        }
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete chat");
    } finally {
      setIsDeletingSession(false);
    }
  }

  async function handleSend() {
    if (isReadOnly) {
      return;
    }

    if (!input.trim() || isStreaming || quota?.token_limit_reached) {
      return;
    }

    let sessionId = activeSessionId;
    if (!sessionId) {
      try {
        const session = await createSession(mode);
        sessionId = session.id;
        setActiveSessionId(sessionId);
        router.push(getSessionHref(sessionId));
      } catch (err) {
        applyTokenLimitError(err);
        setError(err instanceof Error ? err.message : "Failed to create session");
        return;
      }
    }

    const query = input;
    const userMsg: Message = { id: crypto.randomUUID(), role: "user", content: query };
    const assistantMsg: Message = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: "",
      streaming: true,
    };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput("");
    setActiveSources([]);
    setError(null);
    setIsStreaming(true);

    let finalSources: Source[] = [];

    try {
      const stream = await streamMessage(sessionId, query, mode);
      const reader = stream.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          const event = parseSSELine(line.trim());
          if (!event) {
            continue;
          }

          if (event.type === "token") {
            const tokenText = event.data as string;
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === "assistant") {
                updated[updated.length - 1] = { ...last, content: last.content + tokenText };
              }
              return updated;
            });
          } else if (event.type === "sources") {
            finalSources = event.data as Source[];
            setActiveSources(finalSources);
          } else if (event.type === "done") {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === "assistant") {
                updated[updated.length - 1] = {
                  ...last,
                  streaming: false,
                  sources: finalSources,
                };
              }
              return updated;
            });
            await loadSessions();
            await loadQuota();
          } else if (event.type === "error") {
            throw new Error(String(event.message ?? "Streaming failed"));
          }
        }
      }
    } catch (err) {
      applyTokenLimitError(err);
      setError(err instanceof Error ? err.message : "Streaming failed");
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last?.role === "assistant") {
          updated[updated.length - 1] = {
            ...last,
            streaming: false,
            content: last.content || "Unable to generate a response.",
          };
        }
        return updated;
      });
    } finally {
      setIsStreaming(false);
    }
  }

  function getSessionHref(sessionId: string) {
    return adminUserId
      ? `/admin/users/${adminUserId}/experience/${sessionId}`
      : `/chat/${sessionId}`;
  }

  return (
    <div ref={containerRef} className="flex h-screen bg-gray-50 overflow-hidden">
      {/* Left sidebar - chat list */}
      {showChatList && (
        <aside style={{ width: `${leftSidebarWidth}px` }} className="flex-shrink-0 bg-white border-r border-gray-200 flex flex-col">
          <div className="p-4 border-b flex items-start justify-between gap-3">
            <div className="flex items-start gap-3">
              <button
                onClick={toggleLeftSidebar}
                className="text-gray-500 hover:text-gray-700 transition"
                title="Hide chat list"
              >
                ✕
              </button>
              <div>
                <h1 className="text-base font-bold text-gray-800">RLALab AI</h1>
                <p className="text-xs text-gray-500">Research Literature Assistant</p>
              </div>
            </div>
            {isReadOnly ? (
              <Link
                href={backHref}
                className="text-xs text-gray-500 hover:text-gray-800 transition"
              >
                Back
              </Link>
            ) : (
              <div className="flex gap-2">
                <button
                  onClick={handleLogout}
                  className="text-xs text-gray-500 hover:text-gray-800 transition"
                >
                  Sign out
                </button>
              </div>
            )}
          </div>
          <div className="p-3">
            {quota?.token_limit_reached && (
              <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs leading-relaxed text-red-700">
                {quota.message ??
                  "Your token limit has been reached. Please ask your lab admin for more tokens."}
              </div>
            )}
            <button
              onClick={handleNewChat}
              disabled={isReadOnly || quota?.token_limit_reached}
              className="w-full rounded-lg bg-blue-600 text-white text-sm py-2 font-medium hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50 transition"
            >
              + New Chat
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {sessions.map((session) => {
              const isActive = session.id === activeSessionId;
              const isEditing = editingSessionId === session.id;
              return (
                <div
                  key={session.id}
                  className={`rounded-lg px-2 py-1 transition ${
                    isActive ? "bg-blue-50" : "hover:bg-gray-100"
                  }`}
                >
                  {isEditing ? (
                    <input
                      autoFocus
                      value={editingTitle}
                      disabled={isSavingTitle}
                      onChange={(e) => setEditingTitle(e.target.value)}
                      onBlur={(e) => {
                        if (skipBlurSaveRef.current) {
                          skipBlurSaveRef.current = false;
                          return;
                        }
                        void handleSaveTitle(session.id, e.currentTarget.value);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          skipBlurSaveRef.current = true;
                          void handleSaveTitle(session.id, e.currentTarget.value);
                        }
                        if (e.key === "Escape") {
                          e.preventDefault();
                          skipBlurSaveRef.current = true;
                          handleCancelTitleEdit();
                        }
                      }}
                      className="w-full rounded-md border border-blue-200 bg-white px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                      aria-label="Edit chat title"
                    />
                  ) : (
                    <button
                      onClick={() => handleSelectSession(session.id)}
                      onContextMenu={(event) => handleSessionContextMenu(event, session)}
                      className={`w-full text-left rounded-md px-1 py-1 text-sm truncate transition ${
                        isActive ? "text-blue-700" : "text-gray-700"
                      }`}
                      title="Right-click for actions"
                    >
                      {getDisplaySessionTitle(session)}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
          <div className="p-4 border-t space-y-3">
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as "researcher" | "lab_manager")}
              disabled={isReadOnly}
              className="w-full rounded-lg border border-gray-300 text-xs px-2 py-1 bg-white disabled:opacity-60"
            >
              <option value="researcher">Researcher mode</option>
              <option value="lab_manager">Lab Manager mode</option>
            </select>
            {!isReadOnly && (
              <button
                onClick={() => router.push("/analytics")}
                className="w-full rounded-lg border border-gray-300 text-sm py-2 text-gray-700 hover:bg-gray-100 transition"
              >
                Analytics
              </button>
            )}
          </div>
        </aside>
      )}

      {/* Left splitter - draggable */}
      {showChatList && (
        <div
          onMouseDown={() => setIsDraggingLeft(true)}
          className="w-1 bg-gray-200 hover:bg-blue-400 cursor-col-resize hover:shadow-md transition-all"
          title="Drag to resize chat list"
        />
      )}

      {/* Main chat area */}
      <main className="flex-1 flex flex-col overflow-hidden relative">
        {/* Top toolbar */}
        <div className="flex items-center justify-between px-6 py-2 border-b bg-white">
          <div>
            {!showChatList && (
              <button
                onClick={toggleLeftSidebar}
                className="px-2 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 transition"
                title="Show chat list"
              >
                ☰ Chat List
              </button>
            )}
          </div>
          {isReadOnly && (
            <div
              className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-800"
              role="status"
            >
              {readOnlyLabel}
            </div>
          )}
          <div>
            {activeSources.length > 0 && !rightSidebarVisible && (
              <button
                onClick={toggleRightSidebar}
                className="px-2 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 transition"
                title="Show sources"
              >
                📄 Sources ({activeSources.length})
              </button>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {messages.length === 0 && (
            <div className="flex items-center justify-center h-full text-center text-gray-400">
              <div>
                <p className="text-lg font-medium mb-2">Ask the literature</p>
                <p className="text-sm max-w-sm">
                  Query the RLA Lab&apos;s curated scientific corpus for grounded, cited answers.
                </p>
              </div>
            </div>
          )}

          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-2xl rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "bg-blue-600 text-white rounded-br-sm"
                    : "bg-white border border-gray-200 text-gray-800 rounded-bl-sm shadow-sm"
                }`}
              >
                {msg.role === "user" ? (
                  msg.content
                ) : (
                  <div className="assistant-markdown">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                )}
                {msg.streaming && (
                  <span className="inline-block ml-1 w-2 h-4 bg-blue-400 animate-pulse rounded-sm" />
                )}
              </div>
            </div>
          ))}

          {error && (
            <div className="max-w-2xl rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="border-t bg-white px-6 py-4">
          <div className="flex gap-3 max-w-3xl mx-auto">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void handleSend();
                }
              }}
              disabled={isReadOnly || isStreaming || quota?.token_limit_reached}
              placeholder={
                isReadOnly
                  ? "Read-only admin view"
                  : quota?.token_limit_reached
                  ? "Token limit reached"
                  : "e.g. What are the key metabolic pathways for lipid accumulation in Y. lipolytica?"
              }
              className="flex-1 rounded-xl border border-gray-300 px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
            />
            <button
              onClick={() => void handleSend()}
              disabled={isReadOnly || isStreaming || !input.trim() || quota?.token_limit_reached}
              className="rounded-xl bg-blue-600 text-white px-5 py-2 text-sm font-semibold hover:bg-blue-700 disabled:opacity-50 transition"
            >
              {isStreaming ? "..." : "Send"}
            </button>
          </div>
        </div>
      </main>

      {/* Right splitter - draggable */}
      {rightSidebarVisible && activeSources.length > 0 && (
        <div
          onMouseDown={() => setIsDraggingRight(true)}
          className="w-1 bg-gray-200 hover:bg-blue-400 cursor-col-resize hover:shadow-md transition-all"
          title="Drag to resize sources panel"
        />
      )}

      {/* Right sidebar - sources */}
      {rightSidebarVisible && activeSources.length > 0 && (
        <aside style={{ width: `${rightSidebarWidth}px` }} className="flex-shrink-0 bg-white border-l border-gray-200 flex flex-col overflow-hidden">
          <div className="p-4 border-b flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-gray-700">Retrieved Sources</h2>
              <p className="text-xs text-gray-400">{activeSources.length} documents</p>
            </div>
            <button
              onClick={toggleRightSidebar}
              className="text-gray-500 hover:text-gray-700 ml-2"
              title="Hide sources"
            >
              ✕
            </button>
          </div>
          <div className="flex-1 overflow-y-auto divide-y">
            {activeSources.map((source, index) => (
              <div key={`${source.pmid ?? source.doi ?? source.title ?? "source"}-${index}`} className="p-4">
                <p className="text-xs font-semibold text-gray-800 leading-snug mb-1 line-clamp-2">
                  {source.title ?? "Untitled"}
                </p>
                <p className="text-xs text-gray-500 mb-2">
                  {[source.journal, source.year].filter(Boolean).join(" · ")}
                </p>
                {source.snippet && (
                  <p className="text-xs text-gray-600 line-clamp-3 leading-relaxed mb-2">
                    {source.snippet}
                  </p>
                )}
                {source.url && (
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-600 hover:underline"
                  >
                    {source.pmid ? `PMID ${source.pmid}` : source.doi ? `DOI ${source.doi}` : "View source"}
                  </a>
                )}
              </div>
            ))}
          </div>
        </aside>
      )}

      {contextMenu && (
        <div
          className="fixed z-50 min-w-40 rounded-md border border-gray-200 bg-white py-1 shadow-lg"
          style={{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }}
          role="menu"
          onClick={(event) => event.stopPropagation()}
          onContextMenu={(event) => event.preventDefault()}
        >
          <button
            type="button"
            className="w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-100"
            role="menuitem"
            onClick={() => {
              handleStartTitleEdit(contextMenu.session);
              setContextMenu(null);
            }}
          >
            Rename
          </button>
          <button
            type="button"
            className="w-full px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50 disabled:opacity-50"
            role="menuitem"
            disabled={isDeletingSession}
            onClick={() => {
              const sessionId = contextMenu.session.id;
              setContextMenu(null);
              void handleDeleteSession(sessionId);
            }}
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
}
