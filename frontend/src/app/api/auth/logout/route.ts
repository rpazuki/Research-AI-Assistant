import { NextResponse } from "next/server";

import { AUTH_COOKIE_NAME } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function POST() {
  await fetch(`${API_BASE}/api/v1/auth/logout`, {
    method: "POST",
    cache: "no-store",
  }).catch(() => undefined);

  const response = NextResponse.json({ ok: true });
  response.cookies.set({
    name: AUTH_COOKIE_NAME,
    value: "",
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 0,
  });
  return response;
}