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

interface TerminologyContextType {
  terminology: Terminology;
  isLoading: boolean;
  refreshTerminology: () => Promise<void>;
}

const TerminologyContext = createContext<TerminologyContextType | null>(null);

export function TerminologyProvider({ children }: { children: ReactNode }) {
  // Default English labels are shown immediately so there is no flash of empty
  // text while the real terminology loads. The org's type isn't known yet at
  // this point (it's not in the JWT), so this — and the fetch-failure case
  // below — use the sports catch-all rather than a type-based default. The
  // normal (successful fetch) path is unaffected: the backend's
  // get_org_terminology already resolves the org's type-based default and
  // returns a complete terminology object, which fully overrides this.
  const [terminology, setTerminology] = useState<Terminology>(DEFAULT_TERMINOLOGY);
  const [isLoading, setIsLoading] = useState(true);
  const { user } = useAuth();
  const orgId = user?.org_id ?? null;

  const refreshTerminology = useCallback(async () => {
    // No org (e.g. the env-fallback admin) → just use the default labels.
    if (!orgId) {
      setTerminology(DEFAULT_TERMINOLOGY);
      setIsLoading(false);
      return;
    }
    try {
      const res = await organisationsAPI.getTerminology(orgId);
      // res.terminology is already complete (backend fills any gap with the
      // org's type-based default) — this spread just guards missing keys.
      setTerminology({ ...DEFAULT_TERMINOLOGY, ...res.terminology });
    } catch {
      // Keep whatever we have (defaults) if the fetch fails.
    } finally {
      setIsLoading(false);
    }
  }, [orgId]);

  // Fetch terminology for the current org (and refetch if the org changes).
  // When there is no org the callback falls back to defaults without a request.
  useEffect(() => {
    refreshTerminology();
  }, [refreshTerminology]);

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
