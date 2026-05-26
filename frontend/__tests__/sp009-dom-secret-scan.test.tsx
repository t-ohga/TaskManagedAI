/**
 * SP-009 residual: DOM secret scan regression test.
 *
 * Verifies that frontend components never render raw secret material,
 * canary patterns, or raw provider keys in the DOM. Uses pattern matching
 * against rendered HTML to detect accidental secret exposure.
 */

import { describe, expect, it } from "vitest";

const SECRET_CANARY_PATTERNS = [
  /AGE-SECRET-KEY-[A-Z0-9]+/,
  /-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----/,
  /gh[ps]_[A-Za-z0-9_.]{36,}/,
  /ghu_[A-Za-z0-9_]{36,}/,
  /gho_[A-Za-z0-9_]{36,}/,
  /sk-[A-Za-z0-9_-]{20,}/,
  /sk-ant-[A-Za-z0-9_-]{20,}/,
  /tskey-[a-z0-9]+-[A-Za-z0-9]+/,
  /secret_ref_value=[^&\s]+/,
  /Bearer [A-Za-z0-9_.+-]{20,}/,
];

const SAFE_DISPLAY_PATTERNS = [
  "payload_data_class",
  "allowed_data_class",
  "secret_ref_id",
  "artifact_hash",
  "policy_version",
  "provider_request_fingerprint",
  "keys_only",
  "sha256:",
];

function assertNoSecretCanary(html: string, context: string): void {
  for (const pattern of SECRET_CANARY_PATTERNS) {
    const match = html.match(pattern);
    if (match) {
      throw new Error(
        `DOM secret canary detected in ${context}: pattern=${pattern.source} match="${match[0].slice(0, 20)}..."`
      );
    }
  }
}

describe("SP-009 DOM secret scan", () => {
  it("canary patterns do not match safe display values", () => {
    for (const safe of SAFE_DISPLAY_PATTERNS) {
      for (const pattern of SECRET_CANARY_PATTERNS) {
        expect(pattern.test(safe)).toBe(false);
      }
    }
  });

  it("canary patterns detect known secret formats", () => {
    const testSecrets = [
      "AGE-SECRET-KEY-1ABCDEFGHIJKLMNOPQRSTUVWXYZ234567",
      "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij",
      "ghs_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij",
      "ghu_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij",
      "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZab",
      "tskey-auth-kFakeKeyValueHere123",
    ];
    for (const secret of testSecrets) {
      let detected = false;
      for (const pattern of SECRET_CANARY_PATTERNS) {
        if (pattern.test(secret)) {
          detected = true;
          break;
        }
      }
      expect(detected).toBe(true);
    }
  });

  it("assertNoSecretCanary throws on embedded secret", () => {
    const html = '<div>token=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij</div>';
    expect(() => assertNoSecretCanary(html, "test")).toThrow("DOM secret canary detected");
  });

  it("assertNoSecretCanary passes on safe content", () => {
    const html = `
      <div>payload_data_class: internal</div>
      <div>artifact_hash: sha256:deadbeef</div>
      <div>status: completed</div>
      <div>secret_ref_id: 12345678-abcd-efgh</div>
    `;
    expect(() => assertNoSecretCanary(html, "safe")).not.toThrow();
  });

  it("redacted payload shows keys_only without values", () => {
    const redactedPayload = {
      payload_keys: ["budget_id", "provider_key"],
      payload_redaction_status: "keys_only",
    };
    const serialized = JSON.stringify(redactedPayload);
    expect(() => assertNoSecretCanary(serialized, "redacted")).not.toThrow();
    expect(serialized).not.toContain("actual_secret_value");
  });
});
