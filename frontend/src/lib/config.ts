import fs from "node:fs";
import path from "node:path";

import yaml from "js-yaml";

type RawConfig = Record<string, unknown>;

export type FrontendConfig = {
  appEnvironment: string;
  backendApiUrl: string;
  backendApiVersionPath: string;
  apiProxyPrefix: string;
  requestCache: RequestCache;
  authCookieName: string;
  authCookieHttpOnly: boolean;
  authCookieSameSite: "lax" | "strict" | "none";
  authCookieSecure: boolean;
  authCookiePath: string;
  nextOutput: "standalone" | undefined;
};

const cwd = process.cwd();
const FRONTEND_ROOT = path.basename(cwd) === "frontend" ? cwd : path.resolve(cwd, "frontend");
const DEFAULT_CONFIG_FILE = path.resolve(FRONTEND_ROOT, "configs/frontend.yaml");

function deepMerge(base: RawConfig, override: RawConfig): RawConfig {
  const merged: RawConfig = { ...base };
  for (const [key, value] of Object.entries(override)) {
    if (
      value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      merged[key] &&
      typeof merged[key] === "object" &&
      !Array.isArray(merged[key])
    ) {
      merged[key] = deepMerge(merged[key] as RawConfig, value as RawConfig);
    } else {
      merged[key] = value;
    }
  }
  return merged;
}

function envName() {
  return (
    process.env.FRONTEND_ENV ||
    process.env.APP_ENV ||
    process.env.NODE_ENV ||
    "development"
  );
}

function configPath() {
  return path.resolve(process.env.FRONTEND_CONFIG_FILE ?? DEFAULT_CONFIG_FILE);
}

function boolFromEnv(value: string | undefined): boolean | undefined {
  if (value === undefined) return undefined;
  return ["1", "true", "yes", "on"].includes(value.toLowerCase());
}

function readYamlConfig(environment = envName()): RawConfig {
  const filePath = configPath();
  if (!fs.existsSync(filePath)) {
    return {};
  }

  const parsed = (yaml.load(fs.readFileSync(filePath, "utf8")) ?? {}) as {
    defaults?: RawConfig;
    environments?: Record<string, RawConfig>;
  };
  const defaults = parsed.defaults ?? {};
  const selected = parsed.environments?.[environment] ?? {};
  return deepMerge(defaults, selected);
}

function stringValue(config: RawConfig, key: string, fallback: string) {
  const value = config[key];
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

function boolValue(config: RawConfig, key: string, fallback: boolean) {
  const value = config[key];
  return typeof value === "boolean" ? value : fallback;
}

export function loadFrontendConfig(environment = envName()): FrontendConfig {
  const fileConfig = readYamlConfig(environment);
  const secureOverride = boolFromEnv(process.env.FRONTEND_AUTH_COOKIE_SECURE);
  const nextOutput = stringValue(fileConfig, "next_output", "standalone");

  return {
    appEnvironment: stringValue(fileConfig, "app_environment", environment),
    backendApiUrl:
      process.env.NEXT_PUBLIC_API_URL ||
      process.env.BACKEND_API_URL ||
      stringValue(fileConfig, "backend_api_url", "http://localhost:8000"),
    backendApiVersionPath:
      process.env.FRONTEND_BACKEND_API_VERSION_PATH ||
      stringValue(fileConfig, "backend_api_version_path", "/api/v1"),
    apiProxyPrefix:
      process.env.NEXT_PUBLIC_API_PROXY_PREFIX ||
      stringValue(fileConfig, "api_proxy_prefix", "/api/backend"),
    requestCache: stringValue(fileConfig, "request_cache", "no-store") as RequestCache,
    authCookieName:
      process.env.FRONTEND_AUTH_COOKIE_NAME ||
      process.env.AUTH_COOKIE_NAME ||
      stringValue(fileConfig, "auth_cookie_name", "rlalab_access_token"),
    authCookieHttpOnly: boolValue(fileConfig, "auth_cookie_http_only", true),
    authCookieSameSite: stringValue(fileConfig, "auth_cookie_same_site", "lax") as
      | "lax"
      | "strict"
      | "none",
    authCookieSecure:
      secureOverride ?? boolValue(fileConfig, "auth_cookie_secure", environment === "production"),
    authCookiePath: stringValue(fileConfig, "auth_cookie_path", "/"),
    nextOutput: nextOutput === "standalone" ? "standalone" : undefined,
  };
}

export const frontendConfig = loadFrontendConfig();
