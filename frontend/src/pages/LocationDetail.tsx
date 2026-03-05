import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  MapPin,
  Users,
  Calendar,
  ExternalLink,
  Navigation,
  Clock,
  Edit,
  Image as ImageIcon,
  Save,
  X,
  Loader2
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { MainLayout } from "@/components/layout/MainLayout";
import { locationsAPI, sessionsAPI, coachesAPI, playersAPI } from "@/services/api";
import { geocodeAddress, extractCoordsFromMapsUrl } from "@/lib/geocode";

const COACH_COLORS = [
  "bg-primary", "bg-success", "bg-info", "bg-warning",
  "bg-purple-500", "bg-rose-500", "bg-teal-500", "bg-orange-500",
];

export default function LocationDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [location, setLocation] = useState<any>(null);
  const [sessions, setSessions] = useState<any[]>([]);
  const [coaches, setCoaches] = useState<any[]>([]);
  const [players, setPlayers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [isEditing, setIsEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [editData, setEditData] = useState({
    name: "",
    address: "",
    googleMapsLink: "",
    notes: "",
  });

  useEffect(() => {
    if (!id) return;

    const fetchData = async () => {
      try {
        setLoading(true);
        const [locationRes, sessionsRes, coachesRes, playersRes] = await Promise.all([
          locationsAPI.getOne(id),
          sessionsAPI.getAll(),
          coachesAPI.getAll(),
          playersAPI.getAll(),
        ]);
        const loc = locationRes.location;
        setLocation(loc);
        setSessions(sessionsRes.sessions || []);
        setCoaches(coachesRes.coaches || []);
        setPlayers(playersRes.players || []);
        setEditData({
          name: loc.name || "",
          address: loc.address || "",
          googleMapsLink: loc.google_maps_link || "",
          notes: loc.notes || "",
        });
      } catch (err) {
        console.error("Failed to fetch location detail:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [id]);

  const handleSave = async () => {
    if (!id || !location) return;
    try {
      setSaving(true);
      setSaveError(null);

      // Re-geocode if address changed
      const addressChanged = editData.address !== location.address;
      const mapsLinkChanged = editData.googleMapsLink !== (location.google_maps_link || "");
      let coords: { latitude: number; longitude: number } | null = null;
      if (addressChanged || mapsLinkChanged) {
        coords =
          extractCoordsFromMapsUrl(editData.googleMapsLink) ||
          (await geocodeAddress(editData.address));
      }

      await locationsAPI.update(id, {
        name: editData.name,
        address: editData.address,
        google_maps_link: editData.googleMapsLink,
        notes: editData.notes,
        ...(coords && { latitude: coords.latitude, longitude: coords.longitude }),
      });
      const res = await locationsAPI.getOne(id);
      setLocation(res.location);
      setEditData({
        name: res.location.name || "",
        address: res.location.address || "",
        googleMapsLink: res.location.google_maps_link || "",
        notes: res.location.notes || "",
      });
      setIsEditing(false);
    } catch (err: any) {
      console.error("Failed to save location:", err);
      setSaveError(err.message || "Failed to save location");
    } finally {
      setSaving(false);
    }
  };

  const handleCancelEdit = () => {
    if (location) {
      setEditData({
        name: location.name || "",
        address: location.address || "",
        googleMapsLink: location.google_maps_link || "",
        notes: location.notes || "",
      });
    }
    setIsEditing(false);
  };

  if (loading) {
    return (
      <MainLayout>
        <div className="flex items-center justify-center py-24">
          <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
          <span className="ml-2 text-muted-foreground">Loading location...</span>
        </div>
      </MainLayout>
    );
  }

  if (!location) {
    return (
      <MainLayout>
        <div className="text-center py-24">
          <p className="text-muted-foreground">Location not found</p>
          <Button variant="outline" className="mt-4" onClick={() => navigate("/locations")}>
            Back to Locations
          </Button>
        </div>
      </MainLayout>
    );
  }

  // Sessions at this location
  const locationSessions = sessions.filter((s) => s.location_id === id);

  const now = new Date();
  const upcomingSessions = locationSessions
    .filter((s) => new Date(s.date || s.session_date) >= now)
    .sort((a, b) => new Date(a.date || a.session_date).getTime() - new Date(b.date || b.session_date).getTime())
    .slice(0, 5);

  const recentSessions = locationSessions
    .filter((s) => new Date(s.date || s.session_date) < now)
    .sort((a, b) => new Date(b.date || b.session_date).getTime() - new Date(a.date || a.session_date).getTime())
    .slice(0, 5);

  // Coaches at this location
  const coachSessionCounts: Record<string, number> = {};
  locationSessions.forEach((s) => {
    if (s.coach_id) {
      coachSessionCounts[s.coach_id] = (coachSessionCounts[s.coach_id] || 0) + 1;
    }
  });
  const locationCoaches = Object.entries(coachSessionCounts).map(([cid, count], idx) => {
    const coach = coaches.find((c) => c.id === cid);
    const name = coach?.name || coach?.username || "Unknown";
    const nameWords = name.split(" ");
    const coachInitials = nameWords.length >= 2
      ? (nameWords[0][0] + nameWords[1][0]).toUpperCase()
      : name.substring(0, 2).toUpperCase();
    return {
      id: cid,
      name,
      initials: coachInitials,
      color: COACH_COLORS[idx % COACH_COLORS.length],
      sessions: count,
    };
  });

  // Total unique students (from attended_player_ids)
  const studentIds = new Set<string>();
  locationSessions.forEach((s) => {
    if (s.attended_player_ids) {
      s.attended_player_ids.forEach((pid: string) => studentIds.add(pid));
    }
  });

  const totalSessions = locationSessions.length;
  const activeCoaches = locationCoaches.length;
  const totalStudents = studentIds.size;

  const getCoachName = (coachId: string) => {
    const coach = coaches.find((c) => c.id === coachId);
    return coach?.name || coach?.username || "Unknown";
  };

  const googleMapsLink = location.google_maps_link || editData.googleMapsLink;

  return (
    <MainLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => navigate("/locations")}>
            <ArrowLeft className="w-5 h-5" />
          </Button>
          <div className="flex-1">
            <h1 className="page-title">{location.name}</h1>
            <p className="page-subtitle">Location Details</p>
          </div>
          {googleMapsLink && (
            <Button variant="outline" className="gap-2" asChild>
              <a href={googleMapsLink} target="_blank" rel="noopener noreferrer">
                <Navigation className="w-4 h-4" />
                Open in Maps
              </a>
            </Button>
          )}
          {isEditing ? (
            <div className="flex items-center gap-2">
              {saveError && <span className="text-sm text-destructive">{saveError}</span>}
              <Button className="gap-2" onClick={handleSave} disabled={saving}>
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                {saving ? "Saving..." : "Save"}
              </Button>
              <Button variant="outline" className="gap-2" onClick={handleCancelEdit} disabled={saving}>
                <X className="w-4 h-4" />
                Cancel
              </Button>
            </div>
          ) : (
            <Button className="gap-2" onClick={() => setIsEditing(true)}>
              <Edit className="w-4 h-4" />
              Edit Location
            </Button>
          )}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left column - Location info */}
          <div className="space-y-4">
            {/* Location card */}
            <div className="bg-card rounded-xl border border-border p-6 shadow-card">
              <div className="flex items-start gap-4 mb-6">
                <div className="w-14 h-14 rounded-xl bg-info/10 flex items-center justify-center">
                  <MapPin className="w-7 h-7 text-info" />
                </div>
                <div className="flex-1">
                  {isEditing ? (
                    <div className="space-y-3">
                      <div className="space-y-1">
                        <Label className="text-xs">Name</Label>
                        <Input
                          value={editData.name}
                          onChange={(e) => setEditData({ ...editData, name: e.target.value })}
                        />
                      </div>
                      <div className="space-y-1">
                        <Label className="text-xs">Address</Label>
                        <Textarea
                          value={editData.address}
                          onChange={(e) => setEditData({ ...editData, address: e.target.value })}
                          rows={2}
                        />
                      </div>
                    </div>
                  ) : (
                    <>
                      <h2 className="text-xl font-semibold text-foreground">{location.name}</h2>
                      <p className="text-sm text-muted-foreground mt-1">{location.address}</p>
                    </>
                  )}
                </div>
              </div>

              <div className="space-y-4">
                <div className="p-3 rounded-lg bg-muted/50">
                  <span className="text-sm text-muted-foreground">Google Maps Link</span>
                  {isEditing ? (
                    <Input
                      className="mt-1 h-8 text-sm"
                      type="url"
                      placeholder="https://maps.google.com/..."
                      value={editData.googleMapsLink}
                      onChange={(e) => setEditData({ ...editData, googleMapsLink: e.target.value })}
                    />
                  ) : googleMapsLink ? (
                    <a
                      href={googleMapsLink}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm font-medium text-primary hover:underline block mt-1 truncate"
                    >
                      {googleMapsLink}
                    </a>
                  ) : (
                    <span className="text-sm text-muted-foreground block mt-1">Not set</span>
                  )}
                </div>
              </div>

              {googleMapsLink && (
                <Button variant="outline" className="w-full mt-4 gap-2" asChild>
                  <a href={googleMapsLink} target="_blank" rel="noopener noreferrer">
                    <ExternalLink className="w-4 h-4" />
                    View on Google Maps
                  </a>
                </Button>
              )}
            </div>

            {/* Embedded Google Map */}
            {location.address && (
              <div className="bg-card rounded-xl border border-border shadow-card overflow-hidden">
                <iframe
                  title="Location Map"
                  width="100%"
                  height="300"
                  style={{ border: 0 }}
                  loading="lazy"
                  referrerPolicy="no-referrer-when-downgrade"
                  src={`https://www.google.com/maps/embed/v1/place?key=${import.meta.env.VITE_GOOGLE_MAPS_API_KEY}&q=${encodeURIComponent(location.address)}`}
                  allowFullScreen
                />
              </div>
            )}

            {/* Stats */}
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-card rounded-xl border border-border p-4 shadow-card text-center">
                <p className="text-2xl font-bold text-foreground">{totalSessions}</p>
                <p className="text-xs text-muted-foreground">Sessions</p>
              </div>
              <div className="bg-card rounded-xl border border-border p-4 shadow-card text-center">
                <p className="text-2xl font-bold text-foreground">{activeCoaches}</p>
                <p className="text-xs text-muted-foreground">Coaches</p>
              </div>
              <div className="bg-card rounded-xl border border-border p-4 shadow-card text-center">
                <p className="text-2xl font-bold text-foreground">{totalStudents}</p>
                <p className="text-xs text-muted-foreground">Students</p>
              </div>
            </div>

            {/* Notes */}
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <h3 className="font-semibold text-foreground mb-3">Notes</h3>
              {isEditing ? (
                <Textarea
                  value={editData.notes}
                  onChange={(e) => setEditData({ ...editData, notes: e.target.value })}
                  rows={3}
                />
              ) : (
                <p className="text-sm text-muted-foreground">{location.notes || "No notes"}</p>
              )}
            </div>
          </div>

          {/* Middle column - Coaches & Photos */}
          <div className="space-y-4">
            {/* Coaches at location */}
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <h3 className="font-semibold text-foreground mb-4">Coaches at this Location</h3>
              <div className="space-y-3">
                {locationCoaches.length > 0 ? locationCoaches.map((coach) => (
                  <div
                    key={coach.id}
                    className="flex items-center justify-between p-3 rounded-lg bg-muted/50 hover:bg-muted transition-colors cursor-pointer"
                    onClick={() => navigate(`/coaches/${coach.id}`)}
                  >
                    <div className="flex items-center gap-3">
                      <div className={`w-9 h-9 rounded-full ${coach.color} avatar-initials text-xs`}>
                        {coach.initials}
                      </div>
                      <span className="font-medium text-foreground">{coach.name}</span>
                    </div>
                    <span className="text-sm text-muted-foreground">{coach.sessions} sessions</span>
                  </div>
                )) : (
                  <p className="text-sm text-muted-foreground text-center py-4">No coaches at this location yet</p>
                )}
              </div>
            </div>

            {/* Photos - placeholder */}
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-foreground">Photos</h3>
                <Button variant="ghost" size="sm" className="gap-1 text-xs">
                  <ImageIcon className="w-3 h-3" />
                  Add Photo
                </Button>
              </div>
              <div className="text-center py-8">
                <ImageIcon className="w-10 h-10 text-muted-foreground/30 mx-auto mb-2" />
                <p className="text-sm text-muted-foreground">No photos yet</p>
              </div>
            </div>
          </div>

          {/* Right column - Sessions */}
          <div className="space-y-4">
            {/* Upcoming sessions */}
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <h3 className="font-semibold text-foreground mb-4">Upcoming Sessions</h3>
              {upcomingSessions.length > 0 ? (
                <div className="space-y-3">
                  {upcomingSessions.map((session) => {
                    const sessionDate = session.date || session.session_date;
                    const sessionTime = session.time || session.start_time || "";
                    return (
                      <div
                        key={session.id}
                        className="p-3 rounded-lg border border-border hover:bg-muted/50 transition-colors cursor-pointer"
                      >
                        <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                          <Calendar className="w-4 h-4 text-primary" />
                          {new Date(sessionDate).toLocaleDateString('en-ZA', { weekday: 'long', month: 'short', day: 'numeric' })}
                        </div>
                        <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                          {sessionTime && (
                            <div className="flex items-center gap-1">
                              <Clock className="w-3 h-3" />
                              {sessionTime}
                            </div>
                          )}
                          <div className="flex items-center gap-1">
                            <Users className="w-3 h-3" />
                            {getCoachName(session.coach_id)}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="text-center py-8">
                  <Calendar className="w-10 h-10 text-muted-foreground/30 mx-auto mb-2" />
                  <p className="text-sm text-muted-foreground">No upcoming sessions</p>
                </div>
              )}
            </div>

            {/* Recent sessions */}
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <h3 className="font-semibold text-foreground mb-4">Recent Sessions</h3>
              <div className="space-y-3">
                {recentSessions.length > 0 ? recentSessions.map((session) => {
                  const sessionDate = session.date || session.session_date;
                  const studentCount = session.attended_player_ids?.length || 0;
                  return (
                    <div
                      key={session.id}
                      className="flex items-center justify-between p-3 rounded-lg bg-muted/50"
                    >
                      <div>
                        <p className="text-sm font-medium text-foreground">
                          {new Date(sessionDate).toLocaleDateString('en-ZA', { weekday: 'short', month: 'short', day: 'numeric' })}
                        </p>
                        <p className="text-xs text-muted-foreground">{getCoachName(session.coach_id)}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-sm font-medium text-foreground">{studentCount} students</p>
                        <p className="text-xs text-success capitalize">completed</p>
                      </div>
                    </div>
                  );
                }) : (
                  <p className="text-sm text-muted-foreground text-center py-4">No recent sessions</p>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </MainLayout>
  );
}
