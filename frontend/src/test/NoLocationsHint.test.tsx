import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { NoLocationsHint } from "@/components/schedule/NoLocationsHint";

let mockRole: string | null = "location_admin";

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { role: mockRole } }),
}));

vi.mock("@/contexts/TerminologyContext", () => ({
  useTerm: (key: string) => (key === "location_plural" ? "Venues" : key),
}));

const renderHint = () =>
  render(
    <MemoryRouter>
      <NoLocationsHint />
    </MemoryRouter>
  );

describe("NoLocationsHint", () => {
  it.each(["location_admin", "super_admin"])("%s sees a link to the Locations page", (role) => {
    mockRole = role;
    renderHint();
    expect(screen.getByText(/need to be added first/i)).toBeTruthy();
    expect(screen.getByRole("link").getAttribute("href")).toBe("/locations");
  });

  it("a coach is told to ask their administrator, with no link", () => {
    mockRole = "coach";
    renderHint();
    expect(screen.getByText(/ask your administrator/i)).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });
});
