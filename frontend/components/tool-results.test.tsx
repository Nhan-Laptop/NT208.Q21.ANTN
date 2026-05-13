import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
import { ToolResultsRenderer } from "@/components/tool-results";

describe("ToolResultsRenderer", () => {
  it("renders insufficient corpus journal match card", () => {
    render(
      <ToolResultsRenderer
        messageType="journal_list"
        content=""
        toolResults={{ type: "journal_list", data: [], status: "insufficient_corpus" }}
      />,
    );
    expect(screen.getByText(/Chưa đủ dữ liệu để gợi ý tạp chí/i)).toBeInTheDocument();
  });
});
