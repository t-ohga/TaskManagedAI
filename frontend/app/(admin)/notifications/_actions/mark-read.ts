"use server";

import { revalidatePath } from "next/cache";

import { markNotificationRead } from "@/lib/api/notifications";

export async function markNotificationReadAction(formData: FormData) {
  const id = formData.get("notification_id");
  if (typeof id !== "string") {
    return;
  }

  await markNotificationRead(id);
  revalidatePath("/notifications");
  revalidatePath("/", "layout");
}

