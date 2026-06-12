import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3900";
const backendURL = process.env.PLAYWRIGHT_BACKEND_URL ?? "http://127.0.0.1:8000";
const devLoginToken =
  process.env.TASKMANAGEDAI_DEV_LOGIN_TOKEN ??
  process.env.DEV_LOGIN_TOKEN ??
  "dev-login-token";
const devLoginCookieSecret =
  process.env.TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET ??
  process.env.DEV_LOGIN_COOKIE_SECRET ??
  "dev-login-cookie-secret";
const databaseURL =
  process.env.TASKMANAGEDAI_DATABASE_URL ??
  "postgresql+asyncpg://taskmanagedai:test-password@127.0.0.1:5432/taskmanagedai";
const redisURL = process.env.TASKMANAGEDAI_REDIS_URL ?? "redis://127.0.0.1:6379/0";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL,
    trace: "on-first-retry",
    // E2E では admin layout の feature tour overlay を抑止する。初回 localStorage 未設定だと
    // tour modal が表示され、duplicate heading (h2#feature-tour-title) による strict-mode 違反 /
    // a11y 違反 / click 妨害を引き起こすため、completed flag を全 test に pre-seed する
    // (lib/feature-tour.ts の TOUR_STORAGE_KEY="taskmanagedai.feature-tour.completed" /
    // TOUR_VERSION="1" と一致)。cookies は空なので login flow (未認証開始) には影響しない。
    storageState: {
      cookies: [],
      origins: [
        {
          origin: baseURL,
          localStorage: [
            { name: "taskmanagedai.feature-tour.completed", value: "1" }
          ]
        }
      ]
    }
  },
  webServer: [
    {
      command:
        "uv run uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000",
      url: `${backendURL}/healthz`,
      reuseExistingServer: true,
      timeout: 120_000,
      cwd: "..",
      env: {
        TASKMANAGEDAI_ENVIRONMENT: "test",
        TASKMANAGEDAI_API_HOST: "127.0.0.1",
        TASKMANAGEDAI_DATABASE_URL: databaseURL,
        TASKMANAGEDAI_REDIS_URL: redisURL,
        TASKMANAGEDAI_DEV_LOGIN_TOKEN: devLoginToken,
        TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET: devLoginCookieSecret
      }
    },
    {
      command: "pnpm dev --hostname 127.0.0.1 --port 3900",
      url: baseURL,
      reuseExistingServer: true,
      timeout: 120_000,
      env: {
        INTERNAL_API_URL: backendURL,
        TASKMANAGEDAI_INTERNAL_API_URL: backendURL,
        DEV_LOGIN_TOKEN: devLoginToken,
        TASKMANAGEDAI_DEV_LOGIN_TOKEN: devLoginToken,
        DEV_LOGIN_COOKIE_SECRET: devLoginCookieSecret,
        TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET: devLoginCookieSecret
      }
    }
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] }
    },
    {
      name: "mobile-chromium",
      use: { ...devices["Pixel 7"] }
    }
  ]
});

