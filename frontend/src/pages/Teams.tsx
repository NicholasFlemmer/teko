import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Search, Users, MapPin, GraduationCap, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MainLayout } from "@/components/layout/MainLayout";
import { AddTeamModal } from "@/components/teams/AddTeamModal";
import { teamsAPI, playersAPI, locationsAPI, coachesAPI } from "@/services/api";

const TEAM_COLORS = [
  "bg-primary", "bg-success", "bg-info", "bg-warning",
  "bg-purple-500", "bg-rose-500", "bg-teal-500", "bg-orange-500",
];

export default function Teams() {
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState("");
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [teams, setTeams] = useState<any[]>([]);
  const [players, setPlayers] = useState<any[]>([]);
  const [locations, setLocations] = useState<any[]>([]);
  const [coaches, setCoaches] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [teamsRes, playersRes, locationsRes, coachesRes] = await Promise.all([
        teamsAPI.getAll(),
        playersAPI.getAll(),
        locationsAPI.getAll(),
        coachesAPI.getAll(),
      ]);
      setTeams(teamsRes.teams || []);
      setPlayers(playersRes.players || []);
      setLocations(locationsRes.locations || []);
      setCoaches(coachesRes.coaches || []);
    } catch (err: any) {
      console.error("Failed to fetch teams data:", err);
      setError(err.message || "Failed to load teams. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const getLocationName = (locationId: string) => {
    const loc = locations.find((l) => l.id === locationId);
    return loc?.name || "No location";
  };

  const getCoachNames = (coachIds: string[] = []) => {
    return coachIds
      .map((cid) => {
        const coach = coaches.find((c) => c.id === cid);
        return coach?.name || coach?.username || "Unknown";
      })
      .filter(Boolean);
  };

  const getPlayerCount = (teamId: string) => {
    return players.filter((p) => (p.team_ids || []).includes(teamId)).length;
  };

  const getTeamInitials = (name: string) => {
    if (!name) return "??";
    const words = name.split(" ");
    if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
    return name.substring(0, 2).toUpperCase();
  };

  const mappedTeams = teams.map((team, index) => ({
    id: team.id,
    name: team.name,
    ageGroup: team.age_group || "",
    location: getLocationName(team.location_id),
    playerCount: getPlayerCount(team.id),
    coaches: getCoachNames(team.coach_ids),
    initials: getTeamInitials(team.name),
    color: TEAM_COLORS[index % TEAM_COLORS.length],
  }));

  const filteredTeams = mappedTeams.filter(
    (team) =>
      team.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      team.ageGroup.toLowerCase().includes(searchQuery.toLowerCase()) ||
      team.location.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <MainLayout>
      <div className="space-y-6">
        <div className="page-header">
          <div>
            <h1 className="page-title">Teams</h1>
            <p className="page-subtitle">
              Manage squads and age groups ({teams.length} total)
            </p>
          </div>
          <Button className="gap-2" onClick={() => setIsAddModalOpen(true)}>
            <Plus className="w-4 h-4" />
            Add Team
          </Button>
        </div>

        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder="Search teams by name, age group, or location..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-10 bg-card"
          />
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            <span className="ml-2 text-muted-foreground">Loading teams...</span>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <p className="text-destructive mb-2">{error}</p>
            <Button variant="outline" size="sm" onClick={fetchData}>Try Again</Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {filteredTeams.map((team) => (
              <div key={team.id} className="entity-card cursor-pointer" onClick={() => navigate(`/teams/${team.id}`)}>
                <div className="flex items-start gap-3">
                  <div
                    className={`w-10 h-10 rounded-full ${team.color} avatar-initials text-xs`}
                  >
                    {team.initials}
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-foreground">{team.name}</h3>
                    <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-primary/10 text-primary mt-1">
                      {team.ageGroup}
                    </span>
                  </div>
                </div>

                <div className="mt-4 space-y-2">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <MapPin className="w-4 h-4 flex-shrink-0" />
                    <span>{team.location}</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <GraduationCap className="w-4 h-4 flex-shrink-0" />
                    <span>{team.playerCount} players</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Users className="w-4 h-4 flex-shrink-0" />
                    <span>{team.coaches.length > 0 ? team.coaches.join(", ") : "No coaches"}</span>
                  </div>
                </div>

                <Button variant="outline" className="w-full mt-4" onClick={(e) => { e.stopPropagation(); navigate(`/teams/${team.id}`); }}>
                  View Details
                </Button>
              </div>
            ))}
          </div>
        )}

        {!loading && filteredTeams.length === 0 && (
          <div className="text-center py-12">
            <p className="text-muted-foreground">No teams found</p>
          </div>
        )}
      </div>

      <AddTeamModal open={isAddModalOpen} onOpenChange={setIsAddModalOpen} onTeamAdded={fetchData} />
    </MainLayout>
  );
}
