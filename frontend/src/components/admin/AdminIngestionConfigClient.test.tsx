import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminIngestionConfigClient from "./AdminIngestionConfigClient";

const push = vi.fn();
const listIngestionConfigs = vi.fn();
const getIngestionConfig = vi.fn();
const createIngestionConfig = vi.fn();
const updateIngestionConfig = vi.fn();

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
}));

// A realistically long filename: this is what made the select set a width floor
// the panel could not shrink below.
const LONG_NAME = "corpus.rlalab-yarrowia-lipolytica-fulltext-2016-2026.toml";

describe("AdminIngestionConfigClient", () => {
  beforeEach(() => {
    push.mockReset();
    listIngestionConfigs.mockReset();
    getIngestionConfig.mockReset();
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
});
