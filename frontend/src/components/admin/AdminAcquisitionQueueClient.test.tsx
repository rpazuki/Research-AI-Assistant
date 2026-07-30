import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import AdminAcquisitionQueueClient from "./AdminAcquisitionQueueClient";

const push = vi.fn();
const getIngestionAcquisitionQueue = vi.fn();
const downloadIngestionAcquisitionReviewCsv = vi.fn();
const logout = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/admin/ingestion/acquisition",
}));

vi.mock("@/lib/api", () => ({
  downloadIngestionAcquisitionReviewCsv: (...args: unknown[]) => downloadIngestionAcquisitionReviewCsv(...args),
  getIngestionAcquisitionQueue: (...args: unknown[]) => getIngestionAcquisitionQueue(...args),
  logout: (...args: unknown[]) => logout(...args),
}));

describe("AdminAcquisitionQueueClient", () => {
  beforeEach(() => {
    push.mockReset();
    getIngestionAcquisitionQueue.mockReset();
    downloadIngestionAcquisitionReviewCsv.mockReset();
    logout.mockReset();
    downloadIngestionAcquisitionReviewCsv.mockResolvedValue({
      blob: new Blob(["csv"]),
      filename: "review_queue.csv",
    });
    logout.mockResolvedValue(undefined);
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:review-queue"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  });

  it("renders acquisition queue records with open and download links for URL fields", async () => {
    getIngestionAcquisitionQueue.mockResolvedValue([
      {
        cache_path: "data/corpora/rlalab-pubmed-v1/cumulative",
        queue_file_path: "/app/data/corpora/rlalab-pubmed-v1/cumulative/reports/acquisition_queue.jsonl",
        exists: true,
        record_count: 1,
        records: [
          {
            document_id: "pmid:123",
            pmid: "123",
            pmc_id: "PMC123",
            doi: "10.1000/example",
            candidate_url: "https://example.org/article",
            candidate_pdf_url: "https://example.org/article.pdf",
            priority: "low",
            route: "pmc",
          },
          {
            document_id: "pmid:999",
            pmid: "999",
            pmc_id: "PMC999",
            doi: "10.1000/high",
            candidate_url: "https://example.org/high-priority",
            priority: "high",
            route: "doi",
          },
        ],
        parse_errors: [],
      },
    ]);

    render(<AdminAcquisitionQueueClient />);

    expect(await screen.findByText("10.1000/example")).toBeInTheDocument();
    expect(screen.getByText("reports/acquisition_queue.jsonl")).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "document id" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "pmid" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "pmc id" })).not.toBeInTheDocument();
    expect(screen.queryByText("pmid:123")).not.toBeInTheDocument();

    const openLinks = screen.getAllByRole("link", { name: "Open" });
    expect(openLinks[0]).toHaveAttribute("href", "https://example.org/high-priority");
    expect(openLinks[0]).toHaveAttribute("target", "_blank");
    expect(openLinks[1]).toHaveAttribute("href", "https://example.org/article");
    expect(openLinks[2]).toHaveAttribute("href", "https://example.org/article.pdf");

    const downloadLinks = screen.getAllByRole("link", { name: "Download" });
    expect(downloadLinks[0]).toHaveAttribute("download");
    expect(downloadLinks[1]).toHaveAttribute("download");

    fireEvent.click(screen.getByRole("button", { name: "To CSV" }));
    await waitFor(() => {
      expect(downloadIngestionAcquisitionReviewCsv).toHaveBeenCalledWith(
        "data/corpora/rlalab-pubmed-v1/cumulative"
      );
    });
  });
});
