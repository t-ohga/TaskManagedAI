"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { fetchBackendJson } from "@/lib/api/client";
import { DEFAULT_PROJECT_ID, TicketReadSchema } from "@/lib/api/tickets";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const TicketUpdateFormSchema = z.object({
  ticket_id: z.string().regex(UUID_PATTERN, "ticket id format invalid"),
  title: z.string().trim().min(1).optional(),
  description: z.string().trim().optional(),
  status: z
    .enum(["open", "in_progress", "blocked", "review", "closed", "cancelled"])
    .optional(),
  priority: z.enum(["low", "medium", "high", "critical"]).optional()
});

export type UpdateTicketState =
  | { kind: "idle" }
  | { kind: "ok"; ticket_id: string }
  | { kind: "error"; message: string };

function nonEmpty(value: FormDataEntryValue | null): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

export async function updateTicketAction(
  _prevState: UpdateTicketState,
  formData: FormData
): Promise<UpdateTicketState> {
  const parsed = TicketUpdateFormSchema.safeParse({
    ticket_id: typeof formData.get("ticket_id") === "string" ? formData.get("ticket_id") : "",
    title: nonEmpty(formData.get("title")),
    description: nonEmpty(formData.get("description")),
    status: nonEmpty(formData.get("status")),
    priority: nonEmpty(formData.get("priority"))
  });

  if (!parsed.success) {
    return {
      kind: "error",
      message: parsed.error.issues.map((issue) => issue.message).join(", ")
    };
  }

  const { ticket_id, ...rest } = parsed.data;
  // Zod optional fields は undefined を残すので、undefined 排除
  const updatePayload: Record<string, string> = {};
  for (const [key, value] of Object.entries(rest)) {
    if (value !== undefined) {
      updatePayload[key] = value;
    }
  }

  if (Object.keys(updatePayload).length === 0) {
    return { kind: "error", message: "更新する項目を入力してください" };
  }

  try {
    const updated = await fetchBackendJson(
      `/api/v1/projects/${DEFAULT_PROJECT_ID}/tickets/${ticket_id}` as `/${string}`,
      TicketReadSchema,
      {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(updatePayload)
      }
    );
    revalidatePath(`/tickets/${ticket_id}`);
    revalidatePath("/tickets");
    return { kind: "ok", ticket_id: updated.id };
  } catch (error: unknown) {
    const message =
      error instanceof Error ? error.message : "Ticket update failed.";
    return { kind: "error", message };
  }
}
