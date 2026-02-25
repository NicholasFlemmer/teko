import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Search, Mail, Phone, Edit, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MainLayout } from "@/components/layout/MainLayout";
import { AddCoachModal } from "@/components/coaches/AddCoachModal";
import { coachesAPI } from "@/services/api";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

const AVATAR_COLORS = [
  "bg-primary",
  "bg-success",
  "bg-info",
  "bg-warning",
  "bg-destructive",
  "bg-primary",
  "bg-success",
  "bg-info",
];

interface CoachDisplay {
  id: string;
  name: string;
  email: string;
  phone: string;
  initials: string;
  color: string;
}

export default function Coaches() {
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState("");
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [deleteCoachId, setDeleteCoachId] = useState<string | null>(null);
  const [coaches, setCoaches] = useState<CoachDisplay[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const fetchCoaches = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await coachesAPI.getAll();
      if (response.success && response.coaches) {
        const mapped: CoachDisplay[] = response.coaches.map((c: any, index: number) => {
          const firstName = c.first_name || "";
          const lastName = c.last_name || "";
          const name = c.name || `${firstName} ${lastName}`.trim();
          const initials = `${firstName.charAt(0)}${lastName.charAt(0)}`.toUpperCase() || name.charAt(0).toUpperCase();
          return {
            id: String(c.id),
            name,
            email: c.email || "",
            phone: c.phone_number || "",
            initials,
            color: AVATAR_COLORS[index % AVATAR_COLORS.length],
          };
        });
        setCoaches(mapped);
      }
    } catch (err: any) {
      setError(err.message || "Failed to load coaches");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCoaches();
  }, [fetchCoaches]);

  const filteredCoaches = coaches.filter(
    (coach) =>
      coach.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      coach.email.toLowerCase().includes(searchQuery.toLowerCase()) ||
      coach.phone.includes(searchQuery)
  );

  const handleDelete = async () => {
    if (!deleteCoachId) return;
    try {
      setDeleting(true);
      await coachesAPI.delete(deleteCoachId);
      setDeleteCoachId(null);
      await fetchCoaches();
    } catch (err: any) {
      console.error("Failed to delete coach:", err);
    } finally {
      setDeleting(false);
    }
  };

  const handleCoachAdded = () => {
    fetchCoaches();
  };

  return (
    <MainLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="page-header">
          <div>
            <h1 className="page-title">Coaches</h1>
            <p className="page-subtitle">
              Manage your coaching team ({coaches.length} total)
            </p>
          </div>
          <Button onClick={() => setIsAddModalOpen(true)} className="gap-2">
            <Plus className="w-4 h-4" />
            Add Coach
          </Button>
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder="Search coaches by name, email, or phone..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-10 bg-card"
          />
        </div>

        {/* Loading state */}
        {loading && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[1, 2, 3].map((i) => (
              <div key={i} className="entity-card animate-pulse">
                <div className="flex items-start gap-4">
                  <div className="w-12 h-12 rounded-full bg-muted" />
                  <div className="flex-1 space-y-3">
                    <div className="h-4 bg-muted rounded w-3/4" />
                    <div className="h-3 bg-muted rounded w-1/2" />
                    <div className="h-3 bg-muted rounded w-full mt-4" />
                    <div className="h-3 bg-muted rounded w-2/3" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Error state */}
        {error && !loading && (
          <div className="text-center py-12">
            <p className="text-destructive mb-4">{error}</p>
            <Button variant="outline" onClick={fetchCoaches}>
              Try Again
            </Button>
          </div>
        )}

        {/* Coach cards grid */}
        {!loading && !error && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredCoaches.map((coach) => (
              <div key={coach.id} className="entity-card cursor-pointer" onClick={() => navigate(`/coaches/${coach.id}`)}>
                <div className="flex items-start gap-4">
                  {/* Avatar */}
                  <div
                    className={`w-12 h-12 rounded-full ${coach.color} avatar-initials text-sm`}
                  >
                    {coach.initials}
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-foreground">{coach.name}</h3>
                    <span className="badge-coach mt-1 inline-block">Coach</span>

                    <div className="mt-4 space-y-2">
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Mail className="w-4 h-4 flex-shrink-0" />
                        <span className="truncate">{coach.email}</span>
                      </div>
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Phone className="w-4 h-4 flex-shrink-0" />
                        <span>{coach.phone}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="flex gap-2 mt-5">
                  <Button variant="outline" className="flex-1 gap-2" onClick={(e) => { e.stopPropagation(); navigate(`/coaches/${coach.id}`); }}>
                    <Edit className="w-4 h-4" />
                    Edit
                  </Button>
                  <Button
                    variant="outline"
                    size="icon"
                    className="text-destructive hover:text-destructive hover:bg-destructive-light"
                    onClick={(e) => { e.stopPropagation(); setDeleteCoachId(coach.id); }}
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}

        {!loading && !error && filteredCoaches.length === 0 && (
          <div className="text-center py-12">
            <p className="text-muted-foreground">No coaches found</p>
          </div>
        )}
      </div>

      <AddCoachModal
        open={isAddModalOpen}
        onOpenChange={setIsAddModalOpen}
        onSuccess={handleCoachAdded}
      />

      <AlertDialog open={deleteCoachId !== null} onOpenChange={() => setDeleteCoachId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Coach?</AlertDialogTitle>
            <AlertDialogDescription>
              This will remove the coach from your team. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={deleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleting ? "Deleting..." : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </MainLayout>
  );
}
