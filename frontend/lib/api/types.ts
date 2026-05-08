import { z } from "zod";

export const healthResponseSchema = z.object({
  status: z.literal("ok"),
  version: z.string().min(1),
  service: z.literal("api")
});

export type HealthResponse = z.infer<typeof healthResponseSchema>;

