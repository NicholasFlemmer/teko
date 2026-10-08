import { Link } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { useTerm } from "@/contexts/TerminologyContext";

// Roles that can see the Locations page (matches the sidebar's ops nav).
const ROLES_WITH_LOCATIONS_PAGE = ["super_admin", "location_admin"];

/** Shown under the location field when the organisation has no locations. */
export function NoLocationsHint() {
  const { user } = useAuth();
  const locationPlural = useTerm("location_plural");
  const locationPluralLower = locationPlural.toLowerCase();
  const canAdd = !!user?.role && ROLES_WITH_LOCATIONS_PAGE.includes(user.role);

  return (
    <p className="text-xs text-muted-foreground">
      {canAdd ? (
        <>
          No {locationPluralLower} yet — {locationPluralLower} need to be added first.{" "}
          <Link to="/locations" className="text-primary underline">
            Go to {locationPlural}
          </Link>
        </>
      ) : (
        <>No {locationPluralLower} yet. Ask your administrator to add one.</>
      )}
    </p>
  );
}
