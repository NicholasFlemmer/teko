import { useAuth } from "@/contexts/AuthContext";

/**
 * Maps a user role to its badge label and color classes.
 * Colors use existing theme tokens (indigo / amber / green) so each
 * role is visually distinguishable at a glance.
 */
const ROLE_BADGE: Record<string, { label: string; className: string }> = {
  super_admin: {
    label: "Super admin view",
    className: "bg-primary/10 text-primary",
  },
  location_admin: {
    label: "Location admin view",
    className: "bg-warning/10 text-warning",
  },
  coach: {
    label: "Coach view",
    className: "bg-success/10 text-success",
  },
};

/**
 * Slim badge bar shown at the top of every authenticated dashboard page.
 * Purely visual — makes it clear which role's view is being displayed.
 */
export function RoleBadge() {
  const { user } = useAuth();
  const role = user?.role ?? "";
  const badge = ROLE_BADGE[role];

  if (!badge) {
    return null;
  }

  return (
    <div className="mb-4 flex">
      <span
        className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ${badge.className}`}
      >
        {badge.label}
      </span>
    </div>
  );
}
