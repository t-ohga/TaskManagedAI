"use client";

import { useRouter, useSearchParams } from "next/navigation";

import { TagChip } from "@/components/tag-chip";
import type { TagRead } from "@/lib/domain/tag";

/**
 * ADR-00044 (A-5): ticket 一覧の tag 絞り込み。選択した tag を `?tag=<tag_id>` に反映し、
 * page 側が backend の `?tag_id=` query で絞り込む (client-side filter は limit=200 を超えた tag 付き
 * ticket を silent に隠すため不採用、Codex frontend R1 HIGH)。選択中タグの再クリックで解除。
 * tag が 0 件なら何も描画しない。
 */
export function TagFilter({ tags }: { tags: TagRead[] }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const current = searchParams.get("tag") ?? "";

  function setTag(tagId: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (tagId && tagId !== current) {
      params.set("tag", tagId);
    } else {
      params.delete("tag");
    }
    router.push(`?${params.toString()}`);
  }

  if (tags.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="タグで絞り込み">
      <span className="text-xs text-muted-foreground">タグ:</span>
      {tags.map((tag) => {
        const active = current === tag.id;
        return (
          <button
            key={tag.id}
            type="button"
            aria-pressed={active}
            aria-label={`タグ「${tag.name}」で絞り込み`}
            onClick={() => setTag(tag.id)}
            className="rounded-full transition"
          >
            <TagChip
              name={tag.name}
              color={tag.color}
              className={active ? "ring-2 ring-offset-1 ring-accent" : "opacity-50 hover:opacity-100"}
            />
          </button>
        );
      })}
      {current ? (
        <button
          type="button"
          onClick={() => setTag("")}
          className="text-xs text-muted-foreground underline hover:text-foreground"
        >
          クリア
        </button>
      ) : null}
    </div>
  );
}
