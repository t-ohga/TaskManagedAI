"use server";

import { revalidatePath } from "next/cache";

import {
  AutonomyLevelSchema,
  updateProjectAutonomyLevel
} from "@/lib/api/session";

export async function updateProjectAutonomyLevelAction(formData: FormData): Promise<void> {
  const projectId = String(formData.get("project_id") ?? "");
  const autonomyLevel = AutonomyLevelSchema.parse(formData.get("autonomy_level"));
  await updateProjectAutonomyLevel(projectId, autonomyLevel);
  revalidatePath("/settings");
}
