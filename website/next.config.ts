import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
  reactCompiler: true,
  serverExternalPackages: ["better-sqlite3"],
};

export default nextConfig;
