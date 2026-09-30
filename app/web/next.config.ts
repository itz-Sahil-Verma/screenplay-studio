import type { NextConfig } from "next";

// The UI talks to the FastAPI backend through a same-origin proxy, so there is no CORS to configure.
// Override with API_URL if the API runs elsewhere.
const API_URL = process.env.API_URL ?? "http://127.0.0.1:8010";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
};

export default nextConfig;
