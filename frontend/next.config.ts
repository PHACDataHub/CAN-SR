import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  /* config options here */
  output: 'standalone',
  typescript: {
    // Disable TypeScript errors during builds for production deployment
    ignoreBuildErrors: true,
  },
  webpack(config, { dev }) {
    // Use inline source maps in development to avoid network fetches for TS sources
    // This prevents 404s like /_next/static/src/index.ts and /_next/static/src/utilities.ts
    if (dev) {
      config.devtool = 'eval-source-map'
    }
    return config
  },
  turbopack: {},
}

export default nextConfig
