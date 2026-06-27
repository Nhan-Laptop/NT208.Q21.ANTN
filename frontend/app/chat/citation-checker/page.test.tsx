import { describe, expect, it, vi } from "vitest";

const mockRedirect = vi.fn();

vi.mock("next/navigation", () => ({
  redirect: (...args: unknown[]) => mockRedirect(...args),
}));

import CitationCheckerRoutePage from "@/app/chat/citation-checker/page";

describe("legacy citation checker route", () => {
  it("redirects to chat verification mode", () => {
    CitationCheckerRoutePage();
    expect(mockRedirect).toHaveBeenCalledWith("/chat?mode=verification");
  });
});
