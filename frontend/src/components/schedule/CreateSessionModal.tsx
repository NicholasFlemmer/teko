import { useState } from "react";
import { Plus, X, Loader2 } from "lucide-react";
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
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
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
  address?: string;
}

interface CreateSessionModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  coaches: CoachOption[];
  teams: TeamOption[];
  locations: LocationOption[];
  onSuccess: () => void;
}

const defaultSessionTypes = [
  { id: "practice", name: "Practice" },
  { id: "match", name: "Match" },
];

export function CreateSessionModal({ open, onOpenChange, coaches, teams, locations, onSuccess }: CreateSessionModalProps) {
  const { toast } = useToast();
  const [submitting, setSubmitting] = useState(false);
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
  const [sessionTypes, setSessionTypes] = useState(defaultSessionTypes);
  const [newTypeName, setNewTypeName] = useState("");
  const [isAddingType, setIsAddingType] = useState(false);
  const [deleteTypeId, setDeleteTypeId] = useState<string | null>(null);

  const resetForm = () => {
    setFormData({
      team: "", coaches: [], date: "", startTime: "", endTime: "",
      location: "", sessionType: "", notes: "",
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!formData.team || formData.coaches.length === 0 || !formData.date || !formData.startTime || !formData.sessionType) {
      toast({ title: "Missing fields", description: "Please fill in all required fields.", variant: "destructive" });
      return;
    }

    setSubmitting(true);
    try {
      await sessionsAPI.create({
        team_id: formData.team,
        coach_ids: formData.coaches,
        location_id: formData.location || undefined,
        date: formData.date,
        start_time: formData.startTime,
        end_time: formData.endTime || undefined,
        type: formData.sessionType,
        notes: formData.notes || undefined,
        status: "scheduled",
      });
      toast({ title: "Session created", description: "The session has been scheduled successfully." });
      resetForm();
      onOpenChange(false);
      onSuccess();
    } catch (err: any) {
      console.error("Failed to create session:", err);
      toast({ title: "Error", description: err.message || "Failed to create session.", variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  };

  const handleAddType = () => {
    const trimmed = newTypeName.trim();
    if (!trimmed) return;
    const id = trimmed.toLowerCase().replace(/\s+/g, "-");
    if (sessionTypes.some((t) => t.id === id)) return;
    setSessionTypes((prev) => [...prev, { id, name: trimmed }]);
    setFormData((prev) => ({ ...prev, sessionType: id }));
    setNewTypeName("");
    setIsAddingType(false);
  };

  const handleDeleteType = (typeId: string) => {
    setSessionTypes((prev) => prev.filter((t) => t.id !== typeId));
    if (formData.sessionType === typeId) {
      setFormData((prev) => ({ ...prev, sessionType: "" }));
    }
    setDeleteTypeId(null);
  };

  const selectedTeam = teams.find(t => t.id.toString() === formData.team);
  const selectedLocation = locations.find(l => l.id.toString() === formData.location);

  return (
    <>
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px] max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
              <Plus className="w-5 h-5 text-primary" />
            </div>
            <div>
              <DialogTitle className="text-xl">Create Session</DialogTitle>
              <p className="text-sm text-muted-foreground mt-0.5">
                Schedule a new coaching session
              </p>
            </div>
          </div>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4 mt-4">
          {/* Team Selection */}
          <div className="space-y-2">
            <Label htmlFor="team">Team</Label>
            <Select
              value={formData.team}
              onValueChange={(value) => setFormData({ ...formData, team: value })}
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
            {selectedTeam && (
              <p className="text-xs text-muted-foreground">
                Players will be loaded from {selectedTeam.name} for roll call
              </p>
            )}
          </div>

          {/* Session Type with add/delete */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Session Type</Label>
              <Popover open={isAddingType} onOpenChange={setIsAddingType}>
                <PopoverTrigger asChild>
                  <Button type="button" variant="ghost" size="sm" className="h-7 gap-1 text-xs text-primary">
                    <Plus className="w-3 h-3" />
                    New Type
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-64 p-3 bg-popover border border-border shadow-md z-50" align="end">
                  <div className="space-y-2">
                    <Label className="text-xs">Type Name</Label>
                    <Input
                      placeholder="e.g. Tournament"
                      value={newTypeName}
                      onChange={(e) => setNewTypeName(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleAddType(); } }}
                      autoFocus
                    />
                    <div className="flex gap-2">
                      <Button type="button" size="sm" className="flex-1 h-8" onClick={handleAddType}>
                        Add
                      </Button>
                      <Button type="button" variant="outline" size="sm" className="h-8" onClick={() => { setIsAddingType(false); setNewTypeName(""); }}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                </PopoverContent>
              </Popover>
            </div>

            <div className="flex flex-wrap gap-2">
              {sessionTypes.map((type) => {
                const isSelected = formData.sessionType === type.id;
                return (
                  <div key={type.id} className="group relative">
                    <button
                      type="button"
                      onClick={() => setFormData({ ...formData, sessionType: type.id })}
                      className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                        isSelected
                          ? "bg-primary text-primary-foreground border-primary"
                          : "bg-muted/50 text-foreground border-border hover:border-primary/50"
                      }`}
                    >
                      {type.name}
                    </button>
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setDeleteTypeId(type.id); }}
                      className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-destructive text-destructive-foreground flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                      title={`Delete "${type.name}"`}
                    >
                      <X className="w-2.5 h-2.5" />
                    </button>
                  </div>
                );
              })}
            </div>
            {sessionTypes.length === 0 && (
              <p className="text-xs text-muted-foreground">No session types. Click "New Type" to add one.</p>
            )}
          </div>

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

          <div className="space-y-2">
            <Label htmlFor="location">Location</Label>
            <Select
              value={formData.location}
              onValueChange={(value) => setFormData({ ...formData, location: value })}
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
            {selectedLocation?.address && (
              <div className="rounded-lg border border-border overflow-hidden mt-2">
                <iframe
                  title="Location Preview"
                  width="100%"
                  height="150"
                  style={{ border: 0 }}
                  loading="lazy"
                  referrerPolicy="no-referrer-when-downgrade"
                  src={`https://www.google.com/maps/embed/v1/place?key=${import.meta.env.VITE_GOOGLE_MAPS_API_KEY}&q=${encodeURIComponent(selectedLocation.address)}`}
                  allowFullScreen
                />
              </div>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="date">Date</Label>
            <Input
              id="date"
              type="date"
              value={formData.date}
              onChange={(e) => setFormData({ ...formData, date: e.target.value })}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="startTime">Start Time</Label>
              <Input
                id="startTime"
                type="time"
                value={formData.startTime}
                onChange={(e) => setFormData({ ...formData, startTime: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="endTime">End Time</Label>
              <Input
                id="endTime"
                type="time"
                value={formData.endTime}
                onChange={(e) => setFormData({ ...formData, endTime: e.target.value })}
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="notes">Notes (Optional)</Label>
            <Textarea
              id="notes"
              placeholder="Any additional notes for this session..."
              value={formData.notes}
              onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
              rows={2}
            />
          </div>

          <div className="flex gap-3 pt-4">
            <Button type="submit" className="flex-1" disabled={submitting}>
              {submitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              {submitting ? "Creating..." : "Create Session"}
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

      <AlertDialog open={deleteTypeId !== null} onOpenChange={() => setDeleteTypeId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Session Type?</AlertDialogTitle>
            <AlertDialogDescription>
              This will remove "{sessionTypes.find((t) => t.id === deleteTypeId)?.name}" from your session types. Any existing sessions using this type won't be affected.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteTypeId && handleDeleteType(deleteTypeId)}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
