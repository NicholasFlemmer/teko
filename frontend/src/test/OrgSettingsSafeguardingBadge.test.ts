import { describe, it, expect } from "vitest";
import { isSafeguardingFullyConfigured } from "@/pages/OrgSettings";

// Bug 2: the Safeguarding badge previously read "Configured" as soon as
// ANY one safeguarding field was set (e.g. a lead name alone, with no
// email and no works_with_minors decision). It must read "Configured"
// only when all three fields hold a real value -- anything short of that
// (including exactly the partial state QA hit in production: name set,
// email blank) must read "Not configured".

describe("isSafeguardingFullyConfigured", () => {
  it("is false for a null org", () => {
    expect(isSafeguardingFullyConfigured(null)).toBe(false);
  });

  it("is false when nothing is set", () => {
    expect(
      isSafeguardingFullyConfigured({
        safeguarding_lead_name: null,
        safeguarding_lead_email: null,
        works_with_minors: null,
      })
    ).toBe(false);
  });

  it("is false when only the lead name is set (the exact production bug shape)", () => {
    expect(
      isSafeguardingFullyConfigured({
        safeguarding_lead_name: "Ricki",
        safeguarding_lead_email: null,
        works_with_minors: null,
      })
    ).toBe(false);
  });

  it("is false when only the lead email is set", () => {
    expect(
      isSafeguardingFullyConfigured({
        safeguarding_lead_name: null,
        safeguarding_lead_email: "ricki@example.com",
        works_with_minors: null,
      })
    ).toBe(false);
  });

  it("is false when only works_with_minors is set", () => {
    expect(
      isSafeguardingFullyConfigured({
        safeguarding_lead_name: null,
        safeguarding_lead_email: null,
        works_with_minors: true,
      })
    ).toBe(false);
  });

  it("is false when name and email are set but works_with_minors is still undeclared", () => {
    expect(
      isSafeguardingFullyConfigured({
        safeguarding_lead_name: "Ricki",
        safeguarding_lead_email: "ricki@example.com",
        works_with_minors: null,
      })
    ).toBe(false);
  });

  it("is false when the lead name is whitespace-only", () => {
    expect(
      isSafeguardingFullyConfigured({
        safeguarding_lead_name: "   ",
        safeguarding_lead_email: "ricki@example.com",
        works_with_minors: true,
      })
    ).toBe(false);
  });

  it("is false when the lead email is an empty string", () => {
    expect(
      isSafeguardingFullyConfigured({
        safeguarding_lead_name: "Ricki",
        safeguarding_lead_email: "",
        works_with_minors: true,
      })
    ).toBe(false);
  });

  it("is true when all three fields hold real values, works_with_minors=true", () => {
    expect(
      isSafeguardingFullyConfigured({
        safeguarding_lead_name: "Ricki",
        safeguarding_lead_email: "ricki@example.com",
        works_with_minors: true,
      })
    ).toBe(true);
  });

  it("is true when all three fields hold real values, works_with_minors=false", () => {
    // false is a real declared decision, not "unset" -- must still count
    // as fully configured.
    expect(
      isSafeguardingFullyConfigured({
        safeguarding_lead_name: "Ricki",
        safeguarding_lead_email: "ricki@example.com",
        works_with_minors: false,
      })
    ).toBe(true);
  });
});
