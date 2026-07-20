import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "../app/page";

describe("RepoLens home page", () => {
  it("presents the foundation-stage repository analysis interface", () => {
    render(<Home />);

    expect(screen.getByText("RepoLens")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Understand a repository before your first commit.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("GitHub repository URL")).toHaveAttribute(
      "placeholder",
      "https://github.com/owner/repository",
    );
    expect(
      screen.getByRole("button", { name: "Analyze Repository" }),
    ).toBeDisabled();
    expect(
      screen.getByText(/Repository analysis will be enabled in a later development phase/i),
    ).toBeInTheDocument();
  });
});
