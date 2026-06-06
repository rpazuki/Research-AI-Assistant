import { cookies } from "next/headers";

import { frontendConfig } from "@/lib/config";

export const AUTH_COOKIE_NAME = frontendConfig.authCookieName;

export async function getAuthToken(): Promise<string | undefined> {
  const cookieStore = await cookies();
  return cookieStore.get(AUTH_COOKIE_NAME)?.value;
}
