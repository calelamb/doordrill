import type { FormEvent } from "react";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, Lightbulb, MessageSquareText, RefreshCw, Sparkles, X } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { sendManagerChatMessage } from "../lib/api";
import type { ChatMessage, ManagerChatResponse } from "../lib/types";

type ChatRole = "user" | "assistant";

type ChatPanelProps = {
  isOpen: boolean;
  managerId: string;
  onClose: () => void;
  onToggle: () => void;
};

type ChatUiMessage = ChatMessage & {
  error?: boolean;
  failedPrompt?: string;
  failedHistory?: Array<{ role: ChatRole; content: string }>;
};

const CHAT_STORAGE_KEY = "doordrill-manager-chat-v1";
const STARTER_QUESTIONS = [
  "Who's at risk this week?",
  "Which scenario is hardest for my team?",
  "How did Jordan improve last month?",
  "What should I focus coaching on this week?",
];

function createMessageId(): string {
  return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function getModifierKeyLabel(): string {
  if (typeof navigator === "undefined") {
    return "Ctrl+K";
  }
  return /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘K" : "Ctrl+K";
}

function getRepIdFromSources(sources: string[]): string | null {
  const repSource = sources.find((source) => source.startsWith("rep_progress:"));
  return repSource ? repSource.split(":")[1] ?? null : null;
}

function getActionTarget(response: ManagerChatResponse): string | null {
  const repId = getRepIdFromSources(response.sources_used);
  if (repId) {
    return `/manager/reps/${repId}/progress`;
  }
  if (response.intent_detected === "scenario_analysis") {
    return "/manager/scenarios";
  }
  if (response.intent_detected === "coaching_effectiveness") {
    return "/manager/coaching";
  }
  if (response.intent_detected === "risk_alerts") {
    return "/manager/risk";
  }
  if (response.intent_detected === "comparison" || response.intent_detected === "team_performance" || response.intent_detected === "general") {
    return "/manager/analytics";
  }
  return null;
}

function loadStoredMessages(): ChatUiMessage[] {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const raw = window.sessionStorage.getItem(CHAT_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw) as ChatUiMessage[];
    return Array.isArray(parsed) ? parsed.filter((item) => !item.error) : [];
  } catch {
    return [];
  }
}

export function ManagerChatPanel({ isOpen, managerId, onClose, onToggle }: ChatPanelProps) {
  const navigate = useNavigate();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [messages, setMessages] = useState<ChatUiMessage[]>(() => loadStoredMessages());
  const [inputValue, setInputValue] = useState("");
  const [loading, setLoading] = useState(false);
  const shortcutLabel = getModifierKeyLabel();

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const persisted = messages.filter((message) => !message.error);
    window.sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(persisted));
  }, [messages]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const container = scrollRef.current;
    if (!container) {
      return;
    }
    container.scrollTop = container.scrollHeight;
  }, [isOpen, loading, messages]);

  async function requestAssistantResponse(
    prompt: string,
    history: Array<{ role: ChatRole; content: string }>,
    options?: { appendUser?: boolean; removeMessageId?: string }
  ) {
    const appendUser = options?.appendUser ?? true;
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt || !managerId) {
      return;
    }

    if (options?.removeMessageId) {
      setMessages((current) => current.filter((message) => message.id !== options.removeMessageId));
    }

    if (appendUser) {
      const nextUserMessage: ChatUiMessage = {
        id: createMessageId(),
        role: "user",
        content: trimmedPrompt,
        timestamp: new Date().toISOString(),
      };
      setMessages((current) => [...current, nextUserMessage]);
      setInputValue("");
    }

    setLoading(true);
    try {
      const response = await sendManagerChatMessage(managerId, trimmedPrompt, history, 30);
      const assistantMessage: ChatUiMessage = {
        id: createMessageId(),
        role: "assistant",
        content: response.answer,
        response,
        timestamp: new Date().toISOString(),
      };
      setMessages((current) => [...current, assistantMessage]);
    } catch {
      const errorMessage: ChatUiMessage = {
        id: createMessageId(),
        role: "assistant",
        content: "Couldn't reach the AI. Try again.",
        timestamp: new Date().toISOString(),
        error: true,
        failedPrompt: trimmedPrompt,
        failedHistory: history,
      };
      setMessages((current) => [...current, errorMessage]);
    } finally {
      setLoading(false);
    }
  }

  function submitPrompt(prompt: string) {
    if (loading) {
      return;
    }

    const history = messages
      .filter((message) => !message.error)
      .map((message) => ({ role: message.role, content: message.content }));
    void requestAssistantResponse(prompt, history);
  }

  function handleRetry(message: ChatUiMessage) {
    if (!message.failedPrompt || !message.failedHistory || loading) {
      return;
    }
    void requestAssistantResponse(message.failedPrompt, message.failedHistory, {
      appendUser: false,
      removeMessageId: message.id,
    });
  }

  function resetConversation() {
    setMessages([]);
    setInputValue("");
    if (typeof window !== "undefined") {
      window.sessionStorage.removeItem(CHAT_STORAGE_KEY);
    }
  }

  function onSubmitForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submitPrompt(inputValue);
  }

  return (
    <>
      {!isOpen ? (
        <button
          type="button"
          onClick={onToggle}
          aria-label="Open manager AI chat"
          title={shortcutLabel}
          className="fixed bottom-6 right-6 z-50 inline-flex items-center gap-2 rounded-2xl bg-accent px-4 py-3 text-sm font-semibold text-white shadow-xl shadow-accent/25 transition hover:bg-accent-hover"
        >
          <Sparkles className="h-4 w-4" />
          <span>Ask AI</span>
          <span className="rounded-full bg-white/15 px-2 py-0.5 text-[11px] font-medium text-white/90">{shortcutLabel}</span>
        </button>
      ) : null}

      <AnimatePresence>
        {isOpen ? (
          <div className="fixed inset-0 z-50">
            <motion.button
              type="button"
              aria-label="Close manager AI chat"
              className="absolute inset-0 bg-ink/15"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              onClick={onClose}
            />

            <motion.aside
              initial={{ x: 420, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: 420, opacity: 0 }}
              transition={{ duration: 0.3, ease: "easeOut" }}
              className="absolute right-0 top-0 flex h-full w-full flex-col border-l border-white/30 bg-white/80 backdrop-blur-2xl shadow-2xl sm:w-[420px]"
            >
              <div className="flex items-center justify-between border-b border-white/30 px-5 py-4">
                <div>
                  <div className="flex items-center gap-2 text-sm font-semibold text-accent">
                    <Sparkles className="h-4 w-4" />
                    Ask your data
                  </div>
                  <p className="mt-1 text-xs text-muted">Plain-English answers backed by DoorDrill training data.</p>
                </div>
                <button
                  type="button"
                  onClick={onClose}
                  aria-label="Close chat panel"
                  className="rounded-full border border-white/35 bg-white/60 p-2 text-muted transition hover:bg-white hover:text-ink"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              {messages.length >= 20 ? (
                <div className="border-b border-white/25 bg-amber-100/60 px-5 py-3 text-sm text-amber-900">
                  <div className="flex items-center justify-between gap-3">
                    <span>Conversation is getting long. Start a new conversation for a cleaner answer trail.</span>
                    <button
                      type="button"
                      onClick={resetConversation}
                      aria-label="Start new conversation"
                      className="rounded-full border border-amber-300/60 bg-white/70 px-3 py-1 font-semibold transition hover:bg-white"
                    >
                      Start new
                    </button>
                  </div>
                </div>
              ) : null}

              <div ref={scrollRef} className="thin-scrollbar flex-1 space-y-4 overflow-y-auto px-5 py-5">
                {messages.length === 0 ? (
                  <div className="space-y-5">
                    <div className="rounded-[28px] border border-white/30 bg-white/45 p-5 shadow-sm">
                      <div className="flex items-center gap-3">
                        <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-accent/10 text-accent">
                          <MessageSquareText className="h-5 w-5" />
                        </div>
                        <div>
                          <h2 className="text-base font-semibold tracking-tight text-ink">Try asking...</h2>
                          <p className="text-sm text-muted">Ask about team health, reps, scenarios, risk, or coaching lift.</p>
                        </div>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      {STARTER_QUESTIONS.map((question) => (
                        <button
                          key={question}
                          type="button"
                          aria-label={`Ask starter question: ${question}`}
                          onClick={() => submitPrompt(question)}
                          className="rounded-[24px] border border-white/35 bg-white/55 p-4 text-left text-sm font-medium text-ink shadow-sm transition hover:bg-white/80"
                        >
                          {question}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}

                {messages.map((message) => {
                  const actionTarget = message.response ? getActionTarget(message.response) : null;
                  return (
                    <div key={message.id} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                      <div
                        className={
                          message.role === "user"
                            ? "max-w-[85%] rounded-2xl rounded-br-sm bg-accent px-4 py-3 text-sm leading-6 text-white shadow-lg shadow-accent/15"
                            : `max-w-[88%] rounded-2xl rounded-bl-sm border border-white/30 px-4 py-3 shadow-sm ${
                              message.error ? "bg-red-50/90 text-red-800" : "bg-white/55 text-ink"
                            }`
                        }
                      >
                        <p className="m-0 text-sm leading-6">{message.content}</p>

                        {message.role === "assistant" && message.response ? (
                          <div className="mt-4 space-y-3">
                            {message.response.key_metric ? (
                              <div className="rounded-2xl bg-accent-soft/70 px-4 py-3">
                                <div className="text-xl font-black tracking-tight text-accent">{message.response.key_metric}</div>
                                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-accent/80">
                                  {message.response.key_metric_label ?? "Key metric"}
                                </div>
                              </div>
                            ) : null}

                            {message.response.data_points.length > 0 ? (
                              <div className="grid grid-cols-2 gap-2">
                                {message.response.data_points.map((point) => (
                                  <div key={`${message.id}-${point.label}`} className="rounded-2xl border border-white/30 bg-white/70 px-3 py-2">
                                    <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">{point.label}</div>
                                    <div className="mt-1 text-sm font-semibold text-ink">{point.value}</div>
                                  </div>
                                ))}
                              </div>
                            ) : null}

                            {message.response.action_suggestion ? (
                              <button
                                type="button"
                                disabled={!actionTarget}
                                onClick={() => {
                                  if (!actionTarget) {
                                    return;
                                  }
                                  navigate(actionTarget);
                                  onClose();
                                }}
                                aria-label={actionTarget ? `Open recommended page for: ${message.response.action_suggestion}` : "AI action suggestion"}
                                className={`flex w-full items-start gap-3 rounded-2xl border px-3 py-3 text-left transition ${
                                  actionTarget
                                    ? "border-amber-300/50 bg-amber-100/70 text-amber-950 hover:bg-amber-100"
                                    : "border-amber-200/50 bg-amber-50/70 text-amber-900"
                                }`}
                              >
                                <Lightbulb className="mt-0.5 h-4 w-4 shrink-0" />
                                <span className="text-sm leading-6">{message.response.action_suggestion}</span>
                              </button>
                            ) : null}

                            {message.response.follow_up_suggestions.length > 0 ? (
                              <div className="space-y-2">
                                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Try asking</div>
                                <div className="flex flex-wrap gap-2">
                                  {message.response.follow_up_suggestions.map((suggestion) => (
                                    <button
                                      key={`${message.id}-${suggestion}`}
                                      type="button"
                                      disabled={loading}
                                      aria-label={`Ask follow-up question: ${suggestion}`}
                                      onClick={() => submitPrompt(suggestion)}
                                      className="rounded-full border border-white/35 bg-white/80 px-3 py-2 text-xs font-semibold text-ink transition hover:bg-white disabled:opacity-50"
                                    >
                                      {suggestion}
                                    </button>
                                  ))}
                                </div>
                              </div>
                            ) : null}
                          </div>
                        ) : null}

                        {message.error ? (
                          <button
                            type="button"
                            onClick={() => handleRetry(message)}
                            aria-label="Retry failed AI request"
                            className="mt-3 inline-flex items-center gap-2 rounded-full border border-red-200/70 bg-white/80 px-3 py-1.5 text-xs font-semibold text-red-800 transition hover:bg-white"
                          >
                            <RefreshCw className="h-3.5 w-3.5" />
                            Retry
                          </button>
                        ) : null}
                      </div>
                    </div>
                  );
                })}

                {loading ? (
                  <div className="flex justify-start">
                    <div className="rounded-2xl rounded-bl-sm border border-white/30 bg-white/55 px-4 py-3 shadow-sm">
                      <div className="flex items-center gap-1.5" aria-label="AI is typing">
                        {[0, 1, 2].map((index) => (
                          <motion.span
                            key={index}
                            className="h-2 w-2 rounded-full bg-accent"
                            animate={{ opacity: [0.3, 1, 0.3], y: [0, -2, 0] }}
                            transition={{ duration: 1, repeat: Number.POSITIVE_INFINITY, delay: index * 0.15 }}
                          />
                        ))}
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>

              <form onSubmit={onSubmitForm} className="border-t border-white/30 px-5 py-4">
                <div className="flex items-end gap-3 rounded-[24px] border border-white/35 bg-white/65 p-3 shadow-sm">
                  <textarea
                    value={inputValue}
                    onChange={(event) => setInputValue(event.target.value)}
                    rows={2}
                    disabled={loading}
                    aria-label="Ask anything about your team"
                    placeholder="Ask anything about your team..."
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        submitPrompt(inputValue);
                      }
                    }}
                    className="min-h-[44px] flex-1 resize-none bg-transparent text-sm text-ink outline-none placeholder:text-muted/70 disabled:opacity-60"
                  />
                  <button
                    type="submit"
                    disabled={loading || !inputValue.trim()}
                    aria-label="Send chat message"
                    className="inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-accent text-white transition hover:bg-accent-hover disabled:opacity-50"
                  >
                    <ArrowRight className="h-4 w-4" />
                  </button>
                </div>
              </form>
            </motion.aside>
          </div>
        ) : null}
      </AnimatePresence>
    </>
  );
}
