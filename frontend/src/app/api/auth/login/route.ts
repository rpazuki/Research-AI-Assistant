import { NextResponse } from "next/server";

import { AUTH_COOKIE_NAME } from "@/lib/auth";
import { frontendConfig } from "@/lib/config";

export async function POST(request: Request) {
  const body = await request.json();
  const response = await fetch(`${frontendConfig.backendApiUrl}${frontendConfig.backendApiVersionPath}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: frontendConfig.requestCache,
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    return NextResponse.json(payload, { status: response.status });
  }

  const nextResponse = NextResponse.json({ ok: true });
  nextResponse.cookies.set({
    name: AUTH_COOKIE_NAME,
    value: payload.access_token,
    httpOnly: frontendConfig.authCookieHttpOnly,
    sameSite: frontendConfig.authCookieSameSite,
    secure: frontendConfig.authCookieSecure,
    path: frontendConfig.authCookiePath,
    maxAge: payload.expires_in,
  });
  return nextResponse;
}
