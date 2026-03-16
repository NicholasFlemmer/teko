import { useState, useEffect, useCallback } from "react";
import { Download, Calendar, Users, MapPin, GraduationCap, Loader2, RefreshCw, BarChart3 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MainLayout } from "@/components/layout/MainLayout";
import { useToast } from "@/hooks/use-toast";
import { reportsAPI } from "@/services/api";

function sanitizeCSVValue(val: unknown): string {
  let str = String(val ?? "").replace(/"/g, '""');
  // Prevent CSV injection: prefix formula-trigger characters with a single quote
  if (/^[=+\-@\t\r]/.test(str)) {
    str = "'" + str;
  }
  return `"${str}"`;
}

function downloadCSV(data: any[], filename: string) {
  if (!data || data.length === 0) return;
  const headers = Object.keys(data[0]);
  const csvRows = [
    headers.map((h) => sanitizeCSVValue(h)).join(","),
    ...data.map((row) =>
      headers.map((h) => sanitizeCSVValue(row[h])).join(",")
    ),
  ];
  const csvString = csvRows.join("\n");
  const blob = new Blob([csvString], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

interface QuickStats {
  total_sessions: number;
  check_in_rate: number;
  total_students: number;
  active_coaches: number;
}

interface CoachRow {
  coach_id: string;
  coach_name: string;
  total_sessions: number;
  checked_in: number;
}

interface LocationRow {
  location_id: string;
  location_name: string;
  total_sessions: number;
  checked_in: number;
}

interface StudentRow {
  player_id: string;
  player_name: string;
  teams: string[];
  total_sessions: number;
  attended: number;
  absent: number;
  attendance_rate: number;
}

function ProgressBar({ value, max, className = "" }: { value: number; max: number; className?: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2">
      <div className={`flex-1 h-2 rounded-full bg-muted overflow-hidden ${className}`}>
        <div
          className={`h-full rounded-full transition-all ${
            pct >= 80 ? "bg-emerald-500" : pct >= 50 ? "bg-amber-500" : "bg-red-500"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-muted-foreground w-10 text-right">{pct}%</span>
    </div>
  );
}

export default function Reports() {
  const { toast } = useToast();
  const [dateRange, setDateRange] = useState({ from: "", to: "" });

  const [stats, setStats] = useState<QuickStats | null>(null);
  const [loadingStats, setLoadingStats] = useState(true);

  const [coachData, setCoachData] = useState<CoachRow[]>([]);
  const [locationData, setLocationData] = useState<LocationRow[]>([]);
  const [studentData, setStudentData] = useState<StudentRow[]>([]);
  const [loadingReports, setLoadingReports] = useState(false);
  const [exportingId, setExportingId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"coaches" | "locations" | "students">("coaches");

  // Fetch quick stats on mount
  useEffect(() => {
    const fetchStats = async () => {
      setLoadingStats(true);
      try {
        const res = await reportsAPI.getStats();
        if (res.success && res.stats) {
          setStats(res.stats);
        }
      } catch (err: any) {
        toast({ title: "Error loading stats", description: err.message || "Failed to load quick stats.", variant: "destructive" });
      } finally {
        setLoadingStats(false);
      }
    };
    fetchStats();
  }, []);

  const fetchReports = useCallback(async () => {
    setLoadingReports(true);
    const params: { start_date?: string; end_date?: string } = {};
    if (dateRange.from) params.start_date = dateRange.from;
    if (dateRange.to) params.end_date = dateRange.to;

    try {
      const [coachRes, locationRes, studentRes] = await Promise.all([
        reportsAPI.getCoachAttendance(params),
        reportsAPI.getLocationAttendance(params),
        reportsAPI.getStudentRollcall(params),
      ]);
      if (coachRes.success) setCoachData(coachRes.data || []);
      if (locationRes.success) setLocationData(locationRes.data || []);
      if (studentRes.success) setStudentData(studentRes.data || []);
    } catch (err: any) {
      toast({ title: "Error loading reports", description: err.message || "Failed to load report data.", variant: "destructive" });
    } finally {
      setLoadingReports(false);
    }
  }, [dateRange, toast]);

  // Load reports on mount and when date range changes
  useEffect(() => {
    fetchReports();
  }, [fetchReports]);

  const handleExport = (reportId: string) => {
    setExportingId(reportId);
    const suffix = `${dateRange.from || "all"}-to-${dateRange.to || "all"}`;
    try {
      switch (reportId) {
        case "coaches":
          downloadCSV(coachData, `coach-attendance-${suffix}.csv`);
          break;
        case "locations":
          downloadCSV(locationData, `location-attendance-${suffix}.csv`);
          break;
        case "students":
          downloadCSV(studentData.map(s => ({ ...s, teams: s.teams?.join("; ") })), `student-rollcall-${suffix}.csv`);
          break;
      }
      toast({ title: "Export complete" });
    } catch {
      toast({ title: "Export failed", variant: "destructive" });
    } finally {
      setExportingId(null);
    }
  };

  const tabs = [
    { id: "coaches" as const, label: "Coach Attendance", icon: Users, count: coachData.length },
    { id: "locations" as const, label: "Location Attendance", icon: MapPin, count: locationData.length },
    { id: "students" as const, label: "Student Roll Call", icon: GraduationCap, count: studentData.length },
  ];

  return (
    <MainLayout>
      <div className="space-y-6">
        <div className="page-header">
          <div>
            <h1 className="page-title">Reports</h1>
            <p className="page-subtitle">Attendance tracking and accountability reporting</p>
          </div>
        </div>

        {/* Quick Stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: "Total Sessions", value: stats?.total_sessions ?? 0, icon: Calendar },
            { label: "Check-in Rate", value: stats?.check_in_rate != null ? `${Math.round(stats.check_in_rate)}%` : "0%", icon: BarChart3 },
            { label: "Students Attended", value: stats?.total_students ?? 0, icon: GraduationCap },
            { label: "Active Coaches", value: stats?.active_coaches ?? 0, icon: Users },
          ].map((stat) => (
            <div key={stat.label} className="bg-card rounded-xl border border-border p-4 shadow-card">
              {loadingStats ? (
                <div className="flex items-center justify-center py-4">
                  <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-2 text-muted-foreground mb-1">
                    <stat.icon className="w-4 h-4" />
                    <span className="text-xs">{stat.label}</span>
                  </div>
                  <p className="text-2xl font-bold text-foreground">{stat.value}</p>
                </>
              )}
            </div>
          ))}
        </div>

        {/* Date Range + Actions */}
        <div className="bg-card rounded-xl border border-border p-4 shadow-card">
          <div className="flex flex-wrap items-end gap-4">
            <div className="space-y-2">
              <Label htmlFor="from">From</Label>
              <Input
                id="from"
                type="date"
                value={dateRange.from}
                onChange={(e) => setDateRange({ ...dateRange, from: e.target.value })}
                className="w-[180px]"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="to">To</Label>
              <Input
                id="to"
                type="date"
                value={dateRange.to}
                onChange={(e) => setDateRange({ ...dateRange, to: e.target.value })}
                className="w-[180px]"
              />
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  const today = new Date();
                  const weekAgo = new Date(today);
                  weekAgo.setDate(today.getDate() - 7);
                  setDateRange({
                    from: weekAgo.toISOString().split("T")[0],
                    to: today.toISOString().split("T")[0],
                  });
                }}
              >
                Last 7 days
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  const today = new Date();
                  const monthAgo = new Date(today);
                  monthAgo.setMonth(today.getMonth() - 1);
                  setDateRange({
                    from: monthAgo.toISOString().split("T")[0],
                    to: today.toISOString().split("T")[0],
                  });
                }}
              >
                Last 30 days
              </Button>
              <Button variant="outline" size="sm" onClick={fetchReports} disabled={loadingReports}>
                {loadingReports ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
              </Button>
            </div>
          </div>
        </div>

        {/* Tabbed Reports */}
        <div className="bg-card rounded-xl border border-border shadow-card overflow-hidden">
          {/* Tab Header */}
          <div className="flex border-b border-border">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors border-b-2 ${
                  activeTab === tab.id
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                <tab.icon className="w-4 h-4" />
                {tab.label}
                <span className="text-xs bg-muted rounded-full px-1.5 py-0.5">{tab.count}</span>
              </button>
            ))}
            <div className="ml-auto flex items-center px-3">
              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={() => handleExport(activeTab)}
                disabled={exportingId === activeTab}
              >
                {exportingId === activeTab ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
                Export CSV
              </Button>
            </div>
          </div>

          {/* Tab Content */}
          <div className="p-4">
            {loadingReports ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <>
                {/* Coach Attendance */}
                {activeTab === "coaches" && (
                  coachData.length === 0 ? (
                    <div className="text-center py-12 text-muted-foreground">
                      <Users className="w-10 h-10 mx-auto mb-2 opacity-30" />
                      <p>No coach attendance data for this period</p>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {coachData
                        .sort((a, b) => b.total_sessions - a.total_sessions)
                        .map((coach) => (
                          <div key={coach.coach_id} className="flex items-center gap-4 p-3 rounded-lg hover:bg-muted/50 transition-colors">
                            <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                              <span className="text-xs font-bold text-primary">
                                {coach.coach_name?.split(" ").map(n => n[0]).join("").slice(0, 2).toUpperCase() || "?"}
                              </span>
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="font-medium text-foreground text-sm truncate">{coach.coach_name}</p>
                              <p className="text-xs text-muted-foreground">
                                {coach.checked_in}/{coach.total_sessions} sessions checked in
                              </p>
                            </div>
                            <div className="w-32">
                              <ProgressBar value={coach.checked_in} max={coach.total_sessions} />
                            </div>
                          </div>
                        ))}
                    </div>
                  )
                )}

                {/* Location Attendance */}
                {activeTab === "locations" && (
                  locationData.length === 0 ? (
                    <div className="text-center py-12 text-muted-foreground">
                      <MapPin className="w-10 h-10 mx-auto mb-2 opacity-30" />
                      <p>No location attendance data for this period</p>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {locationData
                        .sort((a, b) => b.total_sessions - a.total_sessions)
                        .map((loc) => (
                          <div key={loc.location_id} className="flex items-center gap-4 p-3 rounded-lg hover:bg-muted/50 transition-colors">
                            <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                              <MapPin className="w-4 h-4 text-primary" />
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="font-medium text-foreground text-sm truncate">{loc.location_name}</p>
                              <p className="text-xs text-muted-foreground">
                                {loc.checked_in}/{loc.total_sessions} sessions with check-in
                              </p>
                            </div>
                            <div className="w-32">
                              <ProgressBar value={loc.checked_in} max={loc.total_sessions} />
                            </div>
                          </div>
                        ))}
                    </div>
                  )
                )}

                {/* Student Roll Call */}
                {activeTab === "students" && (
                  studentData.length === 0 ? (
                    <div className="text-center py-12 text-muted-foreground">
                      <GraduationCap className="w-10 h-10 mx-auto mb-2 opacity-30" />
                      <p>No student roll call data for this period</p>
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-border text-left">
                            <th className="py-2 px-3 font-medium text-muted-foreground">Player</th>
                            <th className="py-2 px-3 font-medium text-muted-foreground">Team(s)</th>
                            <th className="py-2 px-3 font-medium text-muted-foreground text-center">Attended</th>
                            <th className="py-2 px-3 font-medium text-muted-foreground text-center">Absent</th>
                            <th className="py-2 px-3 font-medium text-muted-foreground w-40">Rate</th>
                          </tr>
                        </thead>
                        <tbody>
                          {studentData
                            .sort((a, b) => b.attendance_rate - a.attendance_rate)
                            .map((student) => (
                              <tr key={student.player_id} className="border-b border-border/50 hover:bg-muted/30 transition-colors">
                                <td className="py-2 px-3 font-medium text-foreground">{student.player_name || "Unknown"}</td>
                                <td className="py-2 px-3 text-muted-foreground text-xs">{student.teams?.join(", ") || "-"}</td>
                                <td className="py-2 px-3 text-center text-emerald-600 font-medium">{student.attended}</td>
                                <td className="py-2 px-3 text-center text-red-500 font-medium">{student.absent}</td>
                                <td className="py-2 px-3">
                                  <ProgressBar value={student.attended} max={student.total_sessions} />
                                </td>
                              </tr>
                            ))}
                        </tbody>
                      </table>
                    </div>
                  )
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </MainLayout>
  );
}
