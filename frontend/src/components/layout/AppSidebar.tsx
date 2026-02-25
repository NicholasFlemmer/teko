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
  UserCog,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/contexts/AuthContext";

const navItems = [
  { title: "Schedule", path: "/", icon: Calendar },
  { title: "Coaches", path: "/coaches", icon: ClipboardList },
  { title: "Teams", path: "/teams", icon: Shield },
  { title: "Players", path: "/players", icon: UserRound },
  { title: "Locations", path: "/locations", icon: MapPin },
  { title: "Reminders", path: "/reminders", icon: Bell },
  { title: "Broadcasts", path: "/broadcasts", icon: MessageSquare },
  { title: "Content", path: "/content", icon: BookOpen },
  { title: "Reports", path: "/reports", icon: BarChart3 },
];

export function AppSidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { logout } = useAuth();

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
        <NavLink
          to="/super-admin"
          className={cn(
            "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium w-full transition-all",
            location.pathname === "/super-admin"
              ? "bg-primary text-primary-foreground shadow-sm"
              : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
          )}
        >
          <UserCog className="w-5 h-5 flex-shrink-0" />
          {!collapsed && <span>Super Admin</span>}
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
