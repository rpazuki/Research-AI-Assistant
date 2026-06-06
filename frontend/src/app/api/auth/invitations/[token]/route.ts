import { NextResponse } from "next/server";

import { frontendConfig } from "@/lib/config";

export async function GET(_request: Request, context: { params: Promise<{ token: string }> }) {
  const { token } = await context.params;
  const response = await fetch(`${frontendConfig.backendApiUrl}${frontendConfig.backendApiVersionPath}/auth/invitations/${token}`, {
    cache: frontendConfig.requestCache,
  });
  const body = await response.json().catch(() => ({}));
  return NextResponse.json(body, { status: response.status });
}

export async function POST(request: Request, context: { params: Promise<{ token: string }> }) {
  const { token } = await context.params;
  const response = await fetch(`${frontendConfig.backendApiUrl}${frontendConfig.backendApiVersionPath}/auth/invitations/${token}/accept`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
    cache: frontendConfig.requestCache,
  });
  const body = await response.json().catch(() => ({}));
  return NextResponse.json(body, { status: response.status });
}
