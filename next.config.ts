import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
  reactCompiler: true,
  serverExternalPackages: ["better-sqlite3"],
};

export default nextConfig;
