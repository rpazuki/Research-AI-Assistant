import AdminUserClient from "@/components/admin/AdminUserClient";

export default async function AdminUserPage({
  params,
}: {
  params: Promise<{ userId: string }>;
}) {
  const { userId } = await params;
  return <AdminUserClient userId={userId} />;
}
