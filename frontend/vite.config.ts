/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

// Served by FastAPI at SLIDESONG_BASE (the root by default).
const base = process.env.SLIDESONG_BASE ?? "/";
const api = process.env.SLIDESONG_API ?? "http://127.0.0.1:8096";

export default defineConfig({
  base,
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    host: true,
    port: 5196,
    proxy: { "/api": api, "/static": api },
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
    css: false,
    globals: true,
  },
});
