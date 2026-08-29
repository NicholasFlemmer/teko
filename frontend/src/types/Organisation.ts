export type OrganisationType = 'sports' | 'ngo' | 'events' | 'corporate';

export interface Terminology {
  coach_singular: string;
  coach_plural: string;
  player_singular: string;
  player_plural: string;
  team_singular: string;
  team_plural: string;
  session_singular: string;
  session_plural: string;
  location_singular: string;
  location_plural: string;
}

export interface Organisation {
  id: string;
  name: string;
  slug: string;
  type: OrganisationType;
  terminology: Terminology;
  // Optional override for the AI system prompt. When empty/unset, the
  // backend falls back to a default prompt for the org's type.
  ai_persona_prompt?: string;
  created_at?: any;
  is_active: boolean;
  // Safeguarding configuration. Absent/null means not configured -- never
  // treat a missing works_with_minors as false, it means "not declared".
  safeguarding_lead_name?: string | null;
  safeguarding_lead_email?: string | null;
  works_with_minors?: boolean | null;
  // IANA timezone string, e.g. "Africa/Johannesburg" or "America/Sao_Paulo".
  // Nullable, no default -- an org without one falls back to UTC server-side
  // (see FirebaseService.get_org_now).
  timezone?: string | null;
}

// Default terminology per org type, shown until an org customises its own
// labels. Mirrors DEFAULT_AI_PERSONA_PROMPTS on the backend (see
// ConversationService) — each org type gets language that doesn't read as
// sports-specific. Also mirrored server-side in
// FirebaseService.DEFAULT_TERMINOLOGY_BY_TYPE.
export const DEFAULT_TERMINOLOGY_BY_TYPE: Record<OrganisationType, Terminology> = {
  sports: {
    coach_singular: 'Coach',
    coach_plural: 'Coaches',
    player_singular: 'Player',
    player_plural: 'Players',
    team_singular: 'Team',
    team_plural: 'Teams',
    session_singular: 'Session',
    session_plural: 'Sessions',
    location_singular: 'Location',
    location_plural: 'Locations',
  },
  ngo: {
    coach_singular: 'Facilitator',
    coach_plural: 'Facilitators',
    player_singular: 'Participant',
    player_plural: 'Participants',
    team_singular: 'Group',
    team_plural: 'Groups',
    session_singular: 'Session',
    session_plural: 'Sessions',
    location_singular: 'Venue',
    location_plural: 'Venues',
  },
  events: {
    coach_singular: 'Coach',
    coach_plural: 'Coaches',
    player_singular: 'Attendee',
    player_plural: 'Attendees',
    team_singular: 'Team',
    team_plural: 'Teams',
    session_singular: 'Session',
    session_plural: 'Sessions',
    location_singular: 'Venue',
    location_plural: 'Venues',
  },
  corporate: {
    coach_singular: 'Facilitator',
    coach_plural: 'Facilitators',
    player_singular: 'Participant',
    player_plural: 'Participants',
    team_singular: 'Team',
    team_plural: 'Teams',
    session_singular: 'Session',
    session_plural: 'Sessions',
    location_singular: 'Venue',
    location_plural: 'Venues',
  },
};

// Final catch-all fallback for when an org's type is missing/unrecognized,
// or not yet known (e.g. before the org has loaded client-side).
export const DEFAULT_TERMINOLOGY: Terminology = DEFAULT_TERMINOLOGY_BY_TYPE.sports;

/** Resolve the default terminology set for an org type, falling back to sports. */
export function getDefaultTerminology(type?: OrganisationType | null): Terminology {
  return (type && DEFAULT_TERMINOLOGY_BY_TYPE[type]) || DEFAULT_TERMINOLOGY;
}
