import { useState, useRef, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  Phone,
  Calendar,
  MapPin,
  User,
  CheckCircle2,
  XCircle,
  GraduationCap,
  Users,
  Edit,
  Hash,
  FileText,
  Image,
  Download,
  Upload,
  Eye,
  Camera,
  Save,
  X,
  Mail,
  AlertCircle,
  Loader2
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { MainLayout } from "@/components/layout/MainLayout";
import { playersAPI, teamsAPI, sessionsAPI, coachesAPI, locationsAPI } from "@/services/api";

const PLAYER_COLORS = [
  "bg-success", "bg-warning", "bg-info", "bg-primary",
  "bg-purple-500", "bg-rose-500", "bg-teal-500", "bg-orange-500",
];

export default function PlayerDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [player, setPlayer] = useState<any>(null);
  const [allTeams, setAllTeams] = useState<any[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const [coaches, setCoaches] = useState<any[]>([]);
  const [allLocations, setAllLocations] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const [isEditing, setIsEditing] = useState(false);
  const [formData, setFormData] = useState({
    firstName: "",
    lastName: "",
    age: "",
    dateOfBirth: "",
    specialNotes: "",
    guardianName: "",
    guardianEmail: "",
    guardianPrimaryPhone: "",
    guardianSecondaryPhone: "",
  });
  const [selectedTeams, setSelectedTeams] = useState<string[]>([]);
  const [profilePicture, setProfilePicture] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;

    const fetchData = async () => {
      try {
        setLoading(true);
        const [playerRes, teamsRes, sessionsRes, coachesRes, locationsRes] = await Promise.all([
          playersAPI.getOne(id),
          teamsAPI.getAll(),
          sessionsAPI.getAll(),
          coachesAPI.getAll(),
          locationsAPI.getAll(),
        ]);
        const p = playerRes.player;
        setPlayer(p);
        setAllTeams(teamsRes.teams || []);
        setSessions(sessionsRes.sessions || []);
        setCoaches(coachesRes.coaches || []);
        setAllLocations(locationsRes.locations || []);

        const age = calculateAge(p.date_of_birth);
        setFormData({
          firstName: p.first_name || "",
          lastName: p.last_name || "",
          age: age,
          dateOfBirth: p.date_of_birth || "",
          specialNotes: p.special_notes || "",
          guardianName: p.guardian_name || "",
          guardianEmail: p.guardian_email || "",
          guardianPrimaryPhone: p.guardian_primary_phone || "",
          guardianSecondaryPhone: p.guardian_secondary_phone || "",
        });
        setSelectedTeams(p.team_ids || []);
      } catch (err) {
        console.error("Failed to fetch player detail:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [id]);

  const calculateAge = (dob: string) => {
    if (!dob) return "";
    const birthDate = new Date(dob);
    const today = new Date();
    let age = today.getFullYear() - birthDate.getFullYear();
    const m = today.getMonth() - birthDate.getMonth();
    if (m < 0 || (m === 0 && today.getDate() < birthDate.getDate())) {
      age--;
    }
    return String(age);
  };

  const update = (field: string, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  const handleSave = async () => {
    if (!id || !player) return;
    try {
      await playersAPI.update(id, {
        first_name: formData.firstName,
        last_name: formData.lastName,
        date_of_birth: formData.dateOfBirth,
        special_notes: formData.specialNotes,
        guardian_name: formData.guardianName,
        guardian_email: formData.guardianEmail,
        guardian_primary_phone: formData.guardianPrimaryPhone,
        guardian_secondary_phone: formData.guardianSecondaryPhone,
        team_ids: selectedTeams,
      });
      // Re-fetch to get fresh data
      const res = await playersAPI.getOne(id);
      setPlayer(res.player);
      setIsEditing(false);
    } catch (err) {
      console.error("Failed to save player:", err);
    }
  };

  const handleCancel = () => {
    if (player) {
      const age = calculateAge(player.date_of_birth);
      setFormData({
        firstName: player.first_name || "",
        lastName: player.last_name || "",
        age: age,
        dateOfBirth: player.date_of_birth || "",
        specialNotes: player.special_notes || "",
        guardianName: player.guardian_name || "",
        guardianEmail: player.guardian_email || "",
        guardianPrimaryPhone: player.guardian_primary_phone || "",
        guardianSecondaryPhone: player.guardian_secondary_phone || "",
      });
      setSelectedTeams(player.team_ids || []);
    }
    setIsEditing(false);
  };

  const handleProfilePictureChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setProfilePicture(URL.createObjectURL(file));
    }
  };

  const toggleTeam = (teamId: string) => {
    setSelectedTeams((prev) =>
      prev.includes(teamId) ? prev.filter((tid) => tid !== teamId) : [...prev, teamId]
    );
  };

  if (loading) {
    return (
      <MainLayout>
        <div className="flex items-center justify-center py-24">
          <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
          <span className="ml-2 text-muted-foreground">Loading player...</span>
        </div>
      </MainLayout>
    );
  }

  if (!player) {
    return (
      <MainLayout>
        <div className="text-center py-24">
          <p className="text-muted-foreground">Player not found</p>
          <Button variant="outline" className="mt-4" onClick={() => navigate("/players")}>
            Back to Players
          </Button>
        </div>
      </MainLayout>
    );
  }

  const fullName = `${formData.firstName} ${formData.lastName}`.trim();
  const initials = `${formData.firstName?.[0] || ""}${formData.lastName?.[0] || ""}`.toUpperCase();
  const playerColor = PLAYER_COLORS[0];

  // Player's teams
  const playerTeams = allTeams.filter((t) => (player.team_ids || []).includes(t.id));

  // Compute attendance from sessions using attended_player_ids
  // Eligible sessions = sessions where this player's team was involved
  const playerTeamIds = player.team_ids || [];
  const eligibleSessions = sessions.filter((s) =>
    playerTeamIds.includes(s.team_id)
  );
  const totalSessions = eligibleSessions.length;
  const attended = eligibleSessions.filter((s) =>
    (s.attended_player_ids || []).includes(player.id)
  ).length;
  const absent = totalSessions - attended;
  const attendanceRate = totalSessions > 0 ? Math.round((attended / totalSessions) * 100) : 0;

  // Attendance history based on eligible sessions
  const attendanceHistory = [...eligibleSessions]
    .sort((a, b) => new Date(b.date || b.session_date).getTime() - new Date(a.date || a.session_date).getTime())
    .slice(0, 10)
    .map((s) => {
      const wasPresent = (s.attended_player_ids || []).includes(player.id);
      const sessionDate = s.date || s.session_date;
      const sessionType = s.type || s.session_type || "Practice";
      const coach = coaches.find((c) => c.id === s.coach_id);
      const location = allLocations.find((l) => l.id === s.location_id);
      const team = allTeams.find((t) => t.id === s.team_id);
      return {
        id: s.id,
        date: sessionDate,
        status: wasPresent ? "present" : "absent",
        coach: coach?.name || coach?.username || "Unknown",
        location: location?.name || "Unknown",
        team: team?.name || "Unknown",
        type: sessionType,
      };
    });

  // Locations played at (only sessions where player attended)
  const attendedSessions = eligibleSessions.filter((s) =>
    (s.attended_player_ids || []).includes(player.id)
  );
  const locationCounts: Record<string, number> = {};
  attendedSessions.forEach((s) => {
    if (s.location_id) {
      locationCounts[s.location_id] = (locationCounts[s.location_id] || 0) + 1;
    }
  });
  const playerLocations = Object.entries(locationCounts).map(([locId, count]) => {
    const loc = allLocations.find((l) => l.id === locId);
    return { name: loc?.name || "Unknown", sessions: count };
  });

  // Coaches trained with (only sessions where player attended)
  const coachCounts: Record<string, number> = {};
  attendedSessions.forEach((s) => {
    if (s.coach_id) {
      coachCounts[s.coach_id] = (coachCounts[s.coach_id] || 0) + 1;
    }
  });
  const playerCoaches = Object.entries(coachCounts).map(([cid, count]) => {
    const coach = coaches.find((c) => c.id === cid);
    return { name: coach?.name || coach?.username || "Unknown", sessions: count };
  });

  return (
    <MainLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => navigate("/players")}>
            <ArrowLeft className="w-5 h-5" />
          </Button>
          <div className="flex-1">
            <h1 className="page-title">{fullName || "Player"}</h1>
            <p className="page-subtitle">Player Details</p>
          </div>
          {isEditing ? (
            <div className="flex gap-2">
              <Button variant="outline" className="gap-2" onClick={handleCancel}>
                <X className="w-4 h-4" />
                Cancel
              </Button>
              <Button className="gap-2" onClick={handleSave}>
                <Save className="w-4 h-4" />
                Save Changes
              </Button>
            </div>
          ) : (
            <Button className="gap-2" onClick={() => setIsEditing(true)}>
              <Edit className="w-4 h-4" />
              Edit Player
            </Button>
          )}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left column - Profile & Contact */}
          <div className="space-y-4">
            {/* Profile card */}
            <div className="bg-card rounded-xl border border-border p-6 shadow-card">
              {isEditing ? (
                <div className="space-y-4">
                  {/* Profile Picture Edit */}
                  <div className="flex flex-col items-center gap-2">
                    <div
                      onClick={() => fileInputRef.current?.click()}
                      className="w-20 h-20 rounded-full bg-muted border-2 border-dashed border-border flex items-center justify-center cursor-pointer hover:border-primary/50 transition-colors overflow-hidden"
                    >
                      {profilePicture ? (
                        <img src={profilePicture} alt="Profile" className="w-full h-full object-cover" />
                      ) : (
                        <Camera className="w-6 h-6 text-muted-foreground" />
                      )}
                    </div>
                    <span className="text-xs text-muted-foreground">Click to change photo</span>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={handleProfilePictureChange}
                    />
                  </div>

                  {/* Name */}
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label htmlFor="firstName" className="text-xs">First Name</Label>
                      <Input id="firstName" value={formData.firstName} onChange={(e) => update("firstName", e.target.value)} />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="lastName" className="text-xs">Last Name</Label>
                      <Input id="lastName" value={formData.lastName} onChange={(e) => update("lastName", e.target.value)} />
                    </div>
                  </div>

                  {/* Age & DOB */}
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label htmlFor="age" className="text-xs">Age</Label>
                      <Input id="age" type="number" value={formData.age} onChange={(e) => update("age", e.target.value)} />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="dob" className="text-xs">Date of Birth</Label>
                      <Input id="dob" type="date" value={formData.dateOfBirth} onChange={(e) => update("dateOfBirth", e.target.value)} />
                    </div>
                  </div>

                  {/* Special Notes */}
                  <div className="space-y-1.5">
                    <Label htmlFor="specialNotes" className="text-xs">Special Notes (allergies, medical, etc.)</Label>
                    <Textarea
                      id="specialNotes"
                      value={formData.specialNotes}
                      onChange={(e) => update("specialNotes", e.target.value)}
                      rows={3}
                    />
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-4 mb-6">
                    {profilePicture ? (
                      <img src={profilePicture} alt={fullName} className="w-16 h-16 rounded-full object-cover" />
                    ) : (
                      <div className={`w-16 h-16 rounded-full ${playerColor} avatar-initials text-xl`}>
                        {initials}
                      </div>
                    )}
                    <div>
                      <h2 className="text-xl font-semibold text-foreground">{fullName}</h2>
                      <span className="badge-student">Player</span>
                    </div>
                  </div>

                  <div className="space-y-4">
                    <div className="flex items-center gap-3 text-muted-foreground">
                      <Hash className="w-5 h-5 flex-shrink-0" />
                      <span className="text-foreground font-mono text-sm">{player.player_id || player.id}</span>
                    </div>
                    <div className="flex items-center gap-3 text-muted-foreground">
                      <GraduationCap className="w-5 h-5 flex-shrink-0" />
                      <span className="text-foreground">Age {formData.age || "N/A"}</span>
                    </div>
                    <div className="flex items-center gap-3 text-muted-foreground">
                      <Calendar className="w-5 h-5 flex-shrink-0" />
                      <span className="text-foreground">
                        DOB: {formData.dateOfBirth ? new Date(formData.dateOfBirth).toLocaleDateString('en-ZA', { year: 'numeric', month: 'long', day: 'numeric' }) : "N/A"}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-muted-foreground">
                      <Calendar className="w-5 h-5 flex-shrink-0" />
                      <span className="text-foreground">Joined {player.created_at ? new Date(player.created_at).toLocaleDateString('en-ZA', { year: 'numeric', month: 'long', day: 'numeric' }) : "N/A"}</span>
                    </div>
                  </div>
                </>
              )}
            </div>

            {/* Special Notes (view mode) */}
            {!isEditing && formData.specialNotes && (
              <div className="bg-card rounded-xl border border-border p-5 shadow-card">
                <h3 className="font-semibold text-foreground mb-3 flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 text-warning" />
                  Special Notes
                </h3>
                <p className="text-sm text-muted-foreground">{formData.specialNotes}</p>
              </div>
            )}

            {/* Teams */}
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <h3 className="font-semibold text-foreground mb-3">Teams</h3>
              {isEditing ? (
                <div className="space-y-2">
                  {allTeams.map((team) => (
                    <div
                      key={team.id}
                      className="flex items-center gap-3 p-2 rounded-lg hover:bg-muted/50 transition-colors"
                    >
                      <Checkbox
                        id={`team-${team.id}`}
                        checked={selectedTeams.includes(team.id)}
                        onCheckedChange={() => toggleTeam(team.id)}
                      />
                      <label htmlFor={`team-${team.id}`} className="flex-1 flex items-center justify-between cursor-pointer">
                        <span className="text-sm font-medium">{team.name}</span>
                        <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-primary/10 text-primary">{team.age_group || ""}</span>
                      </label>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="space-y-2">
                  {playerTeams.length > 0 ? playerTeams.map((team) => (
                    <div
                      key={team.id}
                      className="flex items-center justify-between p-2 rounded-lg bg-muted/50 cursor-pointer hover:bg-muted transition-colors"
                      onClick={() => navigate(`/teams/${team.id}`)}
                    >
                      <div className="flex items-center gap-2">
                        <Users className="w-4 h-4 text-primary" />
                        <span className="text-sm font-medium text-foreground">{team.name}</span>
                      </div>
                      <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-primary/10 text-primary">{team.age_group || ""}</span>
                    </div>
                  )) : (
                    <p className="text-sm text-muted-foreground">No teams assigned</p>
                  )}
                </div>
              )}
            </div>

            {/* Guardian contact */}
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <h3 className="font-semibold text-foreground mb-3 flex items-center gap-2">
                <User className="w-4 h-4 text-primary" />
                Guardian Contact
              </h3>
              {isEditing ? (
                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="guardianName" className="text-xs">Name</Label>
                    <Input id="guardianName" value={formData.guardianName} onChange={(e) => update("guardianName", e.target.value)} />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="guardianEmail" className="text-xs">Email</Label>
                    <Input id="guardianEmail" type="email" value={formData.guardianEmail} onChange={(e) => update("guardianEmail", e.target.value)} />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="guardianPrimaryPhone" className="text-xs">Primary Phone</Label>
                    <Input id="guardianPrimaryPhone" type="tel" value={formData.guardianPrimaryPhone} onChange={(e) => update("guardianPrimaryPhone", e.target.value)} />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="guardianSecondaryPhone" className="text-xs">Secondary Phone</Label>
                    <Input id="guardianSecondaryPhone" type="tel" value={formData.guardianSecondaryPhone} onChange={(e) => update("guardianSecondaryPhone", e.target.value)} />
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-sm">
                    <User className="w-4 h-4 text-muted-foreground" />
                    <span className="text-foreground">{formData.guardianName || "N/A"}</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm">
                    <Mail className="w-4 h-4 text-muted-foreground" />
                    <span className="text-foreground">{formData.guardianEmail || "N/A"}</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm">
                    <Phone className="w-4 h-4 text-muted-foreground" />
                    <span className="text-foreground">{formData.guardianPrimaryPhone || "N/A"}</span>
                  </div>
                  {formData.guardianSecondaryPhone && (
                    <div className="flex items-center gap-2 text-sm">
                      <Phone className="w-4 h-4 text-muted-foreground" />
                      <span className="text-foreground">{formData.guardianSecondaryPhone}</span>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Locations */}
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <h3 className="font-semibold text-foreground mb-3">Locations Played At</h3>
              <div className="space-y-3">
                {playerLocations.length > 0 ? playerLocations.map((location, index) => (
                  <div key={index} className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-sm">
                      <MapPin className="w-4 h-4 text-muted-foreground" />
                      <span className="text-foreground">{location.name}</span>
                    </div>
                    <span className="text-xs text-muted-foreground">{location.sessions} sessions</span>
                  </div>
                )) : (
                  <p className="text-sm text-muted-foreground">No location data</p>
                )}
              </div>
            </div>

            {/* Coaches */}
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <h3 className="font-semibold text-foreground mb-3">Coaches Trained With</h3>
              <div className="space-y-3">
                {playerCoaches.length > 0 ? playerCoaches.map((coach, index) => (
                  <div key={index} className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-sm">
                      <Users className="w-4 h-4 text-muted-foreground" />
                      <span className="text-foreground">{coach.name}</span>
                    </div>
                    <span className="text-xs text-muted-foreground">{coach.sessions} sessions</span>
                  </div>
                )) : (
                  <p className="text-sm text-muted-foreground">No coach data</p>
                )}
              </div>
            </div>

            {/* Documents - placeholder since backend doesn't have docs yet */}
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-foreground">Documents</h3>
                <Button variant="outline" size="sm" className="gap-1.5 h-8">
                  <Upload className="w-3.5 h-3.5" />
                  Upload
                </Button>
              </div>
              <div className="text-center py-6">
                <FileText className="w-8 h-8 text-muted-foreground/30 mx-auto mb-2" />
                <p className="text-sm text-muted-foreground">No documents uploaded</p>
              </div>
            </div>
          </div>

          {/* Middle column - Attendance stats */}
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-card rounded-xl border border-border p-4 shadow-card text-center">
                <p className="text-3xl font-bold text-foreground">{totalSessions}</p>
                <p className="text-sm text-muted-foreground">Total Sessions</p>
              </div>
              <div className="bg-card rounded-xl border border-success/30 p-4 shadow-card text-center">
                <p className="text-3xl font-bold text-success">{attendanceRate}%</p>
                <p className="text-sm text-muted-foreground">Attendance Rate</p>
              </div>
              <div className="bg-card rounded-xl border border-success/30 p-4 shadow-card text-center">
                <p className="text-3xl font-bold text-success">{attended}</p>
                <p className="text-sm text-muted-foreground">Sessions Attended</p>
              </div>
              <div className="bg-card rounded-xl border border-destructive/30 p-4 shadow-card text-center">
                <p className="text-3xl font-bold text-destructive">{absent}</p>
                <p className="text-sm text-muted-foreground">Sessions Absent</p>
              </div>
            </div>

            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <h3 className="font-semibold text-foreground mb-4">Attendance Overview</h3>
              <div className="h-32 flex items-center justify-center">
                <div className="w-full bg-muted rounded-full h-4 overflow-hidden">
                  <div
                    className="bg-success h-full rounded-full transition-all"
                    style={{ width: `${attendanceRate}%` }}
                  />
                </div>
              </div>
              <div className="flex justify-between mt-2 text-sm text-muted-foreground">
                <span>{attended} present</span>
                <span>{absent} absent</span>
              </div>
            </div>
          </div>

          {/* Right column - Attendance history */}
          <div className="space-y-4">
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <h3 className="font-semibold text-foreground mb-4">Roll Call History</h3>
              <div className="space-y-3">
                {attendanceHistory.length > 0 ? attendanceHistory.map((record) => (
                  <div key={record.id} className="p-3 rounded-lg bg-muted/50">
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-sm font-medium text-foreground">
                        {new Date(record.date).toLocaleDateString('en-ZA', { weekday: 'short', month: 'short', day: 'numeric' })}
                      </p>
                      <div className="flex items-center gap-2">
                        {record.status === "present" ? (
                          <>
                            <CheckCircle2 className="w-4 h-4 text-success" />
                            <span className="text-xs text-success">Present</span>
                          </>
                        ) : (
                          <>
                            <XCircle className="w-4 h-4 text-destructive" />
                            <span className="text-xs text-destructive">Absent</span>
                          </>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs text-muted-foreground">{record.team}</span>
                      <span className="text-xs text-muted-foreground">•</span>
                      <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                        record.type === 'Match' ? 'bg-info/10 text-info' : 'bg-muted text-muted-foreground'
                      }`}>
                        {record.type}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">
                      {record.coach} • {record.location}
                    </p>
                  </div>
                )) : (
                  <p className="text-sm text-muted-foreground text-center py-4">No attendance history</p>
                )}
              </div>
              {attendanceHistory.length > 0 && (
                <Button variant="outline" className="w-full mt-4">
                  View All History
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    </MainLayout>
  );
}
