"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { fetchBackendJson } from "@/lib/api/client";
import { getCurrentProjectId } from "@/lib/api/session";
import { TicketReadSchema } from "@/lib/api/tickets";

const SLUG_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/;

const TicketCreateFormSchema = z.object({
  slug: z.string().trim().min(1).regex(SLUG_PATTERN, "slug は kebab-case (a-z0-9 + hyphen)"),
  title: z.string().trim().min(1, "title 必須"),
  description: z.string().trim().optional(),
  status: z
    .enum(["open", "in_progress", "blocked", "review", "closed", "cancelled"])
    .default("open"),
  priority: z.enum(["low", "medium", "high", "critical"]).optional()
});

export type CreateTicketState =
  | { kind: "idle" }
  | { kind: "ok"; ticket_id: string }
  | { kind: "error"; message: string };

export async function createTicketAction(
  _prevState: CreateTicketState,
  formData: FormData
): Promise<CreateTicketState> {
  const rawDescription = formData.get("description");
  const rawPriority = formData.get("priority");
  const rawStatus = formData.get("status");
  const parsed = TicketCreateFormSchema.safeParse({
    slug: typeof formData.get("slug") === "string" ? formData.get("slug") : "",
    title: typeof formData.get("title") === "string" ? formData.get("title") : "",
    description:
      typeof rawDescription === "string" && rawDescription.length > 0
        ? rawDescription
        : undefined,
    status:
      typeof rawStatus === "string" && rawStatus.length > 0 ? rawStatus : "open",
    priority:
      typeof rawPriority === "string" && rawPriority.length > 0
        ? rawPriority
        : undefined
  });

  if (!parsed.success) {
    return {
      kind: "error",
      message: parsed.error.issues.map((issue) => issue.message).join(", ")
    };
  }

  try {
    // SP-012-11.1 BL-TCU-014: session 経由 project resolve (DEFAULT_PROJECT_ID hardcode 解除)
    const projectId = await getCurrentProjectId();
    const created = await fetchBackendJson(
      `/api/v1/projects/${projectId}/tickets` as `/${string}`,
      TicketReadSchema,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(parsed.data)
      }
    );
    revalidatePath("/tickets");
    return { kind: "ok", ticket_id: created.id };
  } catch (error: unknown) {
    const message =
      error instanceof Error ? error.message : "Ticket creation failed.";
    return { kind: "error", message };
  }
}
