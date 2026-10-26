import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // output: "standalone",
  allowedDevOrigins: ["127.0.0.1"],
  // Static export for Cloudflare Pages (see scripts/build-static.mjs); the BFF is a Pages Function there.
  ...(process.env.STATIC_EXPORT === "1" ? { output: "export" as const, images: { unoptimized: true } } : {}),
};

export default nextConfig;
