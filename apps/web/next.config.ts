import type { NextConfig } from "next";
import { existsSync } from "node:fs";
import { loadEnvFile } from "node:process";
import { fileURLToPath } from "node:url";

const localEnvironment = new URL("../../.env.local", import.meta.url);
if (existsSync(localEnvironment)) loadEnvFile(fileURLToPath(localEnvironment));
const config: NextConfig = {
  async rewrites() {
    return process.env.POKER_API_ORIGIN
      ? [
          {
            source: "/api/v1/:path*",
            destination: `${process.env.POKER_API_ORIGIN}/api/v1/:path*`,
          },
        ]
      : [];
  },
};
export default config;
