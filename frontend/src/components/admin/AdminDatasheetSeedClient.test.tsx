import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminDatasheetSeedClient from "./AdminDatasheetSeedClient";

const push = vi.fn();
const lookupOrganism = vi.fn();
const lookupProduct = vi.fn();
const listDatasheetRuns = vi.fn();
const createDatasheetRun = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh: vi.fn() }),
  usePathname: () => "/admin/datasheets",
}));

vi.mock("@/lib/api", () => ({
  logout: vi.fn(),
  lookupOrganism: (...args: unknown[]) => lookupOrganism(...args),
  lookupProduct: (...args: unknown[]) => lookupProduct(...args),
  listDatasheetRuns: (...args: unknown[]) => listDatasheetRuns(...args),
  createDatasheetRun: (...args: unknown[]) => createDatasheetRun(...args),
}));

const PRODUCT_CLASSES = [
  "Lipids & Fatty Acids",
  "Flavonoids & Polyphenols",
  "Terpenoids & Sterols",
];

const YARROWIA_SEED = {
  taxid: 4952,
  scientific_name: "Yarrowia lipolytica",
  rank: "species",
  synonyms: ["Candida lipolytica", "Endomycopsis lipolytica", "Mycotorula lipolytica"],
  common_names: [],
  lineage: ["Fungi", "Ascomycota", "Yarrowia"],
  search_terms: [
    "Yarrowia lipolytica",
    "Candida lipolytica",
    "Endomycopsis lipolytica",
    "Mycotorula lipolytica",
  ],
};

const HESPERETIN_SEED = {
  cid: 72281,
  preferred_name: "hesperetin",
  synonyms: ["Hesperitin", "3',5,7-Trihydroxy-4'-methoxyflavanone"],
  chebi_id: "CHEBI:28230",
  inchikey: "AIONOLUJZLIMTK-AWEZNQCLSA-N",
  molecular_formula: "C16H14O6",
  molecular_weight: "302.28",
  iupac_name: "(2S)-5,7-dihydroxy-...",
  chebi_label: "hesperetin",
  chebi_definition: "A trihydroxyflavanone having ...",
  product_class: "Flavonoids & Polyphenols",
  product_class_evidence: "flavanone",
  search_terms: ["hesperetin", "Hesperitin", "3',5,7-Trihydroxy-4'-methoxyflavanone"],
};

describe("AdminDatasheetSeedClient", () => {
  beforeEach(() => {
    vi.useRealTimers();
    push.mockReset();
    lookupOrganism.mockReset();
    lookupProduct.mockReset();
    listDatasheetRuns.mockReset();
    createDatasheetRun.mockReset();
    listDatasheetRuns.mockResolvedValue([]);
    lookupOrganism.mockResolvedValue({ query: "", suggestions: [], seed: null });
    lookupProduct.mockResolvedValue({
      query: "",
      suggestions: [],
      seed: null,
      product_classes: PRODUCT_CLASSES,
    });
  });

  it("shows the resolved organism with its synonyms and search terms", async () => {
    lookupOrganism.mockResolvedValue({
      query: "Yarrowia lipolytica",
      suggestions: [],
      seed: YARROWIA_SEED,
    });

    render(<AdminDatasheetSeedClient />);

    fireEvent.change(screen.getByPlaceholderText("Yarrowia lipolytica"), {
      target: { value: "Yarrowia lipolytica" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resolve organism" }));

    await waitFor(() => expect(screen.getByText("4952")).toBeInTheDocument());
    expect(screen.getByText("Synonyms (3)")).toBeInTheDocument();
    // Once as a synonym chip, once as a search term — the two lists are distinct
    // and the search-term list is what discovery consumes.
    expect(screen.getAllByText("Candida lipolytica")).toHaveLength(2);
    expect(screen.getByText("Search terms (4)")).toBeInTheDocument();
    expect(lookupOrganism).toHaveBeenCalledWith({ q: "Yarrowia lipolytica", resolve: true });
  });

  it("resolves a picked suggestion by taxid rather than by name", async () => {
    lookupOrganism.mockResolvedValueOnce({
      query: "Yarrowia lipo",
      suggestions: [{ taxid: 4952, scientific_name: "Yarrowia lipolytica", rank: "species", common_name: null }],
      seed: null,
    });
    lookupOrganism.mockResolvedValue({ query: "", suggestions: [], seed: YARROWIA_SEED });

    render(<AdminDatasheetSeedClient />);

    fireEvent.change(screen.getByPlaceholderText("Yarrowia lipolytica"), {
      target: { value: "Yarrowia lipo" },
    });

    const suggestion = await screen.findByRole("button", { name: /Yarrowia lipolytica taxid 4952/ });
    fireEvent.click(suggestion);

    await waitFor(() => expect(screen.getByText("4952")).toBeInTheDocument());
    expect(lookupOrganism).toHaveBeenLastCalledWith({ taxid: 4952, resolve: true });
  });

  it("does not query upstream for a query shorter than three characters", async () => {
    render(<AdminDatasheetSeedClient />);

    fireEvent.change(screen.getByPlaceholderText("Yarrowia lipolytica"), {
      target: { value: "Ya" },
    });

    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(lookupOrganism).not.toHaveBeenCalled();
  });

  it("shows the product class with the token that matched it", async () => {
    lookupProduct.mockResolvedValue({
      query: "hesperetin",
      suggestions: [],
      seed: HESPERETIN_SEED,
      product_classes: PRODUCT_CLASSES,
    });

    render(<AdminDatasheetSeedClient />);

    fireEvent.change(screen.getByPlaceholderText("hesperetin"), {
      target: { value: "hesperetin" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resolve bioproduct" }));

    await waitFor(() => expect(screen.getByText("72281")).toBeInTheDocument());
    expect(screen.getByText("Flavonoids & Polyphenols")).toBeInTheDocument();
    expect(screen.getByText(/matched on/)).toHaveTextContent("flavanone");
    expect(screen.getByText("CHEBI:28230")).toBeInTheDocument();
  });

  it("asks the admin to pick a class when no rule matched", async () => {
    lookupProduct.mockResolvedValue({
      query: "zorblaxine",
      suggestions: [],
      seed: { ...HESPERETIN_SEED, product_class: null, product_class_evidence: null },
      product_classes: PRODUCT_CLASSES,
    });

    render(<AdminDatasheetSeedClient />);

    fireEvent.change(screen.getByPlaceholderText("hesperetin"), {
      target: { value: "zorblaxine" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resolve bioproduct" }));

    const select = await screen.findByLabelText("Standard product class");
    expect(select).toHaveValue("");
    expect(screen.getByText(/No rule matched/)).toBeInTheDocument();
    expect(
      Array.from(select.querySelectorAll("option")).map((option) => option.textContent)
    ).toEqual(["Select a class", ...PRODUCT_CLASSES]);
  });

  it("reports an unmatched seed rather than showing an empty panel", async () => {
    lookupOrganism.mockResolvedValue({ query: "zzz", suggestions: [], seed: null });

    render(<AdminDatasheetSeedClient />);

    fireEvent.change(screen.getByPlaceholderText("Yarrowia lipolytica"), {
      target: { value: "zzzzz" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resolve organism" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("No organism matched");
  });

  it("surfaces an upstream failure as an error, not as 'not found'", async () => {
    lookupOrganism.mockRejectedValue(new Error("NCBI Taxonomy lookup failed: HTTP 503"));

    render(<AdminDatasheetSeedClient />);

    fireEvent.change(screen.getByPlaceholderText("Yarrowia lipolytica"), {
      target: { value: "Yarrowia" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resolve organism" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 503");
  });

  it("redirects to login when the session has expired", async () => {
    lookupOrganism.mockRejectedValue(new Error("Unauthorized"));

    render(<AdminDatasheetSeedClient />);

    fireEvent.change(screen.getByPlaceholderText("Yarrowia lipolytica"), {
      target: { value: "Yarrowia" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resolve organism" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"));
  });

  it("queues a run from the reviewed search terms, not from the typed name", async () => {
    lookupOrganism.mockResolvedValue({
      query: "Yarrowia lipolytica",
      suggestions: [],
      seed: YARROWIA_SEED,
    });
    createDatasheetRun.mockResolvedValue({ id: "run-1", name: "yarrowia-run" });

    render(<AdminDatasheetSeedClient />);

    fireEvent.change(screen.getByPlaceholderText("Yarrowia lipolytica"), {
      target: { value: "Yarrowia lipolytica" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resolve organism" }));
    await waitFor(() => expect(screen.getByText("4952")).toBeInTheDocument());

    fireEvent.change(screen.getByPlaceholderText("yarrowia-2016-2026"), {
      target: { value: "yarrowia-run" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Queue discovery run" }));

    await waitFor(() => expect(createDatasheetRun).toHaveBeenCalled());
    const payload = createDatasheetRun.mock.calls[0][0];
    expect(payload.seed_kind).toBe("organism");
    expect(payload.organism_taxid).toBe(4952);
    expect(payload.organism_synonyms).toEqual(YARROWIA_SEED.search_terms);
    expect(payload.year_from).toBe(2016);
  });

  it("cannot queue a run before a seed is resolved", async () => {
    render(<AdminDatasheetSeedClient />);

    fireEvent.change(screen.getByPlaceholderText("yarrowia-2016-2026"), {
      target: { value: "premature" },
    });

    expect(screen.getByRole("button", { name: "Queue discovery run" })).toBeDisabled();
    expect(screen.getByText(/Resolve a seed and name the run first/)).toBeInTheDocument();
  });

  it("lists existing runs with links to their detail pages", async () => {
    listDatasheetRuns.mockResolvedValue([
      {
        id: "run-1",
        name: "yarrowia-2016-2026",
        status: "succeeded",
        phase: "discovery",
        seed_kind: "organism",
        organism_name: "Yarrowia lipolytica",
        organism_taxid: 4952,
        product_term: null,
        year_from: 2016,
        year_to: 2026,
        candidate_count: 3952,
        progress_message: "Discovery complete",
        error: null,
        created_at: "2026-07-30T10:00:00Z",
        started_at: null,
        finished_at: null,
      },
    ]);

    render(<AdminDatasheetSeedClient />);

    const link = await screen.findByRole("link", { name: "yarrowia-2016-2026" });
    expect(link).toHaveAttribute("href", "/admin/datasheets/run-1");
    expect(screen.getByText("3952")).toBeInTheDocument();
    expect(screen.getByText("succeeded")).toBeInTheDocument();
  });
});
