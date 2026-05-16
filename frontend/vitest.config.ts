import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": new URL(".", import.meta.url).pathname,
      // Server Components mark themselves with `import "server-only"`. The
      // package is a build-time guard with no runtime API; alias to an
      // empty stub so vitest (jsdom env) can resolve the import.
      "server-only": new URL("./vitest.server-only-stub.ts", import.meta.url).pathname
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

