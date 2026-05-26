/**
 * Shared secret canary patterns for E2E runtime DOM scan.
 *
 * Aligned with backend canonical scanner
 * (backend/app/repositories/_payload_secret_scan.py _RAW_SECRET_PATTERNS).
 */

import { expect, type Page } from "@playwright/test";

export const SECRET_CANARY_PATTERNS: [string, RegExp][] = [
  ["openai_api_key", /sk-[A-Za-z0-9]{20,}/],
  ["anthropic_api_key", /sk-ant-[A-Za-z0-9_-]{20,}/],
  ["github_installation_token", /ghs_[A-Za-z0-9]{20,}/],
  ["github_oauth_token", /gho_[A-Za-z0-9]{20,}/],
  ["github_personal_token", /ghp_[A-Za-z0-9]{20,}/],
  ["tailscale_auth_key", /tskey-[a-z0-9]{16,}-[a-z0-9]{16,}/],
  ["age_private_key", /AGE-SECRET-KEY-1[A-Z0-9]{50,}/],
  ["pem_private_key", /-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----/],
];

export async function assertPageNoSecretCanary(
  page: Page,
  context: string
): Promise<void> {
  const html = await page.content();
  for (const [kind, pattern] of SECRET_CANARY_PATTERNS) {
    const match = html.match(pattern);
    expect(
      match,
      `DOM secret canary detected on ${context}: kind=${kind} length=${match?.[0]?.length ?? 0}`
    ).toBeNull();
  }
}
