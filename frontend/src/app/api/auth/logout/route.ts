import { NextResponse } from "next/server";

import { AUTH_COOKIE_NAME } from "@/lib/auth";
import { frontendConfig } from "@/lib/config";

export async function POST() {
  await fetch(`${frontendConfig.backendApiUrl}${frontendConfig.backendApiVersionPath}/auth/logout`, {
    method: "POST",
    cache: frontendConfig.requestCache,
  }).catch(() => undefined);

  const response = NextResponse.json({ ok: true });
  response.cookies.set({
    name: AUTH_COOKIE_NAME,
    value: "",
    httpOnly: frontendConfig.authCookieHttpOnly,
    sameSite: frontendConfig.authCookieSameSite,
    secure: frontendConfig.authCookieSecure,
    path: frontendConfig.authCookiePath,
    maxAge: 0,
  });
  return response;
}
