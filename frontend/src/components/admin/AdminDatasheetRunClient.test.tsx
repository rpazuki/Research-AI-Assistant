import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminDatasheetRunClient from "./AdminDatasheetRunClient";

const push = vi.fn();
const getDatasheetRun = vi.fn();
const listDatasheetRunCandidates = vi.fn();
const cancelDatasheetRun = vi.fn();
const downloadDatasheetRunManifest = vi.fn();
const downloadDatasheetAssistedLinks = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh: vi.fn() }),
  usePathname: () => "/admin/datasheets/run-1",
}));

vi.mock("@/lib/api", () => ({
  logout: vi.fn(),
  getDatasheetRun: (...args: unknown[]) => getDatasheetRun(...args),
  listDatasheetRunCandidates: (...args: unknown[]) => listDatasheetRunCandidates(...args),
  cancelDatasheetRun: (...args: unknown[]) => cancelDatasheetRun(...args),
  downloadDatasheetRunManifest: (...args: unknown[]) => downloadDatasheetRunManifest(...args),
  downloadDatasheetAssistedLinks: (...args: unknown[]) => downloadDatasheetAssistedLinks(...args),
}));

const RUN = {
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
  progress_message: "Discovery complete: 3952 candidates, 2516 to acquire",
  error: null,
  created_at: "2026-07-30T10:00:00Z",
  started_at: "2026-07-30T10:00:05Z",
  finished_at: "2026-07-30T10:05:00Z",
  organism_synonyms: ["Yarrowia lipolytica", "Candida lipolytica"],
  product_synonyms: [],
  product_classes: [],
  template_name: "rlalab-datasheet-v1",
  template_version: 1,
  log_tail: "2026-07-30T10:05:00 Discovery complete",
  candidate_counts: {
    total: 3952,
    relevance_studies: 2518,
    relevance_unknown: 453,
    reviews: 269,
    retracted: 2,
  },
  discovery_summary: {
    source_record_counts: { pubmed: 1686, europepmc: 1886, crossref: 4014, openalex: 3669 },
    source_errors: {},
    duplicates_collapsed: 7279,
    preprints_collapsed: 24,
  },
};

const CANDIDATE = {
  id: "cand-1",
  doi: "10.1021/acsomega.6c03958",
  pmid: "42428839",
  pmc_id: "PMC13347637",
  title: "Engineering of Yarrowia lipolytica for hesperetin",
  journal: "ACS Omega",
  publisher: "ACS",
  year: 2026,
  found_in: ["pubmed", "europepmc"],
  oa_status: "open",
  license: "cc by-nc-nd",
  is_preprint: false,
  preprint_doi: null,
  version_of_record_doi: null,
  doc_type: "primary",
  is_review: false,
  is_retracted: false,
  relevance: "studies",
  relevance_reason: "seed term in title (1 hit)",
  acquisition_status: "pending",
  acquisition_route: null,
  dedupe_group: "doi:10.1021/acsomega.6c03958",
  possible_duplicate_of: [],
  duplicate_evidence: null,
  notes: null,
};

describe("AdminDatasheetRunClient", () => {
  beforeEach(() => {
    push.mockReset();
    getDatasheetRun.mockReset();
    listDatasheetRunCandidates.mockReset();
    cancelDatasheetRun.mockReset();
    downloadDatasheetRunManifest.mockReset();
    downloadDatasheetAssistedLinks.mockReset();
    getDatasheetRun.mockResolvedValue(RUN);
    listDatasheetRunCandidates.mockResolvedValue([CANDIDATE]);
  });

  it("shows the run's counts and per-source records", async () => {
    render(<AdminDatasheetRunClient runId="run-1" />);

    await waitFor(() => expect(screen.getByText("2518")).toBeInTheDocument());
    expect(screen.getByText("453")).toBeInTheDocument();
    expect(screen.getByText("269 reviews · 2 retracted")).toBeInTheDocument();
    expect(screen.getByText("pubmed: 1686")).toBeInTheDocument();
    expect(screen.getByText("duplicates collapsed: 7279")).toBeInTheDocument();
  });

  it("shows why each candidate was judged as it was", async () => {
    render(<AdminDatasheetRunClient runId="run-1" />);

    expect(await screen.findByText("seed term in title (1 hit)")).toBeInTheDocument();
    // "studies" is also a filter option, so assert on the row's badge specifically.
    const row = screen.getByText("seed term in title (1 hit)").closest("tr");
    expect(row).toHaveTextContent("studies");
    expect(screen.getByRole("link", { name: "10.1021/acsomega.6c03958" })).toHaveAttribute(
      "href",
      "https://doi.org/10.1021/acsomega.6c03958"
    );
  });

  it("reports a failed source instead of quietly showing less coverage", async () => {
    getDatasheetRun.mockResolvedValue({
      ...RUN,
      discovery_summary: {
        ...RUN.discovery_summary,
        source_record_counts: { ...RUN.discovery_summary.source_record_counts, openalex: 0 },
        source_errors: { openalex: "OpenAlex: HTTP 503" },
      },
    });

    render(<AdminDatasheetRunClient runId="run-1" />);

    expect(await screen.findByText("openalex: 0 (failed)")).toBeInTheDocument();
  });

  it("filters candidates by relevance through the API", async () => {
    render(<AdminDatasheetRunClient runId="run-1" />);
    await screen.findByText("seed term in title (1 hit)");

    fireEvent.change(screen.getByLabelText("Relevance filter"), { target: { value: "mentions" } });

    await waitFor(() =>
      expect(listDatasheetRunCandidates).toHaveBeenLastCalledWith("run-1", {
        relevance: "mentions",
        acquisition_status: undefined,
        limit: 300,
      })
    );
  });

  it("offers a cancel button only while the run is still active", async () => {
    getDatasheetRun.mockResolvedValue({ ...RUN, status: "running" });
    cancelDatasheetRun.mockResolvedValue({ ...RUN, status: "cancel_requested" });

    render(<AdminDatasheetRunClient runId="run-1" />);

    fireEvent.click(await screen.findByRole("button", { name: "Cancel run" }));
    await waitFor(() => expect(cancelDatasheetRun).toHaveBeenCalledWith("run-1"));
  });

  it("hides cancel for a finished run", async () => {
    render(<AdminDatasheetRunClient runId="run-1" />);

    await screen.findByText("seed term in title (1 hit)");
    expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
  });

  it("downloads the manifest CSV", async () => {
    downloadDatasheetRunManifest.mockResolvedValue({
      blob: new Blob(["doi,included\n"], { type: "text/csv" }),
      filename: "discovery-manifest.csv",
    });
    const createObjectURL = vi.fn(() => "blob:url");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

    render(<AdminDatasheetRunClient runId="run-1" />);

    fireEvent.click(await screen.findByRole("button", { name: "Manifest CSV" }));

    await waitFor(() => expect(downloadDatasheetRunManifest).toHaveBeenCalledWith("run-1"));
    expect(createObjectURL).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("marks a possible duplicate without merging the rows", async () => {
    listDatasheetRunCandidates.mockResolvedValue([
      {
        ...CANDIDATE,
        doi: "10.1016/j.synbio.2026.01.017",
        possible_duplicate_of: ["10.2139/ssrn.5675827"],
        duplicate_evidence: "same normalised title as 10.2139/ssrn.5675827 (years [2025, 2026])",
      },
      { ...CANDIDATE, id: "cand-2", doi: "10.2139/ssrn.5675827", is_preprint: true },
    ]);
    getDatasheetRun.mockResolvedValue({
      ...RUN,
      discovery_summary: { ...RUN.discovery_summary, possible_duplicates_flagged: 2 },
    });

    render(<AdminDatasheetRunClient runId="run-1" />);

    const chip = await screen.findByText("possible duplicate");
    expect(chip).toHaveAttribute("title", expect.stringContaining("10.2139/ssrn.5675827"));
    // Both rows survive: a duplicate that cites itself is harmless, a wrong merge is not.
    expect(screen.getAllByRole("row")).toHaveLength(3); // header + 2
    expect(screen.getByText("Possible duplicates")).toBeInTheDocument();
  });

  const ACQUISITION = {
    attempted: 50,
    fetched: 14,
    assisted_pending: 34,
    failed: 2,
    from_cache: 3,
    by_route: { pmc_oa: 12, biorxiv: 2 },
    by_format: { xml: 14 },
    fidelity_warnings: 1,
    host_tallies: [
      { host: "eutils.ncbi.nlm.nih.gov", requests: 20, successes: 14, blocked: 0, circuit_open: false },
      { host: "www.mdpi.com", requests: 3, successes: 0, blocked: 3, circuit_open: true },
      { host: "unused.example", requests: 0, successes: 0, blocked: 0, circuit_open: false },
    ],
  };

  it("shows acquisition counts and names the host that blocked us", async () => {
    getDatasheetRun.mockResolvedValue({ ...RUN, acquisition_summary: ACQUISITION, acquired_count: 14 });

    render(<AdminDatasheetRunClient runId="run-1" />);

    await waitFor(() => expect(screen.getByText("14")).toBeInTheDocument());
    expect(screen.getByText("3 already cached")).toBeInTheDocument();
    expect(screen.getByText(/www.mdpi.com: 0\/3 · 3 blocked · circuit open/)).toBeInTheDocument();
    // A host we never called should not appear as a zero row.
    expect(screen.queryByText(/unused.example/)).not.toBeInTheDocument();
  });

  it("offers the assisted-acquisition list when papers need a human", async () => {
    getDatasheetRun.mockResolvedValue({ ...RUN, acquisition_summary: ACQUISITION, acquired_count: 14 });
    downloadDatasheetAssistedLinks.mockResolvedValue({
      blob: new Blob(["doi,resolver_url\n"], { type: "text/csv" }),
      filename: "assisted-acquisition.csv",
    });
    const createObjectURL = vi.fn(() => "blob:url");
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });

    render(<AdminDatasheetRunClient runId="run-1" />);

    fireEvent.click(await screen.findByRole("button", { name: "Assisted list (34)" }));

    await waitFor(() => expect(downloadDatasheetAssistedLinks).toHaveBeenCalledWith("run-1"));
    vi.unstubAllGlobals();
  });

  it("hides the assisted list when nothing is waiting on a human", async () => {
    getDatasheetRun.mockResolvedValue({
      ...RUN,
      acquisition_summary: { ...ACQUISITION, assisted_pending: 0 },
    });

    render(<AdminDatasheetRunClient runId="run-1" />);

    await screen.findByText("seed term in title (1 hit)");
    expect(screen.queryByRole("button", { name: /Assisted list/ })).not.toBeInTheDocument();
  });

  it("redirects to login when the session has expired", async () => {
    getDatasheetRun.mockRejectedValue(new Error("Unauthorized"));

    render(<AdminDatasheetRunClient runId="run-1" />);

    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"));
  });

  it("says discovery is still running rather than showing an empty table", async () => {
    getDatasheetRun.mockResolvedValue({ ...RUN, status: "running", candidate_count: null });
    listDatasheetRunCandidates.mockResolvedValue([]);

    render(<AdminDatasheetRunClient runId="run-1" />);

    expect(await screen.findByText("Discovery is still running.")).toBeInTheDocument();
  });
});
