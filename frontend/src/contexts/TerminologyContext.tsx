import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  ReactNode,
} from "react";
import { organisationsAPI } from "@/services/api";
import { useAuth } from "@/contexts/AuthContext";
import { DEFAULT_TERMINOLOGY, type Terminology } from "@/types/Organisation";

// TODO: replace hardcoded org_id with value from user session
const ORG_ID = "2I8r2Hb2q7pNgjDbcG8w";

interface TerminologyContextType {
  terminology: Terminology;
  isLoading: boolean;
  refreshTerminology: () => Promise<void>;
}

const TerminologyContext = createContext<TerminologyContextType | null>(null);

export function TerminologyProvider({ children }: { children: ReactNode }) {
  // Default English labels are shown immediately so there is no flash of empty
  // text while the real terminology loads.
  const [terminology, setTerminology] = useState<Terminology>(DEFAULT_TERMINOLOGY);
  const [isLoading, setIsLoading] = useState(true);
  const { isAuthenticated } = useAuth();

  const refreshTerminology = useCallback(async () => {
    try {
      const res = await organisationsAPI.getTerminology(ORG_ID);
      // Merge over defaults so any missing key still resolves to a label.
      setTerminology({ ...DEFAULT_TERMINOLOGY, ...res.terminology });
    } catch {
      // Keep whatever we have (defaults) if the fetch fails.
    } finally {
      setIsLoading(false);
    }
  }, []);

  // The terminology endpoint requires a valid JWT, so only fetch once the user
  // is authenticated (and refetch when they log in). On public pages we keep
  // the default labels rather than triggering a 401 redirect.
  useEffect(() => {
    if (isAuthenticated) {
      refreshTerminology();
    } else {
      setTerminology(DEFAULT_TERMINOLOGY);
      setIsLoading(false);
    }
  }, [isAuthenticated, refreshTerminology]);

  return (
    <TerminologyContext.Provider value={{ terminology, isLoading, refreshTerminology }}>
      {children}
    </TerminologyContext.Provider>
  );
}

function useTerminologyContext(): TerminologyContextType {
  const ctx = useContext(TerminologyContext);
  if (!ctx) {
    throw new Error("Terminology hooks must be used within a TerminologyProvider");
  }
  return ctx;
}

/** Returns the full terminology object. */
export function useTerminology(): Terminology {
  return useTerminologyContext().terminology;
}

/** Returns a single label by key, falling back to the default English label. */
export function useTerm(key: keyof Terminology): string {
  const { terminology } = useTerminologyContext();
  return terminology[key] ?? DEFAULT_TERMINOLOGY[key];
}

/** Returns the refresh function so callers can reload terminology after a save. */
export function useRefreshTerminology(): () => Promise<void> {
  return useTerminologyContext().refreshTerminology;
}
