import { useState, useEffect, useRef } from "react";
import { MessageSquare, Send, ClipboardCheck, MapPin, Camera, Radio } from "lucide-react";
import { sseAPI } from "@/services/api";

interface ActivityEvent {
  type: string;
  coach_name: string;
  preview: string;
  timestamp: string;
}

const EVENT_CONFIG: Record<string, { icon: typeof MessageSquare; label: string; color: string }> = {
  message_received: { icon: MessageSquare, label: "Message", color: "text-blue-500" },
  response_sent: { icon: Send, label: "Reply", color: "text-emerald-500" },
  attendance: { icon: ClipboardCheck, label: "Attendance", color: "text-amber-500" },
  check_in: { icon: MapPin, label: "Check-in", color: "text-violet-500" },
  photo_uploaded: { icon: Camera, label: "Photo", color: "text-pink-500" },
};

function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

export function LiveActivityFeed() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const es = sseAPI.coachActivity((event) => {
      setEvents((prev) => [event, ...prev].slice(0, 50));
    });
    if (!es) return; // No auth token available
    esRef.current = es;

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);

    return () => {
      es.close();
      esRef.current = null;
    };
  }, []);

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <h3 className="text-sm font-semibold text-foreground">Live Activity</h3>
        <div className="flex items-center gap-1.5">
          <Radio className={`w-3 h-3 ${connected ? "text-emerald-500 animate-pulse" : "text-muted-foreground"}`} />
          <span className="text-xs text-muted-foreground">{connected ? "Live" : "Connecting..."}</span>
        </div>
      </div>

      <div className="max-h-[280px] overflow-y-auto">
        {events.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <p className="text-sm text-muted-foreground">No activity yet.</p>
            <p className="text-xs text-muted-foreground mt-1">Coach messages, check-ins, and attendance will appear here in real time.</p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {events.map((event, i) => {
              const config = EVENT_CONFIG[event.type] || EVENT_CONFIG.message_received;
              const Icon = config.icon;
              return (
                <div key={`${event.timestamp}-${i}`} className="flex items-start gap-3 px-4 py-2.5 hover:bg-muted/50 transition-colors">
                  <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${config.color}`} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-foreground truncate">{event.coach_name}</span>
                      <span className="text-xs text-muted-foreground shrink-0">{formatTime(event.timestamp)}</span>
                    </div>
                    {event.preview && (
                      <p className="text-xs text-muted-foreground truncate mt-0.5">{event.preview}</p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
