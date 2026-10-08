export interface TeamWithLocation {
  id: string;
  location_id?: string;
}

/**
 * The venue to pre-fill in the session form for the chosen teams: the default
 * location of the first chosen team (in the order they were ticked) that has
 * one the organisation still has. Returns "" if none applies.
 */
export function defaultLocationForTeams(
  selectedTeamIds: string[],
  teams: TeamWithLocation[],
  locations: { id: string }[],
): string {
  for (const teamId of selectedTeamIds) {
    const team = teams.find((t) => t.id.toString() === teamId);
    const locationId = team?.location_id;
    if (locationId && locations.some((l) => l.id.toString() === locationId.toString())) {
      return locationId.toString();
    }
  }
  return "";
}
