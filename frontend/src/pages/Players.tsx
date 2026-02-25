import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Search, GraduationCap, Users, LayoutGrid, List, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MainLayout } from "@/components/layout/MainLayout";
import { AddPlayerModal } from "@/components/players/AddPlayerModal";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { playersAPI, teamsAPI } from "@/services/api";

const PLAYER_COLORS = [
  "bg-success", "bg-info", "bg-warning", "bg-primary",
  "bg-purple-500", "bg-rose-500", "bg-teal-500", "bg-orange-500",
];

export default function Players() {
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState("");
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isListView, setIsListView] = useState(false);
  const [players, setPlayers] = useState<any[]>([]);
  const [teams, setTeams] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [playersRes, teamsRes] = await Promise.all([
        playersAPI.getAll(),
        teamsAPI.getAll(),
      ]);
      setPlayers(playersRes.players || []);
      setTeams(teamsRes.teams || []);
    } catch (err) {
      console.error("Failed to fetch players:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const getTeamNames = (teamIds: string[] = []) => {
    return teamIds
      .map((tid) => {
        const team = teams.find((t) => t.id === tid);
        return team?.name || "";
      })
      .filter(Boolean);
  };

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

  const mappedPlayers = players.map((p, index) => ({
    id: p.id,
    name: `${p.first_name} ${p.last_name}`,
    initials: `${(p.first_name?.[0] || "").toUpperCase()}${(p.last_name?.[0] || "").toUpperCase()}`,
    color: PLAYER_COLORS[index % PLAYER_COLORS.length],
    teams: getTeamNames(p.team_ids),
    ageGroup: calculateAge(p.date_of_birth),
  }));

  const filteredPlayers = mappedPlayers.filter(
    (player) =>
      player.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      player.teams.some((t) => t.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  return (
    <MainLayout>
      <div className="space-y-6">
        <div className="page-header">
          <div>
            <h1 className="page-title">Players</h1>
            <p className="page-subtitle">
              Track participation and attendance ({players.length} total)
            </p>
          </div>
          <Button className="gap-2" onClick={() => setIsAddModalOpen(true)}>
            <Plus className="w-4 h-4" />
            Add Player
          </Button>
        </div>

        <div className="flex items-center gap-4">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="Search players by name or team..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10 bg-card"
            />
          </div>
          <div className="flex items-center gap-2">
            <LayoutGrid className={`w-4 h-4 ${!isListView ? 'text-primary' : 'text-muted-foreground'}`} />
            <Switch
              checked={isListView}
              onCheckedChange={setIsListView}
              aria-label="Toggle view"
            />
            <List className={`w-4 h-4 ${isListView ? 'text-primary' : 'text-muted-foreground'}`} />
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            <span className="ml-2 text-muted-foreground">Loading players...</span>
          </div>
        ) : isListView ? (
          <div className="rounded-lg border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Player</TableHead>
                  <TableHead>Teams</TableHead>
                  <TableHead>Age</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredPlayers.map((player) => (
                  <TableRow
                    key={player.id}
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() => navigate(`/players/${player.id}`)}
                  >
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <div className={`w-8 h-8 rounded-full ${player.color} avatar-initials text-xs`}>
                          {player.initials}
                        </div>
                        <div>
                          <p className="font-medium">{player.name}</p>
                          <span className="badge-student text-xs">Player</span>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{player.teams.join(", ") || "No teams"}</TableCell>
                    <TableCell className="text-muted-foreground">{player.ageGroup || "N/A"}</TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={(e) => { e.stopPropagation(); navigate(`/players/${player.id}`); }}
                      >
                        View
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {filteredPlayers.map((player) => (
              <div key={player.id} className="entity-card cursor-pointer" onClick={() => navigate(`/players/${player.id}`)}>
                <div className="flex items-start gap-3">
                  <div
                    className={`w-10 h-10 rounded-full ${player.color} avatar-initials text-xs`}
                  >
                    {player.initials}
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-foreground">{player.name}</h3>
                    <span className="badge-student mt-1 inline-block">Player</span>
                  </div>
                </div>

                <div className="mt-4 space-y-2">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Users className="w-4 h-4 flex-shrink-0" />
                    <span className="truncate">{player.teams.join(", ") || "No teams"}</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <GraduationCap className="w-4 h-4 flex-shrink-0" />
                    <span>Age: {player.ageGroup || "N/A"}</span>
                  </div>
                </div>

                <Button variant="outline" className="w-full mt-4" onClick={(e) => { e.stopPropagation(); navigate(`/players/${player.id}`); }}>
                  View Details
                </Button>
              </div>
            ))}
          </div>
        )}

        {!loading && filteredPlayers.length === 0 && (
          <div className="text-center py-12">
            <p className="text-muted-foreground">No players found</p>
          </div>
        )}
      </div>

      <AddPlayerModal open={isAddModalOpen} onOpenChange={setIsAddModalOpen} onPlayerAdded={fetchData} />
    </MainLayout>
  );
}
