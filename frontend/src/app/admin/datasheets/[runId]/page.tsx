import AdminDatasheetRunClient from "@/components/admin/AdminDatasheetRunClient";

export default async function AdminDatasheetRunPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  return <AdminDatasheetRunClient runId={runId} />;
}
