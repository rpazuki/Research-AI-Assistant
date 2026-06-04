import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";

import AdminIngestionClient from "./AdminIngestionClient";
import type { IngestionWorkerStatus } from "@/types";

const push = vi.fn();
const refresh = vi.fn();
const logout = vi.fn();
const listIngestionConfigs = vi.fn();
const getIngestionDefaults = vi.fn();
const getIngestionWorkerStatus = vi.fn();
const listIngestionUploads = vi.fn();
const listIngestionJobs = vi.fn();
const createIngestionJob = vi.fn();
const cancelIngestionJob = vi.fn();
const uploadIngestionPdfFolder = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

vi.mock("@/lib/api", () => ({
  cancelIngestionJob: (...args: unknown[]) => cancelIngestionJob(...args),
  createIngestionJob: (...args: unknown[]) => createIngestionJob(...args),
  getIngestionDefaults: (...args: unknown[]) => getIngestionDefaults(...args),
  getIngestionWorkerStatus: (...args: unknown[]) => getIngestionWorkerStatus(...args),
  listIngestionConfigs: (...args: unknown[]) => listIngestionConfigs(...args),
  listIngestionJobs: (...args: unknown[]) => listIngestionJobs(...args),
  listIngestionUploads: (...args: unknown[]) => listIngestionUploads(...args),
  logout: (...args: unknown[]) => logout(...args),
  uploadIngestionPdfFolder: (...args: unknown[]) => uploadIngestionPdfFolder(...args),
}));

const configs = [
  {
    name: "pubmed_abstract.rlalab.toml",
    path: "/app/pipelines/configs/pubmed_abstract.rlalab.toml",
    corpus_name: "rlalab-pubmed-v1",
    source: "pubmed_abstract",
    embedding_model: "pubmedbert",
    year_from: 2000,
    year_to: 2026,
    pdf_dir: null,
    supports_pdf_upload: false,
  },
  {
    name: "pdf.rlalab.toml",
    path: "/app/pipelines/configs/pdf.rlalab.toml",
    corpus_name: "rlalab-pubmed-v1",
    source: "pdf",
    embedding_model: "pubmedbert",
    year_from: null,
    year_to: null,
    pdf_dir: "./data/pdfs",
    supports_pdf_upload: true,
  },
];

const uploadBatch = {
  id: "upload-1",
  name: "Manual PDFs",
  directory_path: "/app/data/admin_uploads/pdf/upload-1",
  file_count: 2,
  total_bytes: 2048,
  created_at: "2026-05-31T10:00:00Z",
};

const queuedJob = {
  id: "job-1",
  requested_by_user_id: "admin-1",
  status: "queued",
  config_name: "pubmed_abstract.rlalab.toml",
  config_path: "/app/pipelines/configs/pubmed_abstract.rlalab.toml",
  source: "pubmed_abstract",
  mode: "incremental",
  from_date: "2026-05-01",
  year: null,
  cache_path: null,
  pdf_upload_batch_id: null,
  options: { write_acquisition_queue: true },
  manifest_id: null,
  document_count: null,
  chunk_count: null,
  progress_message: "Queued",
  log_tail: null,
  error: null,
  created_at: "2026-05-31T10:00:00Z",
  started_at: null,
  finished_at: null,
  updated_at: "2026-05-31T10:00:00Z",
};

const finishedTestYearJob = {
  ...queuedJob,
  id: "job-finished-year",
  status: "succeeded",
  mode: "test_year",
  from_date: null,
  year: 2024,
  cache_path: "/app/data/corpora/rlalab-pubmed-v1/test-2024",
  options: { write_acquisition_queue: false, include_cached_fulltext: true },
  manifest_id: "manifest-2024",
  document_count: 42,
  chunk_count: 420,
  progress_message: "Succeeded",
  log_tail: "Created ingestion manifest\nIndexing complete",
  created_at: "2026-05-31T09:59:30Z",
  started_at: "2026-05-31T10:00:00Z",
  finished_at: "2026-05-31T11:02:03Z",
  updated_at: "2026-05-31T11:02:03Z",
};

const defaults = {
  config_name: "pubmed_abstract.rlalab.toml",
  mode: "full",
  cache_path: "data/corpora/rlalab-pubmed-v1/cumulative",
  write_acquisition_queue: false,
  include_cached_fulltext: false,
};

const activeWorker: IngestionWorkerStatus = {
  active: true,
  state: "polling",
  job_id: null,
  updated_at: "2026-05-31T10:00:00Z",
  seconds_since_heartbeat: 1,
  message: "Worker heartbeat is current.",
};

function setupApi({
  initialJobs = [queuedJob],
  initialUploads = [uploadBatch],
  defaultValues = defaults,
  workerStatus = activeWorker,
}: {
  initialJobs?: unknown[];
  initialUploads?: unknown[];
  defaultValues?: typeof defaults;
  workerStatus?: IngestionWorkerStatus;
} = {}) {
  listIngestionConfigs.mockResolvedValue(configs);
  getIngestionDefaults.mockResolvedValue(defaultValues);
  getIngestionWorkerStatus.mockResolvedValue(workerStatus);
  listIngestionUploads.mockResolvedValue(initialUploads);
  listIngestionJobs.mockResolvedValue(initialJobs);
  logout.mockResolvedValue(undefined);
}

describe("AdminIngestionClient", () => {
  beforeEach(() => {
    push.mockReset();
    refresh.mockReset();
    logout.mockReset();
    listIngestionConfigs.mockReset();
    getIngestionDefaults.mockReset();
    getIngestionWorkerStatus.mockReset();
    listIngestionUploads.mockReset();
    listIngestionJobs.mockReset();
    createIngestionJob.mockReset();
    cancelIngestionJob.mockReset();
    uploadIngestionPdfFolder.mockReset();
  });

  it("loads approved configs, uploads, and recent jobs", async () => {
    setupApi();

    render(<AdminIngestionClient />);

    expect(await screen.findByText("Ingestion operations")).toBeInTheDocument();
    expect(screen.getByLabelText("Approved config")).toHaveValue("pubmed_abstract.rlalab.toml");
    expect(screen.getByText("Manual PDFs")).toBeInTheDocument();
    expect(screen.getByText("Queued")).toBeInTheDocument();
    expect(screen.getByText("From 2026-05-01")).toBeInTheDocument();
    expect(screen.getByDisplayValue("data/corpora/rlalab-pubmed-v1/cumulative")).toBeInTheDocument();
    expect(screen.getByText("Ingestion worker active: polling")).toBeInTheDocument();
    expect(listIngestionConfigs).toHaveBeenCalled();
    expect(getIngestionDefaults).toHaveBeenCalled();
    expect(getIngestionWorkerStatus).toHaveBeenCalled();
    expect(listIngestionUploads).toHaveBeenCalled();
    expect(listIngestionJobs).toHaveBeenCalled();
  });

  it("expands finished job rows with timing, requested year, cache, options, and log details", async () => {
    setupApi({ initialJobs: [finishedTestYearJob] });

    render(<AdminIngestionClient />);

    const modeCell = await screen.findByText("test_year");
    const tableRow = modeCell.closest("tr");
    expect(tableRow).not.toBeNull();

    expect(within(tableRow as HTMLElement).getByText("Year 2024")).toBeInTheDocument();
    fireEvent.click(within(tableRow as HTMLElement).getByRole("button", { name: "Expand job details" }));

    expect(await screen.findByText("Duration")).toBeInTheDocument();
    expect(screen.getAllByText("Config").length).toBeGreaterThan(0);
    expect(screen.getAllByText("pubmed_abstract.rlalab.toml").length).toBeGreaterThan(0);
    expect(screen.getByText("1h 2m 3s")).toBeInTheDocument();
    expect(screen.getByText("/app/data/corpora/rlalab-pubmed-v1/test-2024")).toBeInTheDocument();
    expect(screen.getByText("manifest-2024")).toBeInTheDocument();
    expect(screen.getByText("include_cached_fulltext")).toBeInTheDocument();
    expect(screen.getByText(/Created ingestion manifest/)).toBeInTheDocument();

    fireEvent.click(within(tableRow as HTMLElement).getByRole("button", { name: "Collapse job details" }));
    expect(screen.queryByText("1h 2m 3s")).not.toBeInTheDocument();
  });

  it("shows incremental from date and job-specific cache path in expanded details", async () => {
    setupApi({
      initialJobs: [
        {
          ...queuedJob,
          cache_path: "/app/data/corpora/rlalab-pubmed-v1/cumulative",
        },
      ],
    });

    render(<AdminIngestionClient />);

    const modeCell = await screen.findByText("incremental");
    const tableRow = modeCell.closest("tr");
    expect(tableRow).not.toBeNull();

    expect(within(tableRow as HTMLElement).getByText("From 2026-05-01")).toBeInTheDocument();
    fireEvent.click(within(tableRow as HTMLElement).getByRole("button", { name: "Expand job details" }));

    expect(await screen.findByText("Requested range")).toBeInTheDocument();
    expect(screen.getAllByText("From 2026-05-01").length).toBeGreaterThan(0);
    expect(screen.getByText("/app/data/corpora/rlalab-pubmed-v1/cumulative")).toBeInTheDocument();
  });

  it("warns when no ingestion worker heartbeat is visible", async () => {
    setupApi({
      initialJobs: [],
      workerStatus: {
        active: false,
        state: "not_seen",
        job_id: null,
        updated_at: null,
        seconds_since_heartbeat: null,
        message: "No ingestion worker heartbeat has been seen.",
      },
    });

    render(<AdminIngestionClient />);

    expect(await screen.findByText(/Ingestion worker is not active/)).toBeInTheDocument();
  });

  it("warns differently when a running worker heartbeat is stale", async () => {
    setupApi({
      initialJobs: [
        {
          ...queuedJob,
          status: "running",
          progress_message: "Processed 2300 documents",
          document_count: 2300,
          chunk_count: 65633,
        },
      ],
      workerStatus: {
        active: false,
        state: "running",
        job_id: "job-1",
        updated_at: "2026-05-31T10:00:00Z",
        seconds_since_heartbeat: 802,
        message: "Ingestion worker heartbeat is stale.",
      },
    });

    render(<AdminIngestionClient />);

    expect(await screen.findByText(/heartbeat is stale/)).toBeInTheDocument();
    expect(screen.getByText(/may be busy in a long indexing step/)).toBeInTheDocument();
  });

  it("prefills controls from admin ingestion defaults", async () => {
    setupApi({
      initialJobs: [],
      defaultValues: {
        config_name: "pdf.rlalab.toml",
        mode: "queue_only",
        cache_path: "data/corpora/rlalab-pubmed-v1/cumulative",
        write_acquisition_queue: true,
        include_cached_fulltext: true,
      },
    });

    render(<AdminIngestionClient />);

    expect(await screen.findByLabelText("Approved config")).toHaveValue("pdf.rlalab.toml");
    expect(screen.getByLabelText("Mode")).toHaveValue("queue_only");
    expect(screen.getByDisplayValue("data/corpora/rlalab-pubmed-v1/cumulative")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Write acquisition queue" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Include cached full text in queue" })).toBeChecked();
  });

  it("queues an incremental PubMed ingestion job from the form", async () => {
    setupApi({ initialJobs: [] });
    createIngestionJob.mockResolvedValue(queuedJob);

    render(<AdminIngestionClient />);

    await screen.findByText("Queue ingestion job");
    fireEvent.change(screen.getByDisplayValue("Full run"), {
      target: { value: "incremental" },
    });
    fireEvent.change(screen.getByLabelText("From date"), {
      target: { value: "2026-05-01" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Write acquisition queue" }));
    fireEvent.click(screen.getByRole("button", { name: "Queue job" }));

    await waitFor(() => {
      expect(createIngestionJob).toHaveBeenCalledWith({
        config_name: "pubmed_abstract.rlalab.toml",
        mode: "incremental",
        from_date: "2026-05-01",
        year: null,
        cache_path: "data/corpora/rlalab-pubmed-v1/cumulative",
        pdf_upload_batch_id: null,
        write_acquisition_queue: true,
        include_cached_fulltext: false,
      });
    });
    expect(await screen.findByText("Queued")).toBeInTheDocument();
  });

  it("uploads a PDF folder and uses it for a PDF ingestion job", async () => {
    setupApi({ initialUploads: [], initialJobs: [] });
    uploadIngestionPdfFolder.mockResolvedValue(uploadBatch);
    createIngestionJob.mockResolvedValue({
      ...queuedJob,
      id: "job-2",
      config_name: "pdf.rlalab.toml",
      source: "pdf",
      mode: "full",
      pdf_upload_batch_id: uploadBatch.id,
    });

    render(<AdminIngestionClient />);

    await screen.findByText("Queue ingestion job");
    fireEvent.change(screen.getByDisplayValue("pubmed_abstract.rlalab.toml · pubmed_abstract"), {
      target: { value: "pdf.rlalab.toml" },
    });

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const files = [
      new File(["%PDF-1.4 one"], "one.pdf", { type: "application/pdf" }),
      new File(["%PDF-1.4 two"], "two.pdf", { type: "application/pdf" }),
    ];
    fireEvent.change(fileInput, { target: { files } });
    fireEvent.change(screen.getByPlaceholderText("Batch name"), {
      target: { value: "Manual PDFs" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Upload PDFs" }));

    await waitFor(() => {
      expect(uploadIngestionPdfFolder).toHaveBeenCalledWith(files, "Manual PDFs");
    });
    await screen.findByText("Manual PDFs");
    fireEvent.click(screen.getByRole("button", { name: "Queue job" }));

    await waitFor(() => {
      expect(createIngestionJob).toHaveBeenCalledWith(
        expect.objectContaining({
          config_name: "pdf.rlalab.toml",
          pdf_upload_batch_id: uploadBatch.id,
        })
      );
    });
  });

  it("cancels a queued job from the job table", async () => {
    setupApi();
    cancelIngestionJob.mockResolvedValue({
      ...queuedJob,
      status: "cancelled",
      progress_message: "Cancelled before worker picked it up",
      finished_at: "2026-05-31T10:05:00Z",
    });

    render(<AdminIngestionClient />);

    const row = await screen.findByText("Queued");
    const tableRow = row.closest("tr");
    expect(tableRow).not.toBeNull();
    fireEvent.click(within(tableRow as HTMLElement).getByRole("button", { name: "Cancel" }));

    await waitFor(() => {
      expect(cancelIngestionJob).toHaveBeenCalledWith("job-1");
    });
    expect(await screen.findByText("cancelled")).toBeInTheDocument();
  });

  it("redirects to login when loading ingestion data is unauthorized", async () => {
    listIngestionConfigs.mockRejectedValue(new Error("Unauthorized"));
    getIngestionDefaults.mockResolvedValue(defaults);
    getIngestionWorkerStatus.mockResolvedValue(activeWorker);
    listIngestionUploads.mockResolvedValue([]);
    listIngestionJobs.mockResolvedValue([]);

    render(<AdminIngestionClient />);

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith("/login");
    });
  });
});
