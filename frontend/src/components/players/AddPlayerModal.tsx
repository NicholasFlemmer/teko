import { useState, useEffect } from "react";
import { GraduationCap, X, Loader2 } from "lucide-react";
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
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import { playersAPI, teamsAPI } from "@/services/api";

interface AddPlayerModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPlayerAdded?: () => void;
}

export function AddPlayerModal({ open, onOpenChange, onPlayerAdded }: AddPlayerModalProps) {
  const [formData, setFormData] = useState({
    firstName: "",
    lastName: "",
    dateOfBirth: "",
    specialNotes: "",
    guardianName: "",
    guardianEmail: "",
    guardianPrimaryPhone: "",
    guardianSecondaryPhone: "",
  });
  const [selectedTeams, setSelectedTeams] = useState<string[]>([]);
  const [teams, setTeams] = useState<any[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setFormData({
        firstName: "", lastName: "", dateOfBirth: "", specialNotes: "",
        guardianName: "", guardianEmail: "", guardianPrimaryPhone: "", guardianSecondaryPhone: "",
      });
      setSelectedTeams([]);
      setError(null);
      teamsAPI.getAll().then((res) => {
        setTeams(res.teams || []);
      }).catch(console.error);
    }
  }, [open]);

  const handleTeamToggle = (teamId: string) => {
    setSelectedTeams((prev) =>
      prev.includes(teamId)
        ? prev.filter((id) => id !== teamId)
        : [...prev, teamId]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setSubmitting(true);
      setError(null);
      await playersAPI.create({
        first_name: formData.firstName,
        last_name: formData.lastName,
        date_of_birth: formData.dateOfBirth,
        guardian_name: formData.guardianName,
        guardian_email: formData.guardianEmail,
        guardian_primary_phone: formData.guardianPrimaryPhone,
        guardian_secondary_phone: formData.guardianSecondaryPhone || undefined,
        special_notes: formData.specialNotes || undefined,
        team_ids: selectedTeams.length > 0 ? selectedTeams : undefined,
      });
      onOpenChange(false);
      setFormData({
        firstName: "",
        lastName: "",
        dateOfBirth: "",
        specialNotes: "",
        guardianName: "",
        guardianEmail: "",
        guardianPrimaryPhone: "",
        guardianSecondaryPhone: "",
      });
      setSelectedTeams([]);
      onPlayerAdded?.();
    } catch (err: any) {
      console.error("Failed to create player:", err);
      setError(err.message || "Failed to create player");
    } finally {
      setSubmitting(false);
    }
  };

  const update = (field: string, value: string) =>
    setFormData((prev) => ({ ...prev, [field]: value }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[540px] max-h-[90vh] p-0">
        <DialogHeader className="px-6 pt-6 pb-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-success/10 flex items-center justify-center">
              <GraduationCap className="w-5 h-5 text-success" />
            </div>
            <div>
              <DialogTitle className="text-xl">Add New Player</DialogTitle>
              <p className="text-sm text-muted-foreground mt-0.5">
                Register a new player in the program
              </p>
            </div>
          </div>
        </DialogHeader>

        <ScrollArea className="max-h-[calc(90vh-120px)]">
          <form onSubmit={handleSubmit} className="space-y-4 px-6 pb-6 pt-4">
            {error && (
              <div className="bg-destructive/10 text-destructive text-sm p-3 rounded-lg">{error}</div>
            )}
            {/* Team Selection */}
            <div className="space-y-2">
              <Label>Assign to Teams</Label>
              <div className="border border-border rounded-lg p-3 space-y-2 max-h-32 overflow-y-auto">
                {teams.map((team) => (
                  <div key={team.id} className="flex items-center gap-2">
                    <Checkbox
                      id={`team-${team.id}`}
                      checked={selectedTeams.includes(team.id)}
                      onCheckedChange={() => handleTeamToggle(team.id)}
                    />
                    <label
                      htmlFor={`team-${team.id}`}
                      className="text-sm font-medium leading-none cursor-pointer flex-1"
                    >
                      {team.name}
                      <span className="text-xs text-muted-foreground ml-2">({team.age_group || "N/A"})</span>
                    </label>
                  </div>
                ))}
                {teams.length === 0 && (
                  <p className="text-sm text-muted-foreground">No teams available</p>
                )}
              </div>
              {selectedTeams.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {selectedTeams.map((teamId) => {
                    const team = teams.find((t) => t.id === teamId);
                    return (
                      <span
                        key={teamId}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-primary/10 text-primary"
                      >
                        {team?.name}
                        <button
                          type="button"
                          onClick={() => handleTeamToggle(teamId)}
                          className="hover:bg-primary/20 rounded-full p-0.5"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Name */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="firstName">First Name</Label>
                <Input
                  id="firstName"
                  placeholder="e.g. Thabo"
                  value={formData.firstName}
                  onChange={(e) => update("firstName", e.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="lastName">Last Name</Label>
                <Input
                  id="lastName"
                  placeholder="e.g. Mokoena"
                  value={formData.lastName}
                  onChange={(e) => update("lastName", e.target.value)}
                  required
                />
              </div>
            </div>

            {/* Date of Birth */}
            <div className="space-y-2">
              <Label htmlFor="dateOfBirth">Date of Birth</Label>
              <Input
                id="dateOfBirth"
                type="date"
                value={formData.dateOfBirth}
                onChange={(e) => update("dateOfBirth", e.target.value)}
              />
            </div>

            {/* Special Notes */}
            <div className="space-y-2">
              <Label htmlFor="specialNotes">Special Notes</Label>
              <Textarea
                id="specialNotes"
                placeholder="Allergies, medical conditions, dietary needs, etc."
                value={formData.specialNotes}
                onChange={(e) => update("specialNotes", e.target.value)}
                rows={2}
              />
            </div>

            {/* Guardian Details */}
            <div className="border-t border-border pt-4">
              <p className="text-sm font-medium text-foreground mb-3">Guardian Details</p>

              <div className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="guardianName">Guardian Name</Label>
                  <Input
                    id="guardianName"
                    placeholder="e.g. Nomsa Mokoena"
                    value={formData.guardianName}
                    onChange={(e) => update("guardianName", e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="guardianEmail">Guardian Email</Label>
                  <Input
                    id="guardianEmail"
                    type="email"
                    placeholder="e.g. nomsa@email.com"
                    value={formData.guardianEmail}
                    onChange={(e) => update("guardianEmail", e.target.value)}
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="guardianPrimaryPhone">Primary Phone</Label>
                    <Input
                      id="guardianPrimaryPhone"
                      type="tel"
                      placeholder="+27 82 123 4567"
                      value={formData.guardianPrimaryPhone}
                      onChange={(e) => update("guardianPrimaryPhone", e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="guardianSecondaryPhone">Secondary Phone</Label>
                    <Input
                      id="guardianSecondaryPhone"
                      type="tel"
                      placeholder="+27 82 765 4321"
                      value={formData.guardianSecondaryPhone}
                      onChange={(e) => update("guardianSecondaryPhone", e.target.value)}
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="flex gap-3 pt-4">
              <Button type="submit" className="flex-1" disabled={submitting}>
                {submitting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin mr-2" />
                    Adding...
                  </>
                ) : (
                  "Add Player"
                )}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
              >
                Cancel
              </Button>
            </div>
          </form>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}
