import { defineConfig } from "vite";
import fs from "node:fs";
import https from "node:https";
// Optional loopback-only operator preview. Production static build needs no private files.
export default defineConfig(({ command }) => ({
  server:
    command === "serve" && process.env.ACTIVITY_PREVIEW_CA
      ? {
          host: "127.0.0.1",
          proxy: {
            "/api": {
              target: "https://192.0.2.1",
              changeOrigin: true,
              agent: new https.Agent({
                ca: fs.readFileSync(process.env.ACTIVITY_PREVIEW_CA),
                servername: "example.invalid",
              }),
              configure(proxy) {
                proxy.on("proxyReq", (req) => {
                  req.setHeader("Origin", "https://example.invalid");
                  req.setHeader("Host", "example.invalid");
                });
              },
            },
          },
        }
      : undefined,
}));
