import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import AdminDatasheetTemplatesClient from "./AdminDatasheetTemplatesClient";

const push = vi.fn();
const listDatasheetTemplates = vi.fn();
const getDatasheetTemplate = vi.fn();
const updateDatasheetTemplate = vi.fn();
const getDatasheetExtractionSchema = vi.fn();
const logout = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/admin/datasheets/templates",
}));

vi.mock("@/lib/api", () => ({
  getDatasheetExtractionSchema: (...args: unknown[]) => getDatasheetExtractionSchema(...args),
  getDatasheetTemplate: (...args: unknown[]) => getDatasheetTemplate(...args),
  listDatasheetTemplates: (...args: unknown[]) => listDatasheetTemplates(...args),
  logout: (...args: unknown[]) => logout(...args),
  updateDatasheetTemplate: (...args: unknown[]) => updateDatasheetTemplate(...args),
}));

const SUMMARY = {
  id: "t1",
  name: "rlalab-datasheet-v1",
  version: 1,
  description: "Seeded template",
  is_default: true,
  column_count: 2,
  enabled_column_count: 2,
  created_at: "2026-07-29T10:00:00Z",
  updated_at: "2026-07-29T10:00:00Z",
};

const DETAIL = {
  ...SUMMARY,
  columns: [
    {
      id: "c1",
      key: "carbon_source",
      label: "carbon source",
      kind: "free_text" as const,
      order_index: 0,
      vocabulary: [],
      extraction_hint: "Carbon substrate fed.",
      source_hint: "fulltext" as const,
      required: false,
      enabled: true,
    },
    {
      id: "c2",
      key: "standard_product_class",
      label: "Standard Product Class",
      kind: "controlled" as const,
      order_index: 1,
      vocabulary: ["Organic Acids", "Polyketides"],
      extraction_hint: null,
      source_hint: "any" as const,
      required: false,
      enabled: true,
    },
  ],
};

describe("AdminDatasheetTemplatesClient", () => {
  beforeEach(() => {
    push.mockReset();
    listDatasheetTemplates.mockReset();
    getDatasheetTemplate.mockReset();
    updateDatasheetTemplate.mockReset();
    getDatasheetExtractionSchema.mockReset();
    logout.mockReset();
    listDatasheetTemplates.mockResolvedValue([SUMMARY]);
    getDatasheetTemplate.mockResolvedValue(DETAIL);
    logout.mockResolvedValue(undefined);
  });

  it("renders the template columns with their labels and vocabulary size", async () => {
    render(<AdminDatasheetTemplatesClient />);

    await waitFor(() => expect(getDatasheetTemplate).toHaveBeenCalledWith("rlalab-datasheet-v1"));
    expect(screen.getByDisplayValue("carbon_source")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Standard Product Class")).toBeInTheDocument();
    expect(screen.getByText("2 values")).toBeInTheDocument();
  });

  it("disables save until a column is edited", async () => {
    render(<AdminDatasheetTemplatesClient />);
    await waitFor(() => expect(getDatasheetTemplate).toHaveBeenCalled());

    const save = screen.getByRole("button", { name: "Save column set" });
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Label for column 1"), {
      target: { value: "carbon source (edited)" },
    });
    expect(save).toBeEnabled();
  });

  it("sends the reindexed column set on save", async () => {
    updateDatasheetTemplate.mockResolvedValue({ ...DETAIL, version: 2 });
    render(<AdminDatasheetTemplatesClient />);
    await waitFor(() => expect(getDatasheetTemplate).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Move column 2 up" }));
    fireEvent.click(screen.getByRole("button", { name: "Save column set" }));

    await waitFor(() => expect(updateDatasheetTemplate).toHaveBeenCalled());
    const [name, payload] = updateDatasheetTemplate.mock.calls[0];
    expect(name).toBe("rlalab-datasheet-v1");
    expect(payload.columns.map((column: { key: string }) => column.key)).toEqual([
      "standard_product_class",
      "carbon_source",
    ]);
    // order_index must stay dense and unique or the API rejects the set.
    expect(payload.columns.map((column: { order_index: number }) => column.order_index)).toEqual([0, 1]);
    await screen.findByText("Saved. Template is now version 2.");
  });

  it("blocks a save with a non-snake-case key before calling the API", async () => {
    render(<AdminDatasheetTemplatesClient />);
    await waitFor(() => expect(getDatasheetTemplate).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("Key for column 1"), {
      target: { value: "Carbon Source" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save column set" }));

    await screen.findByText(/must be snake_case/);
    expect(updateDatasheetTemplate).not.toHaveBeenCalled();
  });

  it("blocks a save when a controlled column has no vocabulary", async () => {
    render(<AdminDatasheetTemplatesClient />);
    await waitFor(() => expect(getDatasheetTemplate).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("Vocabulary for column 2"), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save column set" }));

    await screen.findByText(/is controlled and needs a vocabulary/);
    expect(updateDatasheetTemplate).not.toHaveBeenCalled();
  });

  it("blocks a save when every column is disabled", async () => {
    render(<AdminDatasheetTemplatesClient />);
    await waitFor(() => expect(getDatasheetTemplate).toHaveBeenCalled());

    fireEvent.click(screen.getByLabelText("Enabled for column 1"));
    fireEvent.click(screen.getByLabelText("Enabled for column 2"));
    fireEvent.click(screen.getByRole("button", { name: "Save column set" }));

    await screen.findByText("At least one column must be enabled.");
    expect(updateDatasheetTemplate).not.toHaveBeenCalled();
  });

  it("shows the extraction schema preview on request", async () => {
    getDatasheetExtractionSchema.mockResolvedValue({
      template_name: "rlalab-datasheet-v1",
      template_version: 1,
      enabled_columns: ["carbon_source", "standard_product_class"],
      json_schema: { type: "object", additionalProperties: false },
    });
    render(<AdminDatasheetTemplatesClient />);
    await waitFor(() => expect(getDatasheetTemplate).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Preview extraction schema" }));

    await waitFor(() =>
      expect(getDatasheetExtractionSchema).toHaveBeenCalledWith("rlalab-datasheet-v1")
    );
    expect(screen.getByText(/2 enabled columns/)).toBeInTheDocument();
  });

  it("redirects to login when the API reports Unauthorized", async () => {
    listDatasheetTemplates.mockRejectedValue(new Error("Unauthorized"));
    render(<AdminDatasheetTemplatesClient />);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"));
  });
});
