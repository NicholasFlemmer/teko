import { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface StatusCardProps {
  title: string;
  value: number | string;
  icon: ReactNode;
  variant?: "default" | "success" | "warning" | "error" | "info";
  onClick?: () => void;
}

const variantStyles = {
  default: {
    border: "border-border",
    iconBg: "bg-muted",
    iconColor: "text-muted-foreground",
    titleColor: "text-muted-foreground",
  },
  success: {
    border: "border-success/30",
    iconBg: "bg-success-light",
    iconColor: "text-success",
    titleColor: "text-success",
  },
  warning: {
    border: "border-warning/30",
    iconBg: "bg-warning-light",
    iconColor: "text-warning",
    titleColor: "text-warning",
  },
  error: {
    border: "border-destructive/30",
    iconBg: "bg-destructive-light",
    iconColor: "text-destructive",
    titleColor: "text-destructive",
  },
  info: {
    border: "border-info/30",
    iconBg: "bg-info-light",
    iconColor: "text-info",
    titleColor: "text-info",
  },
};

export function StatusCard({
  title,
  value,
  icon,
  variant = "default",
  onClick,
}: StatusCardProps) {
  const styles = variantStyles[variant];

  return (
    <div
      onClick={onClick}
      className={cn(
        "bg-card rounded-xl p-4 border shadow-card hover:shadow-card-hover transition-all cursor-pointer",
        styles.border
      )}
    >
      <div className="flex items-center justify-between">
        <div>
          <p className={cn("text-xs font-medium uppercase tracking-wide", styles.titleColor)}>
            {title}
          </p>
          <p className="text-3xl font-bold text-foreground mt-1">{value}</p>
        </div>
        <div
          className={cn(
            "w-12 h-12 rounded-full flex items-center justify-center",
            styles.iconBg
          )}
        >
          <div className={styles.iconColor}>{icon}</div>
        </div>
      </div>
    </div>
  );
}
