import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
  reactCompiler: true,
  serverExternalPackages: ["better-sqlite3"],
  // Monorepo: set tracing root to repo root so data/ is included in serverless bundles
  outputFileTracingRoot: path.resolve(__dirname, ".."),
  outputFileTracingIncludes: {
    "/**": ["data/**"],
  },
};

export default nextConfig;
