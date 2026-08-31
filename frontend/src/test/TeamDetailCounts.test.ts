import { describe, it, expect } from "vitest";
import { countSessionsByType } from "@/pages/TeamDetail";

// Bug: practiceCount/matchCount compared stored session `type` values
// against capitalized literals ("Practice"/"Match"), but every value the
// app actually stores is lowercase (e.g. "practice") -- so both counts
// were zero for all real data. countSessionsByType must match
// case-insensitively (and whitespace-insensitively) instead.

describe("countSessionsByType", () => {
  const sessions = [
    { type: "practice" },
    { type: "practice" },
    { type: "match" },
    { type: "  Match  " },
    { session_type: "practice" },
    { type: "workshop" },
  ];

  it("counts practice sessions from real (lowercase) fixture data as non-zero", () => {
    expect(countSessionsByType(sessions, "Practice")).toBeGreaterThan(0);
  });

  it("counts match sessions from real (lowercase) fixture data as non-zero", () => {
    expect(countSessionsByType(sessions, "Match")).toBeGreaterThan(0);
  });

  it("counts practice sessions exactly", () => {
    expect(countSessionsByType(sessions, "Practice")).toBe(3);
  });

  it("counts match sessions exactly, trimming whitespace", () => {
    expect(countSessionsByType(sessions, "Match")).toBe(2);
  });

  it("returns 0 for a type with no matches", () => {
    expect(countSessionsByType(sessions, "Tournament")).toBe(0);
  });
});
