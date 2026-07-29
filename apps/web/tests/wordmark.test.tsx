import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it } from "vitest";

import { HuceWordmark } from "../src/components/brand/huce-wordmark";

describe("HUCE wordmark", () => {
  it("labels the product", () => {
    render(<HuceWordmark />);
    expect(screen.getByText("HUCE")).toBeInTheDocument();
    expect(screen.getByText("Teaching Assignment")).toBeInTheDocument();
  });
});
