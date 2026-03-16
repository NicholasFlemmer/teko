import { useState, useEffect } from "react";
import { Pencil, Loader2, Repeat } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { sessionsAPI } from "@/services/api";
import { useToast } from "@/hooks/use-toast";

interface CoachOption {
  id: string;
  name: string;
}

interface TeamOption {
  id: string;
  name: string;
}

interface LocationOption {
  id: string;
  name: string;
}

interface RawSession {
  id: string;
  date: string;
  start_time: string;
  end_time?: string;
  coach_ids?: string[];
  coach_id?: string;
  team_id?: string;
  location_id?: string;
  type?: string;
  notes?: string;
  status?: string;
  recurrence_group_id?: string;
}

interface EditSessionModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  session: RawSession | null;
  coaches: CoachOption[];
  teams: TeamOption[];
  locations: LocationOption[];
  onSuccess: () => void;
}

export function EditSessionModal({ open, onOpenChange, session, coaches, teams, locations, onSuccess }: EditSessionModalProps) {
  const { toast } = useToast();
  const [submitting, setSubmitting] = useState(false);
  const [editScope, setEditScope] = useState<'single' | 'future' | 'all'>('single');
  const [formData, setFormData] = useState({
    team: "",
    coaches: [] as string[],
    date: "",
    startTime: "",
    endTime: "",
    location: "",
    sessionType: "",
    notes: "",
  });

  // Populate form when session changes
  useEffect(() => {
    if (session) {
      const coachIds = session.coach_ids?.length
        ? session.coach_ids
        : session.coach_id ? [session.coach_id] : [];
      setFormData({
        team: session.team_id || "",
        coaches: coachIds,
        date: session.date || "",
        startTime: session.start_time || "",
        endTime: session.end_time || "",
        location: session.location_id || "",
        sessionType: session.type || "practice",
        notes: session.notes || "",
      });
      setEditScope('single');
    }
  }, [session]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session) return;

    if (!formData.team || formData.coaches.length === 0 || !formData.date || !formData.startTime) {
      toast({ title: "Missing fields", description: "Please fill in all required fields.", variant: "destructive" });
      return;
    }

    if (formData.endTime && formData.endTime <= formData.startTime) {
      toast({ title: "Invalid time", description: "End time must be after start time.", variant: "destructive" });
      return;
    }

    setSubmitting(true);
    try {
      const payload: any = {
        team_id: formData.team,
        coach_ids: formData.coaches,
        location_id: formData.location || undefined,
        date: formData.date,
        start_time: formData.startTime,
        end_time: formData.endTime || undefined,
        type: formData.sessionType,
        notes: formData.notes || undefined,
      };

      const scope = session.recurrence_group_id ? editScope : 'single';
      await sessionsAPI.update(session.id, payload, scope);

      const desc = scope !== 'single'
        ? `Recurring sessions updated (${scope}).`
        : "Session updated successfully.";
      toast({ title: "Session updated", description: desc });
      onOpenChange(false);
      onSuccess();
    } catch (err: any) {
      toast({ title: "Error", description: err.message || "Failed to update session.", variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  };

  if (!session) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px] max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
              <Pencil className="w-5 h-5 text-primary" />
            </div>
            <div>
              <DialogTitle className="text-xl">Edit Session</DialogTitle>
              <p className="text-sm text-muted-foreground mt-0.5">
                Modify session details
              </p>
            </div>
          </div>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4 mt-4">
          {/* Scope selector for recurring sessions */}
          {session.recurrence_group_id && (
            <div className="rounded-lg border border-border bg-muted/30 p-3 space-y-2">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Repeat className="w-4 h-4 text-muted-foreground" />
                <span>Recurring session — apply changes to:</span>
              </div>
              <div className="space-y-1 pl-6">
                {(["single", "future", "all"] as const).map((scope) => (
                  <label key={scope} className="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="radio"
                      name="editScope"
                      checked={editScope === scope}
                      onChange={() => setEditScope(scope)}
                      className="rounded-full"
                    />
                    {scope === "single" && "Only this session"}
                    {scope === "future" && "This and all future sessions"}
                    {scope === "all" && "All sessions in this series"}
                  </label>
                ))}
              </div>
            </div>
          )}

          {/* Team */}
          <div className="space-y-2">
            <Label>Team</Label>
            <Select
              value={formData.team}
              onValueChange={(value) => setFormData(prev => ({ ...prev, team: value }))}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select a team" />
              </SelectTrigger>
              <SelectContent>
                {teams.map((team) => (
                  <SelectItem key={team.id} value={team.id.toString()}>
                    {team.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Session Type */}
          <div className="space-y-2">
            <Label>Session Type</Label>
            <div className="flex gap-2">
              {[
                { id: "practice", name: "Practice" },
                { id: "match", name: "Match" },
              ].map((type) => (
                <button
                  key={type.id}
                  type="button"
                  onClick={() => setFormData(prev => ({ ...prev, sessionType: type.id }))}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                    formData.sessionType === type.id
                      ? "bg-primary text-primary-foreground border-primary"
                      : "bg-muted/50 text-foreground border-border hover:border-primary/50"
                  }`}
                >
                  {type.name}
                </button>
              ))}
            </div>
          </div>

          {/* Coaches */}
          <div className="space-y-2">
            <Label>Coach(es)</Label>
            <div className="border border-border rounded-md p-2 max-h-[140px] overflow-y-auto space-y-1">
              {coaches.map((coach) => {
                const isSelected = formData.coaches.includes(coach.id.toString());
                return (
                  <label
                    key={coach.id}
                    className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-muted/50 cursor-pointer text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => {
                        const id = coach.id.toString();
                        setFormData((prev) => ({
                          ...prev,
                          coaches: isSelected
                            ? prev.coaches.filter((c) => c !== id)
                            : [...prev.coaches, id],
                        }));
                      }}
                      className="rounded border-border"
                    />
                    {coach.name}
                  </label>
                );
              })}
              {coaches.length === 0 && (
                <p className="text-xs text-muted-foreground px-2 py-1">No coaches available</p>
              )}
            </div>
            {formData.coaches.length > 0 && (
              <p className="text-xs text-muted-foreground">
                {formData.coaches.length} coach{formData.coaches.length > 1 ? "es" : ""} selected
              </p>
            )}
          </div>

          {/* Location */}
          <div className="space-y-2">
            <Label>Location</Label>
            <Select
              value={formData.location}
              onValueChange={(value) => setFormData(prev => ({ ...prev, location: value }))}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select a location" />
              </SelectTrigger>
              <SelectContent>
                {locations.map((location) => (
                  <SelectItem key={location.id} value={location.id.toString()}>
                    {location.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Date */}
          <div className="space-y-2">
            <Label>Date</Label>
            <Input
              type="date"
              value={formData.date}
              onChange={(e) => setFormData(prev => ({ ...prev, date: e.target.value }))}
            />
          </div>

          {/* Time */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Start Time</Label>
              <Input
                type="time"
                value={formData.startTime}
                onChange={(e) => setFormData(prev => ({ ...prev, startTime: e.target.value }))}
              />
            </div>
            <div className="space-y-2">
              <Label>End Time</Label>
              <Input
                type="time"
                value={formData.endTime}
                onChange={(e) => setFormData(prev => ({ ...prev, endTime: e.target.value }))}
              />
            </div>
          </div>

          {/* Notes */}
          <div className="space-y-2">
            <Label>Notes (Optional)</Label>
            <Textarea
              placeholder="Any additional notes for this session..."
              value={formData.notes}
              onChange={(e) => setFormData(prev => ({ ...prev, notes: e.target.value }))}
              rows={2}
            />
          </div>

          <div className="flex gap-3 pt-4">
            <Button type="submit" className="flex-1" disabled={submitting}>
              {submitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              {submitting ? "Saving..." : "Save Changes"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
