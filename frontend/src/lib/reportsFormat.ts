export interface QuickStats {
  total_sessions: number;
  check_in_rate: number;
  checked_in?: number;
  verified_check_ins?: number;
  unverified_check_ins?: number;
  attendance_mode?: "named" | "headcount";
  total_headcount?: number;
  total_students: number;
  active_coaches: number;
}

export interface AttendanceRow {
  total_sessions: number;
  checked_in: number;
  verified_check_ins?: number;
  unverified_check_ins?: number;
  [key: string]: unknown;
}

// "41 of 91, 24 verified" -- checked in, out of sessions already started
export function checkInHeadline(stats: QuickStats | null): string {
  if (!stats) return "0 of 0, 0 verified";
  return `${stats.checked_in ?? 0} of ${stats.total_sessions ?? 0}, ${stats.verified_check_ins ?? 0} verified`;
}

// Headcount orgs have no named register, so the tile shows the headcount
// recorded across the date range; everyone else sees enrolled players.
export function participantsTile(
  stats: QuickStats | null,
  playerPlural: string,
): { label: string; value: number } {
  if (stats?.attendance_mode === "headcount") {
    return { label: `${playerPlural} Recorded (Headcount)`, value: stats.total_headcount ?? 0 };
  }
  return { label: `${playerPlural} Enrolled`, value: stats?.total_students ?? 0 };
}

// Existing columns stay where they are; the two verified columns go last.
export function attendanceCsvRows(rows: AttendanceRow[]): Record<string, unknown>[] {
  return rows.map(({ verified_check_ins, unverified_check_ins, ...rest }) => ({
    ...rest,
    "Verified check-ins": verified_check_ins ?? 0,
    "Unverified check-ins": unverified_check_ins ?? 0,
  }));
}
