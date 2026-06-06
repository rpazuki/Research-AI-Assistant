import type { NextConfig } from "next";

import { loadFrontendConfig } from "./src/lib/config";

const appConfig = loadFrontendConfig();

const nextConfig: NextConfig = {
  output: appConfig.nextOutput,
  env: {
    NEXT_PUBLIC_API_PROXY_PREFIX: appConfig.apiProxyPrefix,
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${appConfig.backendApiUrl}${appConfig.backendApiVersionPath}/:path*`,
      },
    ];
  },
};

export default nextConfig;
