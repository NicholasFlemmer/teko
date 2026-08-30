import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import OrgSettings from "@/pages/OrgSettings";
import { DEFAULT_TERMINOLOGY, type Organisation } from "@/types/Organisation";

// The timezone field used to be a free-text input where a typo silently
// fell back to UTC server-side with no visible error. It's now a
// constrained <select> populated from Intl.supportedValuesOf('timeZone')
// -- these tests cover that it renders as a real select, that an org's
// existing value is pre-selected, and that a value already stored but not
// in the IANA list (a leftover typo from before this change) is never
// silently dropped from the selection.

vi.mock("@/components/layout/MainLayout", () => ({
  MainLayout: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { org_id: "org-a", role: "location_admin" } }),
}));

vi.mock("@/contexts/TerminologyContext", () => ({
  useRefreshTerminology: () => vi.fn(async () => {}),
}));

const mockGetById = vi.fn();
const mockGetTerminology = vi.fn();

vi.mock("@/services/api", () => ({
  organisationsAPI: {
    getById: (...args: unknown[]) => mockGetById(...args),
    getTerminology: (...args: unknown[]) => mockGetTerminology(...args),
    update: vi.fn(),
  },
}));

function makeOrg(overrides: Partial<Organisation> = {}): Organisation {
  return {
    id: "org-a",
    name: "Org A",
    slug: "org-a",
    type: "sports",
    terminology: DEFAULT_TERMINOLOGY,
    is_active: true,
    timezone: null,
    ...overrides,
  };
}

describe("OrgSettings timezone select", () => {
  beforeEach(() => {
    mockGetById.mockReset();
    mockGetTerminology.mockReset();
    mockGetTerminology.mockResolvedValue({ success: true, terminology: DEFAULT_TERMINOLOGY });
  });

  it("renders a native select containing a known IANA timezone", async () => {
    mockGetById.mockResolvedValue({ success: true, organisation: makeOrg() });

    render(<OrgSettings />);

    const select = await screen.findByLabelText("Timezone");
    expect(select.tagName).toBe("SELECT");
    expect(screen.getByRole("option", { name: "Africa/Johannesburg" })).toBeInTheDocument();
  });

  it("pre-selects the org's existing stored value", async () => {
    mockGetById.mockResolvedValue({
      success: true,
      organisation: makeOrg({ timezone: "Africa/Johannesburg" }),
    });

    render(<OrgSettings />);

    const select = (await screen.findByLabelText("Timezone")) as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    await waitFor(() => expect(select.value).toBe("Africa/Johannesburg"));
  });

  it("still shows a stored value that is not in the IANA list as selected, not discarded", async () => {
    mockGetById.mockResolvedValue({
      success: true,
      organisation: makeOrg({ timezone: "Africa/Jozi" }),
    });

    render(<OrgSettings />);

    const select = (await screen.findByLabelText("Timezone")) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("Africa/Jozi"));
    expect(screen.getByRole("option", { name: "Africa/Jozi" })).toBeInTheDocument();
  });
});
