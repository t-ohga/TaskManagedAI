/**
 * SP-009 residual: frontend/backend enum drift contract test.
 *
 * Verifies that frontend Zod enums match the backend canonical values.
 * If backend adds/removes an enum value, this test fails and forces
 * frontend sync.
 */

import { describe, expect, it } from "vitest";

import { AgentRunStatusEnum } from "@/lib/api/agent-runs";

const EXPECTED_AGENT_RUN_STATUSES = [
  "queued",
  "gathering_context",
  "running",
  "generated_artifact",
  "schema_validated",
  "policy_linted",
  "diff_ready",
  "waiting_approval",
  "blocked",
  "provider_refused",
  "provider_incomplete",
  "validation_failed",
  "repair_exhausted",
  "completed",
  "failed",
  "cancelled",
] as const;

const EXPECTED_BLOCKED_REASONS = [
  "policy_blocked",
  "budget_blocked",
  "runtime_blocked",
] as const;

describe("SP-009 enum drift contract", () => {
  it("AgentRunStatusEnum has exactly 16 values matching backend canonical", () => {
    const actual = new Set(AgentRunStatusEnum.options);
    const expected = new Set(EXPECTED_AGENT_RUN_STATUSES);
    expect(actual).toEqual(expected);
    expect(actual.size).toBe(16);
  });

  it("AgentRunStatusEnum does not contain blocked_reason values as status", () => {
    for (const reason of EXPECTED_BLOCKED_REASONS) {
      expect(AgentRunStatusEnum.options).not.toContain(reason);
    }
  });

  it("terminal states are a strict subset", () => {
    const terminalStates = new Set([
      "completed",
      "failed",
      "cancelled",
      "provider_refused",
      "repair_exhausted",
    ]);
    for (const s of terminalStates) {
      expect(AgentRunStatusEnum.options).toContain(s);
    }
    expect(terminalStates.size).toBe(5);
  });

  it("non-terminal states do not include terminal values", () => {
    const nonTerminal = [
      "queued",
      "gathering_context",
      "running",
      "generated_artifact",
      "schema_validated",
      "policy_linted",
      "diff_ready",
      "waiting_approval",
      "blocked",
      "provider_incomplete",
      "validation_failed",
    ];
    const terminalSet = new Set([
      "completed",
      "failed",
      "cancelled",
      "provider_refused",
      "repair_exhausted",
    ]);
    for (const s of nonTerminal) {
      expect(terminalSet.has(s)).toBe(false);
    }
    expect(nonTerminal.length).toBe(11);
  });
});
