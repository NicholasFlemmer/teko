import { useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  Calendar,
  ClipboardList,
  Shield,
  UserRound,
  MessageSquare,
  BookOpen,
  MapPin,
  BarChart3,
  Bell,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Settings,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/contexts/AuthContext";
import { useTerm } from "@/contexts/TerminologyContext";

const ROLE_LABELS: Record<string, string> = {
  super_admin: "Super Admin",
  location_admin: "Location Admin",
  coach: "Coach",
  player: "Player",
};

/** Build initials from a full name: first letter of first + last word. */
function getInitials(fullName: string): string {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0][0].toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function AppSidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { logout, user } = useAuth();

  const fullName = user?.username ?? "";
  const initials = getInitials(fullName);
  const roleLabel = user?.role ? ROLE_LABELS[user.role] ?? user.role : "";

  // Org-customisable nav labels; the rest stay static.
  const navItems = [
    { title: "Schedule", path: "/", icon: Calendar },
    { title: useTerm("coach_plural"), path: "/coaches", icon: ClipboardList },
    { title: useTerm("team_plural"), path: "/teams", icon: Shield },
    { title: useTerm("player_plural"), path: "/players", icon: UserRound },
    { title: useTerm("location_plural"), path: "/locations", icon: MapPin },
    { title: "Reminders", path: "/reminders", icon: Bell },
    { title: "Broadcasts", path: "/broadcasts", icon: MessageSquare },
    { title: "Content", path: "/content", icon: BookOpen },
    { title: "Reports", path: "/reports", icon: BarChart3 },
    // Users management is only available to super admins.
    ...(user?.role === "super_admin"
      ? [{ title: "Users", path: "/users", icon: Users }]
      : []),
  ];

  return (
    <aside
      className={cn(
        "flex flex-col h-screen bg-card border-r border-border transition-all duration-300",
        collapsed ? "w-[72px]" : "w-[240px]"
      )}
    >
      {/* Logo */}
      <div className="flex items-center gap-3 p-4 border-b border-border">
        <div className="flex items-center justify-center w-10 h-10 rounded-full bg-gradient-to-br from-primary to-primary/80">
          <span className="text-xl font-bold text-primary-foreground">T</span>
        </div>
        {!collapsed && (
          <div className="flex flex-col">
            <span className="font-bold text-foreground">Teko</span>
            <span className="text-xs text-muted-foreground">Coach Management</span>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-4 px-3 space-y-1">
        {navItems.map((item) => {
          const isActive = location.pathname === item.path;
          return (
            <NavLink
              key={item.path}
              to={item.path}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all",
                isActive
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
              )}
            >
              <item.icon className="w-5 h-5 flex-shrink-0" />
              {!collapsed && <span>{item.title}</span>}
              {!collapsed && isActive && (
                <div className="ml-auto w-1.5 h-1.5 rounded-full bg-primary-foreground" />
              )}
            </NavLink>
          );
        })}
      </nav>

      {/* Footer actions */}
      <div className="p-3 border-t border-border space-y-1">
        {/* User profile */}
        <div
          className={cn(
            "flex flex-col items-center text-center gap-2 px-2 py-2",
            collapsed && "px-0"
          )}
        >
          <div
            className="flex items-center justify-center w-10 h-10 rounded-full text-white text-sm font-semibold flex-shrink-0"
            style={{ backgroundColor: "#0D9488" }}
            title={fullName}
          >
            {initials}
          </div>
          {!collapsed && (
            <>
              <span className="text-sm font-semibold text-foreground break-words leading-tight">
                {fullName}
              </span>
              {roleLabel && (
                <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                  {roleLabel}
                </span>
              )}
            </>
          )}
        </div>

        {/* Divider between profile and actions */}
        <div className="border-t border-border my-2" />

        <NavLink
          to="/settings"
          className={cn(
            "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium w-full transition-all",
            location.pathname === "/settings"
              ? "bg-primary text-primary-foreground shadow-sm"
              : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
          )}
        >
          <Settings className="w-5 h-5 flex-shrink-0" />
          {!collapsed && <span>Settings</span>}
        </NavLink>

        <button
          onClick={() => logout()}
          className={cn(
            "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium w-full transition-all",
            "text-destructive hover:bg-destructive-light"
          )}
        >
          <LogOut className="w-5 h-5 flex-shrink-0" />
          {!collapsed && <span>Logout</span>}
        </button>
      </div>

      {/* Collapse toggle */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="absolute top-6 -right-3 w-6 h-6 rounded-full bg-card border border-border shadow-sm flex items-center justify-center hover:bg-muted transition-colors"
      >
        {collapsed ? (
          <ChevronRight className="w-3 h-3 text-muted-foreground" />
        ) : (
          <ChevronLeft className="w-3 h-3 text-muted-foreground" />
        )}
      </button>
    </aside>
  );
}
