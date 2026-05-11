import { redirect } from "next/navigation";

import { getAuthToken } from "@/lib/auth";

export default async function RootPage() {
  const token = await getAuthToken();
  redirect(token ? "/chat" : "/login");
}
