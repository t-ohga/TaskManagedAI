/**
 * SP-009 residual: DOM secret scan regression test.
 *
 * Canary patterns are aligned with backend canonical scanner
 * (backend/app/repositories/_payload_secret_scan.py _RAW_SECRET_PATTERNS).
 */

import { describe, expect, it } from "vitest";

const SECRET_CANARY_PATTERNS: [string, RegExp][] = [
  ["openai_api_key", /sk-[A-Za-z0-9]{20,}/],
  ["anthropic_api_key", /sk-ant-[A-Za-z0-9_-]{20,}/],
  ["github_installation_token", /ghs_[A-Za-z0-9]{20,}/],
  ["github_oauth_token", /gho_[A-Za-z0-9]{20,}/],
  ["github_personal_token", /ghp_[A-Za-z0-9]{20,}/],
  ["tailscale_auth_key", /tskey-[a-z0-9]{16,}-[a-z0-9]{16,}/],
  ["age_private_key", /AGE-SECRET-KEY-1[A-Z0-9]{50,}/],
  ["pem_private_key", /-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----/],
  ["bearer_header", /Bearer [A-Za-z0-9_.+-]{20,}/],
];

export function assertNoSecretCanary(html: string, context: string): void {
  for (const [kind, pattern] of SECRET_CANARY_PATTERNS) {
    const match = html.match(pattern);
    if (match) {
      throw new Error(
        `DOM secret canary detected in ${context}: kind=${kind} match="${match[0].slice(0, 20)}..."`
      );
    }
  }
}

describe("SP-009 DOM secret scan", () => {
  it("canary patterns aligned with backend canonical count", () => {
    expect(SECRET_CANARY_PATTERNS.length).toBe(9);
  });

  it("canary patterns detect known secret formats", () => {
    const testSecrets: [string, string][] = [
      ["openai", "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZab1234"],
      ["anthropic", "sk-ant-ABCDEFGHIJKLMNOPQRSTUVWXYZab"],
      ["github_install", "ghs_ABCDEFGHIJKLMNOPQRSTUVWXYZab"],
      ["github_oauth", "gho_ABCDEFGHIJKLMNOPQRSTUVWXYZab"],
      ["github_pat", "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZab"],
      ["tailscale", "tskey-abcdef1234567890-abcdef1234567890"],
      [
        "age",
        "AGE-SECRET-KEY-1ABCDEFGHIJKLMNOPQRSTUVWXYZ234567890ABCDEFGHIJKLMNOPQ",
      ],
    ];
    for (const [label, secret] of testSecrets) {
      let detected = false;
      for (const [, pattern] of SECRET_CANARY_PATTERNS) {
        if (pattern.test(secret)) {
          detected = true;
          break;
        }
      }
      expect(detected, `${label} should be detected`).toBe(true);
    }
  });

  it("safe display values are not flagged", () => {
    const safeValues = [
      "payload_data_class: internal",
      "allowed_data_class: confidential",
      "secret_ref_id: 12345678-abcd",
      "artifact_hash: sha256:deadbeef",
      "status: completed",
      "keys_only",
      "sk-short",
    ];
    for (const safe of safeValues) {
      expect(() => assertNoSecretCanary(safe, "safe")).not.toThrow();
    }
  });

  it("assertNoSecretCanary throws on embedded secret", () => {
    const html =
      '<div>token=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZab</div>';
    expect(() => assertNoSecretCanary(html, "test")).toThrow(
      "DOM secret canary detected"
    );
  });

  it("redacted payload keys_only format passes scan", () => {
    const redacted = JSON.stringify({
      payload_keys: ["budget_id", "provider_key"],
      payload_redaction_status: "keys_only",
    });
    expect(() => assertNoSecretCanary(redacted, "redacted")).not.toThrow();
  });
});
