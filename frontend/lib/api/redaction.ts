import { z } from "zod";

/**
 * Frontend fail-closed guard for read-only event metadata responses.
 *
 * Backend endpoints should expose only payload key names and redaction status.
 * If a future API regression sends raw payload/value fields, reject the
 * response before any Server Component can render it into HTML.
 */
export const NoRawPayloadFieldsSchema = z.object({
  event_payload: z.never().optional(),
  payload: z.never().optional(),
  raw_payload: z.never().optional(),
  raw_event_payload: z.never().optional(),
  provider_response: z.never().optional(),
  raw_provider_response: z.never().optional(),
  raw_tool_args: z.never().optional(),
  tool_args: z.never().optional(),
  client_secret: z.never().optional(),
  client_secret_response: z.never().optional(),
  repo_state: z.never().optional(),
  tool_manifest: z.never().optional(),
  provider_request_fingerprint: z.never().optional(),
  secret: z.never().optional(),
  secret_value: z.never().optional(),
  api_key: z.never().optional(),
  auth_token: z.never().optional(),
  bearer_token: z.never().optional(),
  capability_token: z.never().optional(),
  github_installation_token: z.never().optional()
}).passthrough();
