import fs from "node:fs";
import path from "node:path";
import os from "node:os";

import { afterEach, describe, expect, it, vi } from "vitest";

async function loadConfigModule() {
  vi.resetModules();
  return import("./config");
}

function writeConfig(content: string) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rlalab-frontend-config-"));
  const file = path.join(dir, "frontend.yaml");
  fs.writeFileSync(file, content, "utf8");
  return file;
}

describe("frontend config", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("loads defaults from YAML", async () => {
    const file = writeConfig(`
defaults:
  app_environment: "local"
  backend_api_url: "http://localhost:9000"
  backend_api_version_path: "/api/v2"
  api_proxy_prefix: "/api/proxy"
  request_cache: "no-store"
  auth_cookie_name: "test_cookie"
  auth_cookie_http_only: true
  auth_cookie_same_site: "strict"
  auth_cookie_secure: false
  auth_cookie_path: "/"
  next_output: "standalone"
environments: {}
`);
    vi.stubEnv("FRONTEND_CONFIG_FILE", file);
    const { loadFrontendConfig } = await loadConfigModule();

    const config = loadFrontendConfig("local");

    expect(config.backendApiUrl).toBe("http://localhost:9000");
    expect(config.backendApiVersionPath).toBe("/api/v2");
    expect(config.apiProxyPrefix).toBe("/api/proxy");
    expect(config.authCookieName).toBe("test_cookie");
    expect(config.authCookieSameSite).toBe("strict");
  });

  it("merges environment sections and lets env vars override YAML", async () => {
    const file = writeConfig(`
defaults:
  app_environment: "local"
  backend_api_url: "http://localhost:8000"
  backend_api_version_path: "/api/v1"
  api_proxy_prefix: "/api/backend"
  request_cache: "no-store"
  auth_cookie_name: "dev_cookie"
  auth_cookie_http_only: true
  auth_cookie_same_site: "lax"
  auth_cookie_secure: false
  auth_cookie_path: "/"
  next_output: "standalone"
environments:
  server:
    app_environment: "server"
    backend_api_url: "http://backend:8000"
    auth_cookie_secure: true
`);
    vi.stubEnv("FRONTEND_CONFIG_FILE", file);
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://backend.example");
    const { loadFrontendConfig } = await loadConfigModule();

    const config = loadFrontendConfig("server");

    expect(config.appEnvironment).toBe("server");
    expect(config.backendApiUrl).toBe("https://backend.example");
    expect(config.authCookieSecure).toBe(true);
  });
  it("defaults to the local scenario when RLALAB_ENV is unset", async () => {
    const file = writeConfig(`
defaults:
  backend_api_url: "http://unused:1"
environments:
  local:
    backend_api_url: "http://localhost:8000"
  server:
    backend_api_url: "http://backend:8000"
`);
    vi.stubEnv("FRONTEND_CONFIG_FILE", file);
    vi.stubEnv("RLALAB_ENV", "");
    const { loadFrontendConfig } = await loadConfigModule();

    // Defaults serve the host: Compose always sets RLALAB_ENV, a bare shell cannot.
    expect(loadFrontendConfig().backendApiUrl).toBe("http://localhost:8000");
  });

  it("does not treat NODE_ENV=production as the server scenario", async () => {
    const file = writeConfig(`
defaults:
  backend_api_url: "http://unused:1"
environments:
  local:
    backend_api_url: "http://localhost:8000"
  server:
    backend_api_url: "http://backend:8000"
`);
    vi.stubEnv("FRONTEND_CONFIG_FILE", file);
    vi.stubEnv("RLALAB_ENV", "");
    // `next build` sets NODE_ENV=production; selecting `server` off that would bake a
    // Compose hostname into a locally built image.
    vi.stubEnv("NODE_ENV", "production");
    const { loadFrontendConfig } = await loadConfigModule();

    expect(loadFrontendConfig().backendApiUrl).toBe("http://localhost:8000");
  });
});
