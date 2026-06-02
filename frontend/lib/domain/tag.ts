import { z } from "zod";

/**
 * ADR-00044 (A-5): tag の client-safe な palette / schema / 型。
 *
 * **Client Component から import されるため `next/headers` 等 server-only 依存を持たない**
 * (Codex frontend R1 HIGH)。fetch 関数 (cookies 依存) は `@/lib/api/tags` に分離し、
 * Client Component は本 module だけを runtime import する。
 *
 * palette は backend `TAG_COLORS` (migration DB CHECK / ORM / Pydantic) と 5+ source 整合。
 */
export const TagColorEnum = z.enum([
  "slate",
  "red",
  "orange",
  "amber",
  "green",
  "teal",
  "blue",
  "purple",
  "pink"
]);

export type TagColor = z.infer<typeof TagColorEnum>;

export const TAG_COLORS: readonly TagColor[] = TagColorEnum.options;

export const TagReadSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  color: TagColorEnum
});

export type TagRead = z.infer<typeof TagReadSchema>;

export const TagListResponseSchema = z.object({
  items: z.array(TagReadSchema)
});

export type TagListResponse = z.infer<typeof TagListResponseSchema>;
