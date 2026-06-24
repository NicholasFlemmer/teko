import { ReactNode } from "react";
import { useAuth } from "@/contexts/AuthContext";

interface RoleGuardProps {
  allowedRoles: string[];
  children: ReactNode;
  /** Rendered when the current user's role is not allowed. Defaults to nothing. */
  fallback?: ReactNode;
}

/**
 * Renders `children` only when the current user's role is in `allowedRoles`;
 * otherwise renders `fallback` (nothing by default).
 */
export function RoleGuard({ allowedRoles, children, fallback = null }: RoleGuardProps) {
  const { user } = useAuth();
  const role = user?.role ?? "";
  return <>{allowedRoles.includes(role) ? children : fallback}</>;
}

export default RoleGuard;
