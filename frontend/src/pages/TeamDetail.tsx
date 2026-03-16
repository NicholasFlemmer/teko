import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  MapPin,
  Calendar,
  Users,
  GraduationCap,
  Edit,
  UserPlus,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  Save,
  X,
  Trash2
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { MainLayout } from "@/components/layout/MainLayout";
import { teamsAPI, playersAPI, coachesAPI, locationsAPI, sessionsAPI } from "@/services/api";

const PLAYER_COLORS = [
  "bg-success", "bg-warning", "bg-info", "bg-primary",
  "bg-purple-500", "bg-rose-500", "bg-teal-500", "bg-orange-500",
];

const TEAM_COLORS = [
  "bg-primary", "bg-success", "bg-info", "bg-warning",
  "bg-purple-500", "bg-rose-500", "bg-teal-500", "bg-orange-500",
];

export default function TeamDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [team, setTeam] = useState<any>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [teamPlayers, setTeamPlayers] = useState<any[]>([]);
  const [coaches, setCoaches] = useState<any[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const [locations, setLocations] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [isEditing, setIsEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [editData, setEditData] = useState({ name: "", ageGroup: "", locationId: "" });

  useEffect(() => {
    if (!id) return;

    const fetchData = async () => {
      try {
        setLoading(true);
        const [teamRes, playersRes, coachesRes, sessionsRes, locationsRes] = await Promise.all([
          teamsAPI.getOne(id),
          playersAPI.getAll({ team_id: id }),
          coachesAPI.getAll(),
          sessionsAPI.getAll(),
          locationsAPI.getAll(),
        ]);
        const t = teamRes.team;
        setTeam(t);
        setTeamPlayers(playersRes.players || []);
        setCoaches(coachesRes.coaches || []);
        setSessions(sessionsRes.sessions || []);
        setLocations(locationsRes.locations || []);
        setEditData({
          name: t.name || "",
          ageGroup: t.age_group || "",
          locationId: t.location_id || "",
        });
      } catch (err) {
        console.error("Failed to fetch team detail:", err);
        setFetchError("Failed to load team. Please check your connection and try again.");
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [id]);

  const ageGroups = ["U8", "U10", "U12", "U14", "U16", "U18", "Senior", "Mixed", "Not Applicable"];

  const handleSave = async () => {
    if (!id) return;
    try {
      setSaving(true);
      setSaveError(null);
      await teamsAPI.update(id, {
        name: editData.name,
        age_group: editData.ageGroup,
        location_id: editData.locationId || undefined,
      });
      const res = await teamsAPI.getOne(id);
      setTeam(res.team);
      setEditData({
        name: res.team.name || "",
        ageGroup: res.team.age_group || "",
        locationId: res.team.location_id || "",
      });
      setIsEditing(false);
    } catch (err: any) {
      setSaveError(err.message || "Failed to save team");
    } finally {
      setSaving(false);
    }
  };

  const handleCancelEdit = () => {
    if (team) {
      setEditData({
        name: team.name || "",
        ageGroup: team.age_group || "",
        locationId: team.location_id || "",
      });
    }
    setIsEditing(false);
  };

  const handleDelete = async () => {
    if (!id) return;
    try {
      setDeleting(true);
      await teamsAPI.delete(id);
      navigate("/teams");
    } catch (err: any) {
      setSaveError(err.message || "Failed to delete team");
      setDeleteConfirmOpen(false);
    } finally {
      setDeleting(false);
    }
  };

  if (loading) {
    return (
      <MainLayout>
        <div className="flex items-center justify-center py-24">
          <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
          <span className="ml-2 text-muted-foreground">Loading team...</span>
        </div>
      </MainLayout>
    );
  }

  if (!team) {
    return (
      <MainLayout>
        <div className="text-center py-24">
          <p className="text-muted-foreground">{fetchError || "Team not found"}</p>
          <Button variant="outline" className="mt-4" onClick={() => navigate("/teams")}>
            Back to Teams
          </Button>
        </div>
      </MainLayout>
    );
  }

  const getLocationName = (locationId: string) => {
    const loc = locations.find((l) => l.id === locationId);
    return loc?.name || "No location";
  };

  const getCoachName = (coachId: string) => {
    const coach = coaches.find((c) => c.id === coachId);
    return coach?.name || coach?.username || "Unknown";
  };

  const teamSessions = sessions.filter(
    (s) => s.team_id === id || s.team_ids?.includes(id)
  );

  const now = new Date();
  const upcomingSessions = teamSessions
    .filter((s) => new Date(s.date || s.session_date) >= now)
    .sort((a, b) => new Date(a.date || a.session_date).getTime() - new Date(b.date || b.session_date).getTime())
    .slice(0, 5);

  const recentSessions = teamSessions
    .filter((s) => new Date(s.date || s.session_date) < now)
    .sort((a, b) => new Date(b.date || b.session_date).getTime() - new Date(a.date || a.session_date).getTime())
    .slice(0, 5);

  const teamCoaches = (team.coach_ids || []).map((cid: string, idx: number) => {
    const coach = coaches.find((c) => c.id === cid);
    const coachSessions = teamSessions.filter((s) => s.coach_id === cid || (s.coach_ids && s.coach_ids.includes(cid)));
    return {
      id: cid,
      name: coach?.name || coach?.username || "Unknown",
      sessions: coachSessions.length,
    };
  });

  const totalSessions = teamSessions.length;
  const practiceCount = teamSessions.filter((s) => s.type === "Practice" || s.session_type === "Practice").length;
  const matchCount = teamSessions.filter((s) => s.type === "Match" || s.session_type === "Match").length;

  // Compute avg attendance from sessions using attended_player_ids
  const sessionsWithAttendance = teamSessions.filter((s) => s.attended_player_ids && s.attended_player_ids.length > 0);
  let avgAttendance = 0;
  if (sessionsWithAttendance.length > 0 && teamPlayers.length > 0) {
    const totalPresent = sessionsWithAttendance.reduce((sum, s) => {
      return sum + (s.attended_player_ids || []).length;
    }, 0);
    const totalPossible = sessionsWithAttendance.length * teamPlayers.length;
    avgAttendance = totalPossible > 0 ? Math.round((totalPresent / totalPossible) * 100) : 0;
  }

  const getTeamInitials = (name: string) => {
    if (!name) return "??";
    const words = name.split(" ");
    if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
    return name.substring(0, 2).toUpperCase();
  };

  const teamColor = TEAM_COLORS[0];
  const teamInitials = getTeamInitials(team.name);

  const mappedPlayers = teamPlayers.map((p, index) => ({
    id: p.id,
    name: `${p.first_name} ${p.last_name}`,
    initials: `${(p.first_name?.[0] || "").toUpperCase()}${(p.last_name?.[0] || "").toUpperCase()}`,
    color: PLAYER_COLORS[index % PLAYER_COLORS.length],
    attendanceRate: (() => {
      // Count sessions for this team where the player is in attended_player_ids
      if (teamSessions.length === 0) return 0;
      const present = teamSessions.filter((s) =>
        (s.attended_player_ids || []).includes(p.id)
      ).length;
      return Math.round((present / teamSessions.length) * 100);
    })(),
  }));

  return (
    <MainLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => navigate("/teams")}>
            <ArrowLeft className="w-5 h-5" />
          </Button>
          <div className="flex-1">
            <h1 className="page-title">{team.name}</h1>
            <p className="page-subtitle">Team Details</p>
          </div>
          {isEditing ? (
            <div className="flex items-center gap-2">
              {saveError && <span className="text-sm text-destructive mr-2">{saveError}</span>}
              <Button variant="destructive" size="sm" className="gap-2" onClick={() => setDeleteConfirmOpen(true)}>
                <Trash2 className="w-4 h-4" />
                Delete
              </Button>
              <Button variant="outline" className="gap-2" onClick={handleCancelEdit} disabled={saving}>
                <X className="w-4 h-4" />
                Cancel
              </Button>
              <Button className="gap-2" onClick={handleSave} disabled={saving}>
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                {saving ? "Saving..." : "Save Changes"}
              </Button>
            </div>
          ) : (
            <>
              <Button variant="outline" className="gap-2" onClick={() => navigate(`/players?team=${id}`)}>
                <UserPlus className="w-4 h-4" />
                Add Players
              </Button>
              <Button className="gap-2" onClick={() => setIsEditing(true)}>
                <Edit className="w-4 h-4" />
                Edit Team
              </Button>
            </>
          )}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left column - Team info */}
          <div className="space-y-4">
            {/* Team profile card */}
            <div className="bg-card rounded-xl border border-border p-6 shadow-card">
              {isEditing ? (
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="teamName">Team Name</Label>
                    <Input
                      id="teamName"
                      value={editData.name}
                      onChange={(e) => setEditData({ ...editData, name: e.target.value })}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Age Group</Label>
                    <Select value={editData.ageGroup} onValueChange={(v) => setEditData({ ...editData, ageGroup: v })}>
                      <SelectTrigger><SelectValue placeholder="Select age group" /></SelectTrigger>
                      <SelectContent>
                        {ageGroups.map((g) => (
                          <SelectItem key={g} value={g}>{g}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>Default Location</Label>
                    <Select value={editData.locationId} onValueChange={(v) => setEditData({ ...editData, locationId: v })}>
                      <SelectTrigger><SelectValue placeholder="Select a location" /></SelectTrigger>
                      <SelectContent>
                        {locations.map((loc) => (
                          <SelectItem key={loc.id} value={loc.id}>{loc.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-4 mb-6">
                    <div className={`w-16 h-16 rounded-full ${teamColor} avatar-initials text-xl`}>
                      {teamInitials}
                    </div>
                    <div>
                      <h2 className="text-xl font-semibold text-foreground">{team.name}</h2>
                      <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-primary/10 text-primary">
                        {team.age_group || "N/A"}
                      </span>
                    </div>
                  </div>

                  <div className="space-y-4">
                    <div className="flex items-center gap-3 text-muted-foreground">
                      <MapPin className="w-5 h-5 flex-shrink-0" />
                      <span className="text-foreground">{getLocationName(team.location_id)}</span>
                    </div>
                    <div className="flex items-center gap-3 text-muted-foreground">
                      <GraduationCap className="w-5 h-5 flex-shrink-0" />
                      <span className="text-foreground">{teamPlayers.length} players</span>
                    </div>
                  </div>
                </>
              )}
            </div>

            {/* Stats grid */}
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-card rounded-xl border border-border p-4 shadow-card text-center">
                <p className="text-3xl font-bold text-foreground">{totalSessions}</p>
                <p className="text-sm text-muted-foreground">Total Sessions</p>
              </div>
              <div className="bg-card rounded-xl border border-success/30 p-4 shadow-card text-center">
                <p className="text-3xl font-bold text-success">{avgAttendance}%</p>
                <p className="text-sm text-muted-foreground">Avg Attendance</p>
              </div>
              <div className="bg-card rounded-xl border border-border p-4 shadow-card text-center">
                <p className="text-3xl font-bold text-foreground">{practiceCount}</p>
                <p className="text-sm text-muted-foreground">Practices</p>
              </div>
              <div className="bg-card rounded-xl border border-info/30 p-4 shadow-card text-center">
                <p className="text-3xl font-bold text-info">{matchCount}</p>
                <p className="text-sm text-muted-foreground">Matches</p>
              </div>
            </div>

            {/* Coaches */}
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <h3 className="font-semibold text-foreground mb-3">Coaches</h3>
              <div className="space-y-3">
                {teamCoaches.length > 0 ? teamCoaches.map((coach: any) => (
                  <div key={coach.id} className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-sm">
                      <Users className="w-4 h-4 text-muted-foreground" />
                      <span className="text-foreground">{coach.name}</span>
                    </div>
                    <span className="text-xs text-muted-foreground">{coach.sessions} sessions</span>
                  </div>
                )) : (
                  <p className="text-sm text-muted-foreground">No coaches assigned</p>
                )}
              </div>
            </div>
          </div>

          {/* Middle column - Players */}
          <div className="space-y-4">
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-foreground">Players ({mappedPlayers.length})</h3>
                <Button variant="ghost" size="sm" className="text-primary" onClick={() => navigate(`/players?team=${id}`)}>
                  Manage
                </Button>
              </div>
              <div className="space-y-3">
                {mappedPlayers.map((player) => (
                  <div
                    key={player.id}
                    className="flex items-center justify-between p-3 rounded-lg bg-muted/50 cursor-pointer hover:bg-muted transition-colors"
                    onClick={() => navigate(`/players/${player.id}`)}
                  >
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded-full ${player.color} avatar-initials text-xs`}>
                        {player.initials}
                      </div>
                      <span className="text-sm font-medium text-foreground">{player.name}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`text-xs ${player.attendanceRate >= 80 ? 'text-success' : 'text-warning'}`}>
                        {player.attendanceRate}%
                      </span>
                    </div>
                  </div>
                ))}
                {mappedPlayers.length === 0 && (
                  <p className="text-sm text-muted-foreground text-center py-4">No players in this team</p>
                )}
              </div>
              {mappedPlayers.length > 0 && (
                <Button variant="outline" className="w-full mt-4" onClick={() => navigate(`/players?team=${id}`)}>
                  View All Players
                </Button>
              )}
            </div>

            {/* Recent Sessions */}
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <h3 className="font-semibold text-foreground mb-4">Recent Sessions</h3>
              <div className="space-y-3">
                {recentSessions.length > 0 ? recentSessions.map((session) => {
                  const attended = (session.attended_player_ids || []).length;
                  const absent = Math.max(0, teamPlayers.length - attended);
                  const sessionDate = session.date || session.session_date;
                  const sessionType = session.type || session.session_type || "Practice";
                  return (
                    <div
                      key={session.id}
                      className="flex items-center justify-between p-3 rounded-lg bg-muted/50"
                    >
                      <div>
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium text-foreground">
                            {new Date(sessionDate).toLocaleDateString('en-ZA', { weekday: 'short', month: 'short', day: 'numeric' })}
                          </p>
                          <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                            sessionType === 'Match' ? 'bg-info/10 text-info' : 'bg-muted text-muted-foreground'
                          }`}>
                            {sessionType}
                          </span>
                        </div>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          Coach: {getCoachName(session.coach_id)}
                        </p>
                      </div>
                      <div className="text-right">
                        <div className="flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3 text-success" />
                          <span className="text-xs text-success">{attended}</span>
                          <XCircle className="w-3 h-3 text-destructive ml-2" />
                          <span className="text-xs text-destructive">{absent}</span>
                        </div>
                      </div>
                    </div>
                  );
                }) : (
                  <p className="text-sm text-muted-foreground text-center py-4">No recent sessions</p>
                )}
              </div>
            </div>
          </div>

          {/* Right column - Upcoming sessions */}
          <div className="space-y-4">
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <h3 className="font-semibold text-foreground mb-4">Upcoming Sessions</h3>
              <div className="space-y-3">
                {upcomingSessions.length > 0 ? upcomingSessions.map((session) => {
                  const sessionDate = session.date || session.session_date;
                  const sessionType = session.type || session.session_type || "Practice";
                  const sessionTime = session.time || session.start_time || "";
                  const sessionLocation = getLocationName(session.location_id);
                  return (
                    <div
                      key={session.id}
                      className="p-3 rounded-lg bg-muted/50"
                    >
                      <div className="flex items-center justify-between mb-2">
                        <p className="text-sm font-medium text-foreground">
                          {new Date(sessionDate).toLocaleDateString('en-ZA', { weekday: 'short', month: 'short', day: 'numeric' })}
                        </p>
                        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                          sessionType === 'Match' ? 'bg-info/10 text-info' : 'bg-muted text-muted-foreground'
                        }`}>
                          {sessionType}
                        </span>
                      </div>
                      <div className="space-y-1">
                        {sessionTime && (
                          <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <Clock className="w-3 h-3" />
                            <span>{sessionTime}</span>
                          </div>
                        )}
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <Users className="w-3 h-3" />
                          <span>{getCoachName(session.coach_id)}</span>
                        </div>
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <MapPin className="w-3 h-3" />
                          <span>{sessionLocation}</span>
                        </div>
                      </div>
                    </div>
                  );
                }) : (
                  <p className="text-sm text-muted-foreground text-center py-4">No upcoming sessions</p>
                )}
              </div>
              <Button variant="outline" className="w-full mt-4" onClick={() => navigate(`/`)}>
                View Team Schedule
              </Button>
            </div>
          </div>
        </div>
      </div>

      <AlertDialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Team?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete <strong>{team.name}</strong>? This action cannot be undone. Players assigned to this team will not be deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} disabled={deleting} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
              {deleting ? "Deleting..." : "Delete Team"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </MainLayout>
  );
}
