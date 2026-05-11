import { cookies } from "next/headers";

export const AUTH_COOKIE_NAME = "rlalab_access_token";

export async function getAuthToken(): Promise<string | undefined> {
  const cookieStore = await cookies();
  return cookieStore.get(AUTH_COOKIE_NAME)?.value;
}