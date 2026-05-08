export type ActorType = "human" | "service" | "agent" | "provider" | "github_app";
export type PrincipalType = "session";

export type Actor = {
  actorId: "human:default";
  actorType: Extract<ActorType, "human">;
  displayName: string;
};

export type Principal = {
  principalType: PrincipalType;
  principalId: "session";
};

export type SessionClaims = {
  actor_id: "human:default";
  principal_type: PrincipalType;
  exp: number;
};

export type DevSession = {
  actor: Actor;
  principal: Principal;
  expiresAt: Date;
  claims: SessionClaims;
};

