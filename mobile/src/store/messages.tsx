import { createContext, useContext, useState, ReactNode } from "react";

export type Message = {
  id: string;
  sender: string;
  role?: string;
  content: string;
  date: string;
  isMe: boolean;
};

export type Thread = {
  id: string;
  manager: string;
  role: string;
  subject: string;
  isNew: boolean;
  messages: Message[];
  updatedAt: string;
};

type MessagesContextType = {
  threads: Thread[];
  addThread: (thread: Omit<Thread, "id" | "updatedAt" | "isNew" | "messages">, initialMessage: string) => void;
  addMessage: (threadId: string, content: string) => void;
  markRead: (threadId: string) => void;
};

const MessagesContext = createContext<MessagesContextType | null>(null);

export function MessagesProvider({ children }: { children: ReactNode }) {
  const [threads, setThreads] = useState<Thread[]>([]);

  const addThread = (
    threadParams: Omit<Thread, "id" | "updatedAt" | "isNew" | "messages">,
    initialMessage: string
  ) => {
    const newThread: Thread = {
      ...threadParams,
      id: Math.random().toString(36).slice(2, 9),
      isNew: false, // My own threads are not "new" to me
      updatedAt: new Date().toISOString(),
      messages: [
        {
          id: Math.random().toString(36).slice(2, 9),
          sender: "Me",
          content: initialMessage,
          date: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          isMe: true,
        },
      ],
    };
    setThreads((prev) => [newThread, ...prev]);
  };

  const addMessage = (threadId: string, content: string) => {
    setThreads((prev) =>
      prev.map((t) => {
        if (t.id !== threadId) return t;
        return {
          ...t,
          updatedAt: new Date().toISOString(),
          messages: [
            ...t.messages,
            {
              id: Math.random().toString(36).slice(2, 9),
              sender: "Me",
              content,
              date: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
              isMe: true,
            },
          ],
        };
      })
    );
  };

  const markRead = (threadId: string) => {
    setThreads((prev) =>
      prev.map((t) => (t.id === threadId ? { ...t, isNew: false } : t))
    );
  };

  return (
    <MessagesContext.Provider value={{ threads, addThread, addMessage, markRead }}>
      {children}
    </MessagesContext.Provider>
  );
}

export function useMessages() {
  const context = useContext(MessagesContext);
  if (!context) {
    throw new Error("useMessages must be used within a MessagesProvider");
  }
  return context;
}
