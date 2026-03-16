import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Search, MapPin, Users, Calendar, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MainLayout } from "@/components/layout/MainLayout";
import { AddLocationModal } from "@/components/locations/AddLocationModal";
import { locationsAPI, sessionsAPI, coachesAPI } from "@/services/api";

export default function Locations() {
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState("");
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [locations, setLocations] = useState<any[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const [coaches, setCoaches] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [locationsRes, sessionsRes, coachesRes] = await Promise.all([
        locationsAPI.getAll(),
        sessionsAPI.getAll(),
        coachesAPI.getAll(),
      ]);
      setLocations(locationsRes.locations || []);
      setSessions(sessionsRes.sessions || []);
      setCoaches(coachesRes.coaches || []);
    } catch (err: any) {
      console.error("Failed to fetch locations:", err);
      setError(err.message || "Failed to load locations. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const getLocationStats = (locationId: string) => {
    const locationSessions = sessions.filter((s) => s.location_id === locationId);
    const coachIds = new Set<string>();
    locationSessions.forEach((s) => {
      if (Array.isArray(s.coach_ids)) {
        s.coach_ids.forEach((cid: string) => coachIds.add(cid));
      } else if (s.coach_id) {
        coachIds.add(s.coach_id);
      }
    });
    return {
      sessions: locationSessions.length,
      coaches: coachIds.size,
    };
  };

  const mappedLocations = locations.map((loc) => {
    const stats = getLocationStats(loc.id);
    return {
      id: loc.id,
      name: loc.name,
      address: loc.address || "",
      coaches: stats.coaches,
      sessions: stats.sessions,
      radius: loc.radius ? `${loc.radius}m` : "N/A",
    };
  });

  const filteredLocations = mappedLocations.filter(
    (location) =>
      location.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      location.address.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <MainLayout>
      <div className="space-y-6">
        <div className="page-header">
          <div>
            <h1 className="page-title">Locations</h1>
            <p className="page-subtitle">
              Manage venues for coaching sessions
            </p>
          </div>
          <Button className="gap-2" onClick={() => setIsAddModalOpen(true)}>
            <Plus className="w-4 h-4" />
            Add Location
          </Button>
        </div>

        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder="Search locations..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-10 bg-card"
          />
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            <span className="ml-2 text-muted-foreground">Loading locations...</span>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <p className="text-destructive mb-2">{error}</p>
            <Button variant="outline" size="sm" onClick={fetchData}>Try Again</Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredLocations.map((location) => (
              <div key={location.id} className="entity-card cursor-pointer" onClick={() => navigate(`/locations/${location.id}`)}>
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded-lg bg-info/10 flex items-center justify-center flex-shrink-0">
                    <MapPin className="w-5 h-5 text-info" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-foreground">{location.name}</h3>
                    <p className="text-sm text-muted-foreground mt-1">{location.address}</p>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-2 mt-4">
                  <div className="text-center p-2 rounded-lg bg-muted/50">
                    <div className="flex items-center justify-center gap-1 text-xs text-muted-foreground">
                      <Users className="w-3 h-3" />
                      Coaches
                    </div>
                    <p className="font-semibold text-foreground mt-1">{location.coaches}</p>
                  </div>
                  <div className="text-center p-2 rounded-lg bg-muted/50">
                    <div className="flex items-center justify-center gap-1 text-xs text-muted-foreground">
                      <Calendar className="w-3 h-3" />
                      Sessions
                    </div>
                    <p className="font-semibold text-foreground mt-1">{location.sessions}</p>
                  </div>
                  <div className="text-center p-2 rounded-lg bg-muted/50">
                    <div className="text-xs text-muted-foreground">
                      Radius
                    </div>
                    <p className="font-semibold text-foreground mt-1">{location.radius}</p>
                  </div>
                </div>

                <Button variant="outline" className="w-full mt-4" onClick={(e) => { e.stopPropagation(); navigate(`/locations/${location.id}`); }}>
                  View Details
                </Button>
              </div>
            ))}
          </div>
        )}

        {!loading && filteredLocations.length === 0 && (
          <div className="text-center py-12">
            <MapPin className="w-12 h-12 text-muted-foreground/30 mx-auto mb-3" />
            <p className="text-muted-foreground">No locations found</p>
          </div>
        )}
      </div>

      <AddLocationModal open={isAddModalOpen} onOpenChange={setIsAddModalOpen} onLocationAdded={fetchData} />
    </MainLayout>
  );
}
