/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  env: {
    WEBSOCKET_PORT: process.env.WEBSOCKET_PORT || '8765',
    NEXT_PUBLIC_API_URL: process.env.API_URL || 'http://localhost:8765',
  },
};
module.exports = nextConfig;
