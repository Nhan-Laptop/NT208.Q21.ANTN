/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    webpackBuildWorker: false,
  },
  async rewrites() {
    // Proxy backend APIs through Next so public demo (ngrok/domain) doesn't need direct backend exposure.
    // This avoids CORS and mixed-content issues when the frontend is served over HTTPS.
    const backend = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
    return [
      { source: "/api/v1/:path*", destination: `${backend}/api/v1/:path*` },
      { source: "/health", destination: `${backend}/health` },
    ];
  },
};

export default nextConfig;
