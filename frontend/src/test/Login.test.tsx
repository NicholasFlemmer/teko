import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Login from "@/pages/Login";

const mockLogin = vi.fn();

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ login: mockLogin, isAuthenticated: false }),
}));

describe("Login page", () => {
  beforeEach(() => {
    mockLogin.mockReset();
  });

  it("submits exactly what was typed in the email field, unmodified", async () => {
    mockLogin.mockResolvedValueOnce(undefined);

    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    );

    // Bug 2: the field is labelled "Email" (was "Username"), and the
    // backend does its own normalising (Bug 3) -- this page must not
    // pre-emptively lowercase or otherwise alter the casing of what the
    // user typed before sending it. (Surrounding whitespace isn't checked
    // here: <input type="email"> sanitises that at the platform level
    // before React ever sees an onChange, independent of this component.)
    const emailInput = screen.getByLabelText(/email/i);
    const passwordInput = screen.getByLabelText(/password/i);

    fireEvent.change(emailInput, { target: { value: "Coach@Example.com" } });
    fireEvent.change(passwordInput, { target: { value: "hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() =>
      expect(mockLogin).toHaveBeenCalledWith("Coach@Example.com", "hunter2")
    );
  });

  it("renders an email input, not a plain text username field", () => {
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    );

    const emailInput = screen.getByLabelText(/email/i) as HTMLInputElement;
    expect(emailInput.type).toBe("email");
  });
});
