import { createContext, ReactNode, useContext, useMemo, useState } from "react";

type AuthSessionValue = {
  repId: string | null;
  setRepId: (repId: string) => void;
  clearSession: () => void;
};

const SessionContext = createContext<AuthSessionValue | null>(null);

type Props = {
  children: ReactNode;
};

export function SessionProvider({ children }: Props) {
  const [repId, setRepIdValue] = useState<string | null>(null);

  const value = useMemo<AuthSessionValue>(
    () => ({
      repId,
      setRepId: (nextRepId: string) => setRepIdValue(nextRepId.trim()),
      clearSession: () => setRepIdValue(null)
    }),
    [repId]
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error("useSession must be used inside SessionProvider");
  }
  return context;
}
