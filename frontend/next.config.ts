import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  experimental: {
    typedRoutes: true,
    optimizePackageImports: ["zod"]
  }
};

export default nextConfig;

