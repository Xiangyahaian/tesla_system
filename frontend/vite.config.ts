import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": new URL("./src", import.meta.url).pathname,
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:6006",
      "/manual": "http://127.0.0.1:6006",
      "/legacy": "http://127.0.0.1:6006",
      "/agent-console": "http://127.0.0.1:6006",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
