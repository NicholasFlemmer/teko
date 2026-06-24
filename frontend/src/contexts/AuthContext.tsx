import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { authAPI } from '@/services/api';

export interface AuthUser {
  username: string;
  org_id: string | null;
  role: string | null;
}

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: AuthUser | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

/** Decode a JWT payload (no verification — purely to read claims client-side). */
function parseJwt(token: string | null): { org_id?: string | null; role?: string | null } | null {
  if (!token) return null;
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const json = decodeURIComponent(
      atob(base64)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join('')
    );
    return JSON.parse(json);
  } catch {
    return null;
  }
}

/** Build an AuthUser from a username plus the claims in the stored token. */
function buildUser(username: string): AuthUser {
  const claims = parseJwt(localStorage.getItem('token'));
  return {
    username,
    org_id: claims?.org_id ?? null,
    role: claims?.role ?? null,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(authAPI.isAuthenticated());
  const [isLoading, setIsLoading] = useState(true);
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    if (authAPI.isAuthenticated()) {
      authAPI.verify()
        .then(data => {
          setIsAuthenticated(true);
          setUser(buildUser(data.username));
        })
        .catch(() => {
          setIsAuthenticated(false);
          setUser(null);
        })
        .finally(() => setIsLoading(false));
    } else {
      setIsLoading(false);
    }
  }, []);

  const login = async (email: string, password: string) => {
    const data = await authAPI.login(email, password);
    setIsAuthenticated(true);
    setUser(buildUser(data.username));
  };

  const logout = () => {
    authAPI.logout();
    setIsAuthenticated(false);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ isAuthenticated, isLoading, user, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider');
  return context;
}
