export const TOOL_ALLOWED_ACTIONS = [
  "web_fetch",
  "docs_search",
  "code_grep",
  "filesystem_read",
] as const;

export type ToolAllowedAction = (typeof TOOL_ALLOWED_ACTIONS)[number];

export const TOOL_TRUST_TIERS = [
  "official",
  "self_hosted",
  "third_party",
  "experimental",
] as const;

export type ToolTrustTier = (typeof TOOL_TRUST_TIERS)[number];

export const TOOL_PAYLOAD_DATA_CLASSES = [
  "public",
  "internal",
  "confidential",
  "pii",
] as const;

export type ToolPayloadDataClass = (typeof TOOL_PAYLOAD_DATA_CLASSES)[number];
