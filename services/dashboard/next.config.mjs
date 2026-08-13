/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Static export for deploy
  output: "export",
  // next/image won't work in static export without a loader
  images: {
    unoptimized: true,
    remotePatterns: [
      { protocol: "https", hostname: "images.unsplash.com" },
    ],
  },
  // Required when using output: "export" with App Router
  trailingSlash: true,
};

export default nextConfig;
