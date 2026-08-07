import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminIngestionConfigClient from "./AdminIngestionConfigClient";

const push = vi.fn();
const listIngestionConfigs = vi.fn();
const getIngestionConfig = vi.fn();
const createIngestionConfig = vi.fn();
const updateIngestionConfig = vi.fn();
const listDatasheetRuns = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh: vi.fn() }),
  usePathname: () => "/admin/ingestion/config",
}));

vi.mock("@/lib/api", () => ({
  logout: vi.fn(),
  listIngestionConfigs: (...args: unknown[]) => listIngestionConfigs(...args),
  getIngestionConfig: (...args: unknown[]) => getIngestionConfig(...args),
  createIngestionConfig: (...args: unknown[]) => createIngestionConfig(...args),
  updateIngestionConfig: (...args: unknown[]) => updateIngestionConfig(...args),
  listDatasheetRuns: (...args: unknown[]) => listDatasheetRuns(...args),
}));

// A realistically long filename: this is what made the select set a width floor
// the panel could not shrink below.
const LONG_NAME = "corpus.rlalab-yarrowia-lipolytica-fulltext-2016-2026.toml";

const DATASHEET_RUN = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "yarrowia-2016-2026",
  status: "succeeded",
  phase: "ingestion",
  seed_kind: "organism",
  organism_name: "Yarrowia lipolytica",
  organism_taxid: 4952,
  product_term: null,
  year_from: 2016,
  year_to: 2026,
  candidate_count: 3426,
  progress_message: null,
  error: null,
  cache_path: "data/corpora/datasheets/yarrowia-2016-2026-11111111",
  created_at: "2026-08-01T10:00:00Z",
  started_at: "2026-08-01T10:00:00Z",
  finished_at: "2026-08-01T11:00:00Z",
};

describe("AdminIngestionConfigClient", () => {
  beforeEach(() => {
    push.mockReset();
    listIngestionConfigs.mockReset();
    getIngestionConfig.mockReset();
    listDatasheetRuns.mockReset();
    listDatasheetRuns.mockResolvedValue([DATASHEET_RUN]);
    listIngestionConfigs.mockResolvedValue([
      { name: LONG_NAME, source: "pubmed_abstract", path: `pipelines/configs/${LONG_NAME}` },
      { name: "corpus.rlalab.toml", source: "pubmed_abstract", path: "pipelines/configs/corpus.rlalab.toml" },
    ]);
    getIngestionConfig.mockResolvedValue({
      name: LONG_NAME,
      path: `pipelines/configs/${LONG_NAME}`,
      content: { corpus: { name: "rlalab", source: "pubmed_abstract", embedding_model: "pubmedbert" } },
    });
  });

  it("puts a draggable splitter between the config list and the editor", async () => {
    render(<AdminIngestionConfigClient />);

    const splitter = await screen.findByRole("separator", { name: "Resize config list" });
    expect(splitter).toHaveAttribute("aria-orientation", "vertical");
  });

  it("resizes the list panel by dragging, within bounds", async () => {
    render(<AdminIngestionConfigClient />);

    const splitter = await screen.findByRole("separator", { name: "Resize config list" });
    const panel = splitter.previousElementSibling as HTMLElement;
    const width = () => panel.style.getPropertyValue("--config-list-width");
    expect(width()).toBe("320px");

    fireEvent.mouseDown(splitter);
    fireEvent.mouseMove(document, { clientX: 480 });
    await waitFor(() => expect(width()).toBe("480px"));

    // Past the minimum the panel stops rather than collapsing onto its content.
    fireEvent.mouseMove(document, { clientX: 40 });
    await waitFor(() => expect(width()).toBe("220px"));

    fireEvent.mouseMove(document, { clientX: 5000 });
    await waitFor(() => expect(width()).toBe("560px"));

    fireEvent.mouseUp(document);
    // Dragging has ended: further movement must not resize.
    fireEvent.mouseMove(document, { clientX: 300 });
    expect(width()).toBe("560px");
  });

  it("resets to the default width on double click", async () => {
    render(<AdminIngestionConfigClient />);

    const splitter = await screen.findByRole("separator", { name: "Resize config list" });
    const panel = splitter.previousElementSibling as HTMLElement;
    const width = () => panel.style.getPropertyValue("--config-list-width");

    fireEvent.mouseDown(splitter);
    fireEvent.mouseMove(document, { clientX: 500 });
    fireEvent.mouseUp(document);
    await waitFor(() => expect(width()).toBe("500px"));

    fireEvent.doubleClick(splitter);
    await waitFor(() => expect(width()).toBe("320px"));
  });

  it("applies the dragged width only where the splitter exists", async () => {
    // Below `lg` the panels stack and the splitter is hidden. An inline pixel
    // width survives that breakpoint and leaves a narrow orphan column above a
    // full-width editor — which is what put the dropdown in its own skinny box.
    render(<AdminIngestionConfigClient />);

    const splitter = await screen.findByRole("separator", { name: "Resize config list" });
    const panel = splitter.previousElementSibling as HTMLElement;

    expect(panel.style.width).toBe("");
    expect(panel.style.getPropertyValue("--config-list-width")).toBe("320px");
    expect(panel.className).toContain("w-full");
    expect(panel.className).toContain("lg:w-[var(--config-list-width)]");
  });

  it("scrolls a long config path sideways instead of wrapping", async () => {
    render(<AdminIngestionConfigClient />);

    const path = await screen.findByTitle(`pipelines/configs/${LONG_NAME}`);

    expect(path.className).toContain("whitespace-nowrap");
    expect(path.className).toContain("overflow-x-auto");
  });

  it("lets the list panel and its controls shrink instead of overflowing the splitter", async () => {
    // A select sizes itself to its longest option, and a grid child defaults to
    // min-width:auto — together they set a floor wider than the panel, which is
    // what spilled the dropdown across the splitter.
    render(<AdminIngestionConfigClient />);

    const splitter = await screen.findByRole("separator", { name: "Resize config list" });
    const panel = splitter.previousElementSibling as HTMLElement;
    // The editor pane has selects of its own, so scope to the list panel's.
    await screen.findAllByRole("combobox");
    const select = panel.querySelector("select") as HTMLSelectElement;

    expect(panel.className).toContain("min-w-0");
    expect(panel.className).toContain("overflow-hidden");
    expect(select.className).toContain("w-full");
    expect(select.className).toContain("min-w-0");
    expect(select.closest("label")?.className).toContain("min-w-0");
  });

  it("offers the discovery and datasheet sources", async () => {
    render(<AdminIngestionConfigClient />);

    const sourceSelect = (await screen.findByText("Source type")).closest("label")
      ?.querySelector("select") as HTMLSelectElement;
    const values = Array.from(sourceSelect.options).map((option) => option.value);

    expect(values).toEqual(
      expect.arrayContaining([
        "discovery_search",
        "datasheet_manifest",
        "datasheet_fulltext",
        "datasheet_rows",
      ])
    );
  });

  it("shows discovery search terms when the discovery source is selected", async () => {
    render(<AdminIngestionConfigClient />);

    const sourceSelect = (await screen.findByText("Source type")).closest("label")
      ?.querySelector("select") as HTMLSelectElement;
    fireEvent.change(sourceSelect, { target: { value: "discovery_search" } });

    expect(await screen.findByText("Organism terms")).toBeInTheDocument();
    expect(screen.getByText("Product terms")).toBeInTheDocument();
    expect(screen.queryByText("PubMed query")).not.toBeInTheDocument();
  });

  it("lets a datasheet run be picked instead of typing its cache path", async () => {
    // The last path segment is a UUID fragment; typing it by hand is the obvious
    // way for this to go wrong.
    render(<AdminIngestionConfigClient />);

    const sourceSelect = (await screen.findByText("Source type")).closest("label")
      ?.querySelector("select") as HTMLSelectElement;
    fireEvent.change(sourceSelect, { target: { value: "datasheet_fulltext" } });

    const runSelect = (await screen.findByText("Datasheet run")).closest("label")
      ?.querySelector("select") as HTMLSelectElement;
    await waitFor(() =>
      expect(Array.from(runSelect.options).map((option) => option.value)).toContain(
        DATASHEET_RUN.cache_path
      )
    );
    expect(runSelect.options[1].textContent).toContain("3426 candidates");

    fireEvent.change(runSelect, { target: { value: DATASHEET_RUN.cache_path } });
    expect(runSelect.value).toBe(DATASHEET_RUN.cache_path);
  });

  it("falls back to a text field when no datasheet runs can be listed", async () => {
    // A failed listing must not make a required field unfillable: a path typed
    // by hand is still valid.
    listDatasheetRuns.mockRejectedValue(new Error("unavailable"));
    render(<AdminIngestionConfigClient />);

    const sourceSelect = (await screen.findByText("Source type")).closest("label")
      ?.querySelector("select") as HTMLSelectElement;
    fireEvent.change(sourceSelect, { target: { value: "datasheet_manifest" } });

    const label = (await screen.findByText("Datasheet run")).closest("label") as HTMLElement;
    await waitFor(() => expect(label.querySelector("select")).toBeNull());
    const input = label.querySelector("input") as HTMLInputElement;
    expect(input.placeholder).toBe("data/corpora/datasheets/<run>");
  });

  it("does not list datasheet runs for a source that has no use for them", async () => {
    render(<AdminIngestionConfigClient />);
    await screen.findByText("Source type");

    expect(listDatasheetRuns).not.toHaveBeenCalled();
  });
});
