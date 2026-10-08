import { describe, it, expect } from "vitest";
import { defaultLocationForTeams } from "@/lib/sessionLocation";

const locations = [{ id: "loc-1" }, { id: "loc-2" }];
const teams = [
  { id: "t1", location_id: "loc-1" },
  { id: "t2", location_id: "loc-2" },
  { id: "t3" },
  { id: "t4", location_id: "gone" },
];

describe("defaultLocationForTeams", () => {
  it("uses the chosen team's default venue", () => {
    expect(defaultLocationForTeams(["t1"], teams, locations)).toBe("loc-1");
  });

  it("uses the first ticked team that has a venue when several are chosen", () => {
    expect(defaultLocationForTeams(["t3", "t2", "t1"], teams, locations)).toBe("loc-2");
  });

  it("returns nothing when the team has no venue, or its venue no longer exists", () => {
    expect(defaultLocationForTeams(["t3"], teams, locations)).toBe("");
    expect(defaultLocationForTeams(["t4"], teams, locations)).toBe("");
  });

  it("returns nothing when no team is chosen or the team is unknown", () => {
    expect(defaultLocationForTeams([], teams, locations)).toBe("");
    expect(defaultLocationForTeams(["nope"], teams, locations)).toBe("");
  });
});
