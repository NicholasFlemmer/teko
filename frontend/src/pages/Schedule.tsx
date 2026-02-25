import { useState, useMemo, useEffect, useCallback } from "react";
import {
  Calendar as CalendarIcon,
  Clock,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Plus,
  ChevronLeft,
  ChevronRight,
  MapPin,
  User,
  AlertCircle,
  X,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusCard } from "@/components/ui/status-card";
import { MainLayout } from "@/components/layout/MainLayout";
import { CreateSessionModal } from "@/components/schedule/CreateSessionModal";
import { SessionDetailModal } from "@/components/schedule/SessionDetailModal";
import { cn } from "@/lib/utils";
import { format, addMonths, subMonths, startOfMonth, endOfMonth, eachDayOfInterval, isSameMonth, isToday, isBefore, startOfWeek, endOfWeek } from "date-fns";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { sessionsAPI, coachesAPI, teamsAPI, locationsAPI } from "@/services/api";
import { useToast } from "@/hooks/use-toast";

interface Session {
  id: number;
  date: string;
  coach: string;
  team: string;
  location: string;
  time: string;
  endTime?: string;
  type: string;
  status: string;
  notes?: string;
}

interface CoachOption {
  id: number;
  name: string;
}

interface TeamOption {
  id: number;
  name: string;
}

interface LocationOption {
  id: number;
  name: string;
  address?: string;
}

type ViewMode = "month" | "week" | "day";

export default function Schedule() {
  const { toast } = useToast();
  const [currentDate, setCurrentDate] = useState(new Date());
  const [viewMode, setViewMode] = useState<ViewMode>("month");
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [selectedSession, setSelectedSession] = useState<Session | null>(null);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);

  // API data state
  const [sessions, setSessions] = useState<Session[]>([]);
  const [coachOptions, setCoachOptions] = useState<CoachOption[]>([]);
  const [teamOptions, setTeamOptions] = useState<TeamOption[]>([]);
  const [locationOptions, setLocationOptions] = useState<LocationOption[]>([]);
  const [loading, setLoading] = useState(true);

  // Filters
  const [filterCoach, setFilterCoach] = useState("all");
  const [filterType, setFilterType] = useState("all");
  const [filterTeam, setFilterTeam] = useState("all");
  const [filterLocation, setFilterLocation] = useState("all");

  const hasActiveFilter = filterCoach !== "all" || filterType !== "all" || filterTeam !== "all" || filterLocation !== "all";

  // Build lookup maps for coach/team/location names by ID
  const coachMap = useMemo(() => {
    const map: Record<number, string> = {};
    coachOptions.forEach((c) => { map[c.id] = c.name; });
    return map;
  }, [coachOptions]);

  const teamMap = useMemo(() => {
    const map: Record<number, string> = {};
    teamOptions.forEach((t) => { map[t.id] = t.name; });
    return map;
  }, [teamOptions]);

  const locationMap = useMemo(() => {
    const map: Record<number, string> = {};
    locationOptions.forEach((l) => { map[l.id] = l.name; });
    return map;
  }, [locationOptions]);

  // Map backend session to display format
  const mapSession = useCallback((raw: any): Session => {
    return {
      id: raw.id,
      date: raw.date,
      coach: coachMap[raw.coach_id] || `Coach #${raw.coach_id}`,
      team: teamMap[raw.team_id] || `Team #${raw.team_id}`,
      location: locationMap[raw.location_id] || raw.address || `Location #${raw.location_id}`,
      time: raw.start_time ? raw.start_time.slice(0, 5) : "",
      endTime: raw.end_time ? raw.end_time.slice(0, 5) : undefined,
      type: raw.type || "practice",
      status: raw.status || "scheduled",
      notes: raw.notes,
    };
  }, [coachMap, teamMap, locationMap]);

  // Fetch reference data (coaches, teams, locations) on mount
  useEffect(() => {
    const fetchReferenceData = async () => {
      try {
        const [coachRes, teamRes, locationRes] = await Promise.all([
          coachesAPI.getAll(),
          teamsAPI.getAll(),
          locationsAPI.getAll(),
        ]);
        if (coachRes.coaches) setCoachOptions(coachRes.coaches.map((c: any) => ({ id: c.id, name: c.name || c.username || `Coach ${c.id}` })));
        if (teamRes.teams) setTeamOptions(teamRes.teams.map((t: any) => ({ id: t.id, name: t.name })));
        if (locationRes.locations) setLocationOptions(locationRes.locations.map((l: any) => ({ id: l.id, name: l.name, address: l.address })));
      } catch (err) {
        console.error("Failed to load reference data:", err);
        toast({ title: "Error", description: "Failed to load coaches, teams, or locations.", variant: "destructive" });
      }
    };
    fetchReferenceData();
  }, [toast]);

  // Fetch sessions
  const fetchSessions = useCallback(async () => {
    setLoading(true);
    try {
      const res = await sessionsAPI.getAll();
      if (res.sessions) {
        setSessions(res.sessions);
      }
    } catch (err) {
      console.error("Failed to load sessions:", err);
      toast({ title: "Error", description: "Failed to load sessions.", variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  // Map raw sessions to display format (depends on lookup maps being populated)
  const displaySessions = useMemo(() => {
    return sessions.map(mapSession);
  }, [sessions, mapSession]);

  // Derive unique filter options from display sessions
  const coaches = useMemo(() => [...new Set(displaySessions.map((s) => s.coach))], [displaySessions]);
  const types = useMemo(() => [...new Set(displaySessions.map((s) => s.type))], [displaySessions]);
  const teams = useMemo(() => [...new Set(displaySessions.map((s) => s.team))], [displaySessions]);
  const locations = useMemo(() => [...new Set(displaySessions.map((s) => s.location))], [displaySessions]);

  // Filtered sessions
  const filteredSessions = useMemo(() => {
    return displaySessions.filter((s) => {
      if (filterCoach !== "all" && s.coach !== filterCoach) return false;
      if (filterType !== "all" && s.type !== filterType) return false;
      if (filterTeam !== "all" && s.team !== filterTeam) return false;
      if (filterLocation !== "all" && s.location !== filterLocation) return false;
      return true;
    });
  }, [displaySessions, filterCoach, filterType, filterTeam, filterLocation]);

  // Status counts from display sessions
  const statusCounts = useMemo(() => {
    const counts = { total: displaySessions.length, scheduled: 0, reminded: 0, checked_in: 0, missed: 0 };
    displaySessions.forEach((s) => {
      const status = s.status.toLowerCase().replace(/\s+/g, "_");
      if (status === "scheduled") counts.scheduled++;
      else if (status === "reminded") counts.reminded++;
      else if (status === "checked_in" || status === "checked-in" || status === "checkedin" || status === "completed") counts.checked_in++;
      else if (status === "missed" || status === "no_show" || status === "no-show") counts.missed++;
    });
    return counts;
  }, [displaySessions]);

  const clearFilters = () => {
    setFilterCoach("all");
    setFilterType("all");
    setFilterTeam("all");
    setFilterLocation("all");
  };

  const today = new Date();

  const goToPrevious = () => {
    if (viewMode === "month") setCurrentDate(subMonths(currentDate, 1));
  };

  const goToNext = () => {
    if (viewMode === "month") setCurrentDate(addMonths(currentDate, 1));
  };

  const goToToday = () => setCurrentDate(new Date());

  const monthStart = startOfMonth(currentDate);
  const monthEnd = endOfMonth(currentDate);
  const calendarStart = startOfWeek(monthStart);
  const calendarEnd = endOfWeek(monthEnd);
  const calendarDays = eachDayOfInterval({ start: calendarStart, end: calendarEnd });

  const getSessionsForDate = (date: Date) => {
    const dateStr = format(date, "yyyy-MM-dd");
    return filteredSessions.filter((s) => s.date === dateStr);
  };

  const handleSessionClick = (session: Session) => {
    setSelectedSession(session);
    setIsDetailModalOpen(true);
  };

  const handleDeleteSession = async (sessionId: number) => {
    try {
      await sessionsAPI.delete(sessionId.toString());
      toast({ title: "Session deleted", description: "The session has been removed." });
      setIsDetailModalOpen(false);
      setSelectedSession(null);
      fetchSessions();
    } catch (err) {
      console.error("Failed to delete session:", err);
      toast({ title: "Error", description: "Failed to delete session.", variant: "destructive" });
    }
  };

  // Upcoming sessions (sorted by date/time, future only)
  const upcomingSessions = useMemo(() => {
    const todayStr = format(new Date(), "yyyy-MM-dd");
    return displaySessions
      .filter((s) => s.date >= todayStr)
      .sort((a, b) => a.date.localeCompare(b.date) || a.time.localeCompare(b.time))
      .slice(0, 3);
  }, [displaySessions]);

  // Group filtered sessions by date for list view
  const groupedSessions = useMemo(() => {
    const groups: Record<string, Session[]> = {};
    const sorted = [...filteredSessions].sort((a, b) => a.date.localeCompare(b.date) || a.time.localeCompare(b.time));
    sorted.forEach((s) => {
      if (!groups[s.date]) groups[s.date] = [];
      groups[s.date].push(s);
    });
    return groups;
  }, [filteredSessions]);

  return (
    <MainLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="page-header">
          <div>
            <h1 className="page-title">Schedule</h1>
            <p className="page-subtitle">Manage your coaching sessions</p>
          </div>
          <Button onClick={() => setIsCreateModalOpen(true)} className="gap-2">
            <Plus className="w-4 h-4" />
            New Session
          </Button>
        </div>

        {/* Status Cards */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
          <StatusCard title="Total" value={statusCounts.total} icon={<CalendarIcon className="w-5 h-5" />} variant="default" />
          <StatusCard title="Scheduled" value={statusCounts.scheduled} icon={<Clock className="w-5 h-5" />} variant="info" />
          <StatusCard title="Reminded" value={statusCounts.reminded} icon={<AlertTriangle className="w-5 h-5" />} variant="warning" />
          <StatusCard title="Checked In" value={statusCounts.checked_in} icon={<CheckCircle2 className="w-5 h-5" />} variant="success" />
          <StatusCard title="Missed" value={statusCounts.missed} icon={<XCircle className="w-5 h-5" />} variant="error" />
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3">
          <Select value={filterCoach} onValueChange={setFilterCoach}>
            <SelectTrigger className="w-[160px] bg-card">
              <SelectValue placeholder="All Coaches" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Coaches</SelectItem>
              {coaches.map((c) => (
                <SelectItem key={c} value={c}>{c}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={filterType} onValueChange={setFilterType}>
            <SelectTrigger className="w-[170px] bg-card">
              <SelectValue placeholder="All Session Types" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Session Types</SelectItem>
              {types.map((t) => (
                <SelectItem key={t} value={t} className="capitalize">{t.charAt(0).toUpperCase() + t.slice(1)}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={filterTeam} onValueChange={setFilterTeam}>
            <SelectTrigger className="w-[180px] bg-card">
              <SelectValue placeholder="All Teams" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Teams</SelectItem>
              {teams.map((t) => (
                <SelectItem key={t} value={t}>{t}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={filterLocation} onValueChange={setFilterLocation}>
            <SelectTrigger className="w-[170px] bg-card">
              <SelectValue placeholder="All Locations" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Locations</SelectItem>
              {locations.map((l) => (
                <SelectItem key={l} value={l}>{l}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          {hasActiveFilter && (
            <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground" onClick={clearFilters}>
              <X className="w-3.5 h-3.5" />
              Clear filters
            </Button>
          )}
        </div>

        {/* Loading state */}
        {loading ? (
          <div className="flex items-center justify-center py-24">
            <Loader2 className="w-8 h-8 animate-spin text-primary" />
            <span className="ml-3 text-muted-foreground">Loading sessions...</span>
          </div>
        ) : (
        /* Main content area */
        <div className="flex gap-6">
          {/* Calendar or List */}
          <div className="flex-1 bg-card rounded-xl border border-border p-4 shadow-card">
            {hasActiveFilter ? (
              /* ---- LIST VIEW when filtering ---- */
              <div>
                <h2 className="text-lg font-semibold text-foreground mb-4">
                  Filtered Sessions ({filteredSessions.length})
                </h2>
                {filteredSessions.length === 0 ? (
                  <div className="text-center py-12">
                    <CalendarIcon className="w-10 h-10 text-muted-foreground/30 mx-auto mb-2" />
                    <p className="text-sm text-muted-foreground">No sessions match the selected filters</p>
                  </div>
                ) : (
                  <div className="space-y-6">
                    {Object.entries(groupedSessions).map(([date, dateSessions]) => (
                      <div key={date}>
                        <h3 className="text-sm font-semibold text-muted-foreground mb-2">
                          {format(new Date(date), "EEEE, MMMM d, yyyy")}
                        </h3>
                        <div className="space-y-2">
                          {dateSessions.map((session) => (
                            <div
                              key={session.id}
                              onClick={() => handleSessionClick(session)}
                              className="flex items-center gap-4 p-3 rounded-lg border border-border hover:bg-muted/50 transition-colors cursor-pointer"
                            >
                              {/* Type indicator */}
                              <div className={cn(
                                "w-1 h-10 rounded-full flex-shrink-0",
                                session.type === "match" ? "bg-amber-500" : "bg-emerald-500"
                              )} />

                              {/* Time */}
                              <div className="w-24 flex-shrink-0">
                                <p className="text-sm font-semibold text-foreground">{session.time}</p>
                                {session.endTime && (
                                  <p className="text-xs text-muted-foreground">to {session.endTime}</p>
                                )}
                              </div>

                              {/* Details */}
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                  <p className="text-sm font-medium text-foreground truncate">{session.team}</p>
                                  <span className={cn(
                                    "px-2 py-0.5 rounded-full text-xs font-medium capitalize",
                                    session.type === "match"
                                      ? "bg-amber-500/15 text-amber-700 dark:text-amber-400"
                                      : "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
                                  )}>
                                    {session.type}
                                  </span>
                                </div>
                                <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
                                  <span className="flex items-center gap-1">
                                    <User className="w-3 h-3" />
                                    {session.coach}
                                  </span>
                                  <span className="flex items-center gap-1">
                                    <MapPin className="w-3 h-3" />
                                    {session.location}
                                  </span>
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              /* ---- CALENDAR VIEW (no filter) ---- */
              <>
                {/* Calendar header */}
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <Button variant="outline" size="sm" onClick={goToToday}>Today</Button>
                    <Button variant="ghost" size="icon" onClick={goToPrevious}>
                      <ChevronLeft className="w-4 h-4" />
                    </Button>
                    <Button variant="ghost" size="icon" onClick={goToNext}>
                      <ChevronRight className="w-4 h-4" />
                    </Button>
                  </div>
                  <h2 className="text-lg font-semibold text-foreground">{format(currentDate, "MMMM yyyy")}</h2>
                  <div className="flex rounded-lg border border-border overflow-hidden">
                    {(["month", "week", "day"] as ViewMode[]).map((mode) => (
                      <button
                        key={mode}
                        onClick={() => setViewMode(mode)}
                        className={cn(
                          "px-4 py-1.5 text-sm font-medium capitalize transition-colors",
                          viewMode === mode
                            ? "bg-primary text-primary-foreground"
                            : "bg-card text-muted-foreground hover:bg-muted"
                        )}
                      >
                        {mode}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Calendar grid */}
                <div className="grid grid-cols-7 gap-px bg-border rounded-lg overflow-hidden">
                  {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day) => (
                    <div key={day} className="bg-muted/50 px-3 py-2 text-center text-sm font-medium text-muted-foreground">
                      {day}
                    </div>
                  ))}
                  {calendarDays.map((day) => {
                    const daySessions = getSessionsForDate(day);
                    const isPast = isBefore(day, today) && !isToday(day);
                    const isCurrentMonth = isSameMonth(day, currentDate);
                    return (
                      <div
                        key={day.toISOString()}
                        className={cn(
                          "calendar-cell",
                          isToday(day) && "calendar-cell-today",
                          isPast && "calendar-cell-past",
                          !isCurrentMonth && "opacity-40"
                        )}
                      >
                        <span className={cn("text-sm font-medium", isToday(day) ? "text-primary font-bold" : "text-foreground")}>
                          {format(day, "d")}
                        </span>
                        {daySessions.length > 0 && (
                          <div className="mt-1 space-y-1">
                            {daySessions.slice(0, 2).map((session) => (
                              <div
                                key={session.id}
                                onClick={(e) => { e.stopPropagation(); handleSessionClick(session); }}
                                className={cn(
                                  "text-xs px-1.5 py-0.5 rounded truncate cursor-pointer transition-opacity hover:opacity-80",
                                  session.type === "match"
                                    ? "bg-amber-500/20 text-amber-700 dark:text-amber-400"
                                    : "bg-emerald-500/20 text-emerald-700 dark:text-emerald-400"
                                )}
                              >
                                {session.time} {session.coach}
                              </div>
                            ))}
                            {daySessions.length > 2 && (
                              <div className="text-xs text-muted-foreground">+{daySessions.length - 2} more</div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Legend */}
                <div className="flex items-center gap-6 mt-4 text-sm text-muted-foreground">
                  <span className="font-medium">Legend:</span>
                  <div className="flex items-center gap-2">
                    <div className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
                    <span>Practice</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="w-2.5 h-2.5 rounded-full bg-amber-500" />
                    <span>Match</span>
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Right sidebar */}
          <div className="w-[300px] space-y-4">
            <div className="bg-card rounded-xl border border-border p-4 shadow-card">
              <div className="flex items-center gap-2 mb-4">
                <Clock className="w-4 h-4 text-primary" />
                <h3 className="font-semibold text-foreground">Upcoming</h3>
              </div>
              {upcomingSessions.length > 0 ? (
                <div className="space-y-3">
                  {upcomingSessions.map((session) => (
                    <div
                      key={session.id}
                      onClick={() => handleSessionClick(session)}
                      className="p-3 rounded-lg bg-muted/50 hover:bg-muted transition-colors cursor-pointer"
                    >
                      <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                        <User className="w-3.5 h-3.5 text-muted-foreground" />
                        {session.coach}
                      </div>
                      <div className="flex items-center gap-2 text-xs text-muted-foreground mt-1">
                        <MapPin className="w-3 h-3" />
                        {session.location}
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">{session.date} at {session.time}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-8">
                  <CalendarIcon className="w-10 h-10 text-muted-foreground/30 mx-auto mb-2" />
                  <p className="text-sm text-muted-foreground">No upcoming sessions</p>
                </div>
              )}
            </div>

            <div className="bg-card rounded-xl border border-border p-4 shadow-card">
              <div className="flex items-center gap-2 mb-4">
                <AlertCircle className="w-4 h-4 text-destructive" />
                <h3 className="font-semibold text-foreground">Needs Attention</h3>
              </div>
              {/* Attention items will come from API in the future */}
              <div className="text-center py-6">
                <CheckCircle2 className="w-8 h-8 text-success/30 mx-auto mb-2" />
                <p className="text-sm text-muted-foreground">All good!</p>
              </div>
            </div>
          </div>
        </div>
        )}
      </div>

      <CreateSessionModal
        open={isCreateModalOpen}
        onOpenChange={setIsCreateModalOpen}
        coaches={coachOptions}
        teams={teamOptions}
        locations={locationOptions}
        onSuccess={fetchSessions}
      />
      <SessionDetailModal
        open={isDetailModalOpen}
        onOpenChange={setIsDetailModalOpen}
        session={selectedSession}
        onDelete={handleDeleteSession}
      />
    </MainLayout>
  );
}
