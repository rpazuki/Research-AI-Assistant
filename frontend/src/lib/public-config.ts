export type PublicFrontendConfig = {
  apiProxyPrefix: string;
};

export function getPublicFrontendConfig(): PublicFrontendConfig {
  return {
    apiProxyPrefix: process.env.NEXT_PUBLIC_API_PROXY_PREFIX ?? "/api/backend",
  };
}
