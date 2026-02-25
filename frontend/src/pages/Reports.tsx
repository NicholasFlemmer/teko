import { useState, useEffect } from "react";
import { Download, Calendar, Users, MapPin, GraduationCap, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MainLayout } from "@/components/layout/MainLayout";
import { useToast } from "@/hooks/use-toast";
import { reportsAPI } from "@/services/api";

const reportSections = [
  { id: "coach-attendance", title: "Coach Attendance", description: "Attendance by coach over time", icon: Users },
  { id: "location-attendance", title: "Location Attendance", description: "Attendance by location", icon: MapPin },
  { id: "student-rollcall", title: "Student Roll Call", description: "Student participation summaries", icon: GraduationCap },
];

function downloadCSV(data: any[], filename: string) {
  if (!data || data.length === 0) return;
  const headers = Object.keys(data[0]);
  const csvRows = [
    headers.join(","),
    ...data.map((row) =>
      headers
        .map((h) => {
          const val = row[h] ?? "";
          const str = String(val).replace(/"/g, '""');
          return `"${str}"`;
        })
        .join(",")
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

export default function Reports() {
  const { toast } = useToast();
  const [dateRange, setDateRange] = useState({
    from: "",
    to: "",
  });

  const [stats, setStats] = useState<QuickStats | null>(null);
  const [loadingStats, setLoadingStats] = useState(true);
  const [exportingId, setExportingId] = useState<string | null>(null);

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
        toast({
          title: "Error loading stats",
          description: err.message || "Failed to load quick stats.",
          variant: "destructive",
        });
      } finally {
        setLoadingStats(false);
      }
    };
    fetchStats();
  }, []);

  const handleExport = async (reportId: string) => {
    setExportingId(reportId);
    try {
      const params: { start_date?: string; end_date?: string } = {};
      if (dateRange.from) params.start_date = dateRange.from;
      if (dateRange.to) params.end_date = dateRange.to;

      let res: { success: boolean; data: any[] };
      let filename: string;

      switch (reportId) {
        case "coach-attendance":
          res = await reportsAPI.getCoachAttendance(params);
          filename = `coach-attendance-${dateRange.from || "all"}-to-${dateRange.to || "all"}.csv`;
          break;
        case "location-attendance":
          res = await reportsAPI.getLocationAttendance(params);
          filename = `location-attendance-${dateRange.from || "all"}-to-${dateRange.to || "all"}.csv`;
          break;
        case "student-rollcall":
          res = await reportsAPI.getStudentRollcall(params);
          filename = `student-rollcall-${dateRange.from || "all"}-to-${dateRange.to || "all"}.csv`;
          break;
        default:
          return;
      }

      if (res.success && res.data && res.data.length > 0) {
        downloadCSV(res.data, filename);
        toast({ title: "Export complete", description: `${res.data.length} rows exported.` });
      } else if (res.success && (!res.data || res.data.length === 0)) {
        toast({ title: "No data", description: "No data found for the selected date range." });
      }
    } catch (err: any) {
      toast({
        title: "Export failed",
        description: err.message || "Failed to export report.",
        variant: "destructive",
      });
    } finally {
      setExportingId(null);
    }
  };

  return (
    <MainLayout>
      <div className="space-y-6">
        <div className="page-header">
          <div>
            <h1 className="page-title">Reports</h1>
            <p className="page-subtitle">
              Basic accountability and funder reporting
            </p>
          </div>
        </div>

        {/* Date range filter */}
        <div className="bg-card rounded-xl border border-border p-4 shadow-card">
          <h2 className="font-semibold text-foreground mb-4">Date Range</h2>
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
            </div>
          </div>
        </div>

        {/* Report sections */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {reportSections.map((report) => (
            <div key={report.id} className="bg-card rounded-xl border border-border p-5 shadow-card">
              <div className="flex items-start gap-4">
                <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                  <report.icon className="w-6 h-6 text-primary" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="font-semibold text-foreground">{report.title}</h3>
                  <p className="text-sm text-muted-foreground mt-1">{report.description}</p>
                </div>
              </div>

              <Button
                variant="outline"
                className="w-full mt-4 gap-2"
                onClick={() => handleExport(report.id)}
                disabled={exportingId === report.id}
              >
                {exportingId === report.id ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Download className="w-4 h-4" />
                )}
                {exportingId === report.id ? "Exporting..." : "Export CSV"}
              </Button>
            </div>
          ))}
        </div>

        {/* Quick stats */}
        <div className="bg-card rounded-xl border border-border p-6 shadow-card">
          <h2 className="font-semibold text-foreground mb-4">Quick Stats (This Month)</h2>
          {loadingStats ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
              <div>
                <p className="text-3xl font-bold text-foreground">{stats?.total_sessions ?? 0}</p>
                <p className="text-sm text-muted-foreground">Total Sessions</p>
              </div>
              <div>
                <p className="text-3xl font-bold text-success">{stats?.check_in_rate != null ? `${Math.round(stats.check_in_rate)}%` : "0%"}</p>
                <p className="text-sm text-muted-foreground">Check-in Rate</p>
              </div>
              <div>
                <p className="text-3xl font-bold text-foreground">{stats?.total_students ?? 0}</p>
                <p className="text-sm text-muted-foreground">Students Attended</p>
              </div>
              <div>
                <p className="text-3xl font-bold text-foreground">{stats?.active_coaches ?? 0}</p>
                <p className="text-sm text-muted-foreground">Active Coaches</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </MainLayout>
  );
}
