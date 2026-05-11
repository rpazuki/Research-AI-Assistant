"use client";

/**
 * Main chat page.
 *
 * Layout:
 *   Left sidebar  — session history + new chat button
 *   Centre panel  — chat window (messages + input)
 *   Right panel   — source documents (slides in after response)
 *
 * Streaming:
 *   Uses fetch + ReadableStream to consume SSE tokens from the backend.
 *   Tokens are appended to a working message in real-time.
 *   After the stream ends, sources are displayed in the right panel.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { createSession, listSessions, streamMessage } from "@/lib/api";
import { Source } from "@/types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function getToken(): string | null {
  // TODO: Replace with next-auth session when configured
  if (typeof window !== "undefined") {
    return localStorage.getItem("rlalab_token");
  }
  return null;
}

function parseSSELine(line: string): { type: string; [key: string]: unknown } | null {
  if (!line.startsWith("data: ")) return null;
  try {
    return JSON.parse(line.slice(6));
  } catch {
    return null;
  }
}

// ── Types ─────────────────────────────────────────────────────────────────────

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

// ── Component ─────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<"researcher" | "lab_manager">("researcher");
  const [activeSources, setActiveSources] = useState<Source[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = getToken();
    if (!t) { router.push("/login"); return; }
    setToken(t);
    loadSessions(t);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function loadSessions(t: string) {
    try {
      const data = await listSessions(t);
      setSessions(data);
    } catch { /* ignore */ }
  }

  async function handleNewChat() {
    if (!token) return;
    const session = await createSession(token, mode);
    setActiveSessionId(session.id);
    setMessages([]);
    setActiveSources([]);
    loadSessions(token);
  }

  async function handleSend() {
    if (!input.trim() || !token || isStreaming) return;

    let sessionId = activeSessionId;
    if (!sessionId) {
      const session = await createSession(token, mode);
      sessionId = session.id;
      setActiveSessionId(sessionId);
    }

    const userMsg: Message = { id: crypto.randomUUID(), role: "user", content: input };
    const assistantMsg: Message = {
      id: crypto.randomUUID(), role: "assistant", content: "", streaming: true,
    };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput("");
    setActiveSources([]);
    setIsStreaming(true);

    try {
      const stream = await streamMessage(token, sessionId, input, mode);
      const reader = stream.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          const event = parseSSELine(line.trim());
          if (!event) continue;

          if (event.type === "token") {
            const token_text = event.data as string;
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last.role === "assistant") {
                updated[updated.length - 1] = { ...last, content: last.content + token_text };
              }
              return updated;
            });
          } else if (event.type === "sources") {
            setActiveSources(event.data as Source[]);
          } else if (event.type === "done") {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last.role === "assistant") {
                updated[updated.length - 1] = { ...last, streaming: false, sources: activeSources };
              }
              return updated;
            });
            loadSessions(token!);
          } else if (event.type === "error") {
            console.error("Stream error:", event.message);
          }
        }
      }
    } finally {
      setIsStreaming(false);
    }
  }

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      {/* ── Sidebar ── */}
      <aside className="w-64 flex-shrink-0 bg-white border-r border-gray-200 flex flex-col">
        <div className="p-4 border-b">
          <h1 className="text-base font-bold text-gray-800">RLALab AI</h1>
          <p className="text-xs text-gray-500">Research Literature Assistant</p>
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
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => setActiveSessionId(s.id)}
              className={`w-full text-left rounded-lg px-3 py-2 text-sm truncate transition ${
                s.id === activeSessionId ? "bg-blue-50 text-blue-700" : "text-gray-700 hover:bg-gray-100"
              }`}
            >
              {s.title ?? "Untitled Chat"}
            </button>
          ))}
        </div>
        <div className="p-4 border-t">
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as "researcher" | "lab_manager")}
            className="w-full rounded-lg border border-gray-300 text-xs px-2 py-1 bg-white"
          >
            <option value="researcher">🔬 Researcher mode</option>
            <option value="lab_manager">🧪 Lab Manager mode</option>
          </select>
        </div>
      </aside>

      {/* ── Main chat ── */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {messages.length === 0 && (
            <div className="flex items-center justify-center h-full text-center text-gray-400">
              <div>
                <p className="text-lg font-medium mb-2">Ask the literature</p>
                <p className="text-sm max-w-sm">
                  Query the RLA Lab's curated scientific corpus — synthetic biology, metabolic
                  engineering, and sustainable bioproduction.
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
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="border-t bg-white px-6 py-4">
          <div className="flex gap-3 max-w-3xl mx-auto">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
              disabled={isStreaming}
              placeholder="e.g. What are the key metabolic pathways for lipid accumulation in Y. lipolytica?"
              className="flex-1 rounded-xl border border-gray-300 px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
            />
            <button
              onClick={handleSend}
              disabled={isStreaming || !input.trim()}
              className="rounded-xl bg-blue-600 text-white px-5 py-2 text-sm font-semibold hover:bg-blue-700 disabled:opacity-50 transition"
            >
              {isStreaming ? "…" : "Send"}
            </button>
          </div>
        </div>
      </main>

      {/* ── Sources panel ── */}
      {activeSources.length > 0 && (
        <aside className="w-80 flex-shrink-0 bg-white border-l border-gray-200 overflow-y-auto">
          <div className="p-4 border-b">
            <h2 className="text-sm font-semibold text-gray-700">Retrieved Sources</h2>
            <p className="text-xs text-gray-400">{activeSources.length} documents</p>
          </div>
          <div className="divide-y">
            {activeSources.map((src, i) => (
              <div key={i} className="p-4">
                <p className="text-xs font-semibold text-gray-800 leading-snug mb-1 line-clamp-2">
                  {src.title ?? "Untitled"}
                </p>
                <p className="text-xs text-gray-500 mb-2">
                  {[src.journal, src.year].filter(Boolean).join(" · ")}
                </p>
                {src.snippet && (
                  <p className="text-xs text-gray-600 line-clamp-3 leading-relaxed mb-2">
                    {src.snippet}
                  </p>
                )}
                {src.url && (
                  <a
                    href={src.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-600 hover:underline"
                  >
                    {src.pmid ? `PMID ${src.pmid}` : "View source"} ↗
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
