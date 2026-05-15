/**
 * Shared dynamic route id validators for admin pages.
 *
 * F-P3R1-006 fix: extract UUID v1-v5 pattern so that both ticket and agent run
 * detail pages can validate caller-supplied path parameters from the same
 * canonical source. Future tightening or relaxation can stay in sync.
 *
 * server-owned-boundary invariant: dynamic route ids are caller-supplied input
 * and must be validated before being rendered or forwarded to any downstream
 * service. Invalid ids resolve to notFound() at the page level.
 */

export const UUID_V1_TO_V5_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
