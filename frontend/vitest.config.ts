import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": new URL(".", import.meta.url).pathname
    }
  },
  test: {
    css: true,
    environment: "jsdom",
    globals: true,
    include: ["__tests__/**/*.{test,spec}.{ts,tsx}"],
    restoreMocks: true,
    setupFiles: ["./vitest.setup.ts"],
    unstubEnvs: true
  }
});

