import type { NextConfig } from "next";

// Static export: the app is fully client-side and served by nginx, which also proxies /api
// to the FastAPI backend (see nginx.conf.template). No Node server is needed in production.
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
  devIndicators: false,
};

export default nextConfig;
