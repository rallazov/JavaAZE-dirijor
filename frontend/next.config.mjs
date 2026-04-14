/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Polling avoids native file watchers; helps when macOS hits EMFILE ("too many open files")
  // and leaves .next in a broken state where every route 404s.
  webpack: (config, { dev }) => {
    if (dev) {
      config.watchOptions = {
        ...config.watchOptions,
        poll: 1000,
        aggregateTimeout: 300,
      };
    }
    return config;
  },
};

export default nextConfig;
