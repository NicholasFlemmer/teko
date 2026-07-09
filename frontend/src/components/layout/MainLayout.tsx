import { ReactNode } from "react";
import { AppSidebar } from "./AppSidebar";
import { RoleBadge } from "./RoleBadge";

interface MainLayoutProps {
  children: ReactNode;
}

export function MainLayout({ children }: MainLayoutProps) {
  return (
    <div className="flex h-screen w-full bg-background">
      <div className="relative sticky top-0 h-screen">
        <AppSidebar />
      </div>
      <main className="flex-1 overflow-auto p-6">
        <RoleBadge />
        {children}
      </main>
    </div>
  );
}
