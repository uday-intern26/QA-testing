/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Long try-on validate calls are proxied by app/api/v1/[...path]/route.ts
  // (rewrites drop socket after ~30–60s on that endpoint).
  experimental: {
    proxyTimeout: 300_000,
  },
};

module.exports = nextConfig;
