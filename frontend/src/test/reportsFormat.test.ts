import { describe, it, expect } from "vitest";
import { checkInHeadline, participantsTile, attendanceCsvRows, QuickStats } from "@/lib/reportsFormat";

const base: QuickStats = {
  total_sessions: 91,
  check_in_rate: 45,
  checked_in: 41,
  verified_check_ins: 24,
  unverified_check_ins: 17,
  attendance_mode: "named",
  total_headcount: 0,
  total_students: 30,
  active_coaches: 5,
};

describe("checkInHeadline", () => {
  it("shows checked in out of started sessions, with the verified count", () => {
    expect(checkInHeadline(base)).toBe("41 of 91, 24 verified");
  });
  it("is zero-safe before stats load", () => {
    expect(checkInHeadline(null)).toBe("0 of 0, 0 verified");
  });
});

describe("participantsTile", () => {
  it("headcount org: shows the headcount recorded across the range", () => {
    const t = participantsTile({ ...base, attendance_mode: "headcount", total_headcount: 182 }, "Participants");
    expect(t).toEqual({ label: "Participants Recorded (Headcount)", value: 182 });
  });
  it("other orgs: still shows enrolled players, labelled as enrolled", () => {
    expect(participantsTile(base, "Students")).toEqual({ label: "Students Enrolled", value: 30 });
  });
});

describe("attendanceCsvRows", () => {
  const rows = [{
    coach_id: "c1", coach_name: "A", total_sessions: 3, checked_in: 2,
    verified_check_ins: 1, unverified_check_ins: 1,
  }];
  it("keeps existing columns first and in order, then adds the two new columns", () => {
    const [row] = attendanceCsvRows(rows);
    expect(Object.keys(row)).toEqual([
      "coach_id", "coach_name", "total_sessions", "checked_in",
      "Verified check-ins", "Unverified check-ins",
    ]);
    expect(row["Verified check-ins"]).toBe(1);
    expect(row["Unverified check-ins"]).toBe(1);
  });
  it("defaults missing counts to 0", () => {
    const [row] = attendanceCsvRows([{ total_sessions: 1, checked_in: 0 }]);
    expect(row["Verified check-ins"]).toBe(0);
  });
});
