"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import {
  createSession,
  getSession,
  listSessions,
  logout,
  streamMessage,
} from "@/lib/api";
import type { ChatMessage, Source } from "@/types";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  streaming?: boolean;
}

interface SessionSummary {
  id: string;
  title: string | null;
  mode: string;
  updated_at: string;
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
}: {
  initialSessionId?: string;
}) {
  const router = useRouter();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(initialSessionId ?? null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<"researcher" | "lab_manager">("researcher");
  const [activeSources, setActiveSources] = useState<Source[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void loadSessions();
  }, []);

  useEffect(() => {
    if (!initialSessionId) {
      setMessages([]);
      setActiveSources([]);
      return;
    }
    void loadSession(initialSessionId);
  }, [initialSessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function loadSessions() {
    try {
      const data = await listSessions();
      setSessions(data);
    } catch (err) {
      if (err instanceof Error && err.message === "Unauthorized") {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load sessions");
    }
  }

  async function loadSession(sessionId: string) {
    try {
      const session = await getSession(sessionId);
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
    try {
      const session = await createSession(mode);
      setActiveSessionId(session.id);
      setMessages([]);
      setActiveSources([]);
      setError(null);
      await loadSessions();
      router.push(`/chat/${session.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create session");
    }
  }

  function handleSelectSession(sessionId: string) {
    router.push(`/chat/${sessionId}`);
  }

  async function handleSend() {
    if (!input.trim() || isStreaming) {
      return;
    }

    let sessionId = activeSessionId;
    if (!sessionId) {
      try {
        const session = await createSession(mode);
        sessionId = session.id;
        setActiveSessionId(sessionId);
        router.push(`/chat/${sessionId}`);
      } catch (err) {
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
          } else if (event.type === "error") {
            throw new Error(String(event.message ?? "Streaming failed"));
          }
        }
      }
    } catch (err) {
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

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      <aside className="w-64 flex-shrink-0 bg-white border-r border-gray-200 flex flex-col">
        <div className="p-4 border-b flex items-start justify-between gap-3">
          <div>
            <h1 className="text-base font-bold text-gray-800">RLALab AI</h1>
            <p className="text-xs text-gray-500">Research Literature Assistant</p>
          </div>
          <button
            onClick={handleLogout}
            className="text-xs text-gray-500 hover:text-gray-800 transition"
          >
            Sign out
          </button>
        </div>
        <div className="p-3">
          <button
            onClick={handleNewChat}
            className="w-full rounded-lg bg-blue-600 text-white text-sm py-2 font-medium hover:bg-blue-700 transition"
          >
            + New Chat
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {sessions.map((session) => (
            <button
              key={session.id}
              onClick={() => handleSelectSession(session.id)}
              className={`w-full text-left rounded-lg px-3 py-2 text-sm truncate transition ${
                session.id === activeSessionId
                  ? "bg-blue-50 text-blue-700"
                  : "text-gray-700 hover:bg-gray-100"
              }`}
            >
              {session.title ?? "Untitled Chat"}
            </button>
          ))}
        </div>
        <div className="p-4 border-t space-y-3">
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as "researcher" | "lab_manager")}
            className="w-full rounded-lg border border-gray-300 text-xs px-2 py-1 bg-white"
          >
            <option value="researcher">Researcher mode</option>
            <option value="lab_manager">Lab Manager mode</option>
          </select>
          <button
            onClick={() => router.push("/analytics")}
            className="w-full rounded-lg border border-gray-300 text-sm py-2 text-gray-700 hover:bg-gray-100 transition"
          >
            Analytics
          </button>
        </div>
      </aside>

      <main className="flex-1 flex flex-col overflow-hidden">
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
                {msg.content}
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
              disabled={isStreaming}
              placeholder="e.g. What are the key metabolic pathways for lipid accumulation in Y. lipolytica?"
              className="flex-1 rounded-xl border border-gray-300 px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
            />
            <button
              onClick={() => void handleSend()}
              disabled={isStreaming || !input.trim()}
              className="rounded-xl bg-blue-600 text-white px-5 py-2 text-sm font-semibold hover:bg-blue-700 disabled:opacity-50 transition"
            >
              {isStreaming ? "..." : "Send"}
            </button>
          </div>
        </div>
      </main>

      {activeSources.length > 0 && (
        <aside className="w-80 flex-shrink-0 bg-white border-l border-gray-200 overflow-y-auto">
          <div className="p-4 border-b">
            <h2 className="text-sm font-semibold text-gray-700">Retrieved Sources</h2>
            <p className="text-xs text-gray-400">{activeSources.length} documents</p>
          </div>
          <div className="divide-y">
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
    </div>
  );
}