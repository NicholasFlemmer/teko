import { useTerm } from "@/contexts/TerminologyContext";
import { Label } from "@/components/ui/label";

interface CoachOption {
  id: string;
  name?: string;
  username?: string;
  active?: boolean;
  status?: string;
}

interface CoachMultiSelectProps {
  coaches: CoachOption[];
  value: string[];
  onChange: (ids: string[]) => void;
}

// Coach records carry no active flag today, so every coach counts as active
// unless a record is explicitly marked inactive/disabled.
export const isActiveCoach = (c: CoachOption) =>
  c.active !== false && c.status !== "disabled" && c.status !== "inactive";

export function CoachMultiSelect({ coaches, value, onChange }: CoachMultiSelectProps) {
  const coachSingular = useTerm("coach_singular");
  const coachPlural = useTerm("coach_plural");
  const options = coaches.filter(isActiveCoach);

  const toggle = (id: string) =>
    onChange(value.includes(id) ? value.filter((c) => c !== id) : [...value, id]);

  return (
    <div className="space-y-2">
      <Label>{coachPlural}</Label>
      <div className="border border-border rounded-md p-2 max-h-[140px] overflow-y-auto space-y-1">
        {options.map((coach) => (
          <label
            key={coach.id}
            className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-muted/50 cursor-pointer text-sm"
          >
            <input
              type="checkbox"
              checked={value.includes(coach.id)}
              onChange={() => toggle(coach.id)}
              className="rounded border-border"
            />
            {coach.name || coach.username || "Unnamed"}
          </label>
        ))}
        {options.length === 0 && (
          <p className="text-xs text-muted-foreground px-2 py-1">No {coachPlural.toLowerCase()} available</p>
        )}
      </div>
      {value.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {value.length} {value.length === 1 ? coachSingular.toLowerCase() : coachPlural.toLowerCase()} selected
        </p>
      )}
    </div>
  );
}
