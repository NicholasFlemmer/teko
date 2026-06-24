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
  created_at?: any;
  is_active: boolean;
}

export const DEFAULT_TERMINOLOGY: Terminology = {
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
};
