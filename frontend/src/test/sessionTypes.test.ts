import { describe, it, expect } from "vitest";
import { formatSessionType } from "@/lib/sessionTypes";

describe("formatSessionType", () => {
  it("returns 'Practice' for undefined", () => {
    expect(formatSessionType(undefined)).toBe("Practice");
  });

  it("returns 'Practice' for an empty string", () => {
    expect(formatSessionType("")).toBe("Practice");
  });

  it("title-cases 'practice'", () => {
    expect(formatSessionType("practice")).toBe("Practice");
  });

  it("title-cases 'match'", () => {
    expect(formatSessionType("match")).toBe("Match");
  });

  it("title-cases 'workshop'", () => {
    expect(formatSessionType("workshop")).toBe("Workshop");
  });

  it("replaces hyphens with spaces and title-cases each word for a custom type", () => {
    expect(formatSessionType("coach-academy-coaching-course")).toBe(
      "Coach Academy Coaching Course"
    );
  });
});
