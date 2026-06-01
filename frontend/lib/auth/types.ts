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
  // ADR-00043 (R-2): issued-at (= login 時刻、UNIX 秒)。表示専用 (最終ログイン日時)。
  // 既存 cookie (iat 無) や iat 不正は undefined。session 有効性には使わない (exp のみ)。
  iat?: number;
};

export type DevSession = {
  actor: Actor;
  principal: Principal;
  expiresAt: Date;
  // ADR-00043 (R-2): login 時刻 (iat 由来)。iat 無 cookie は null。
  issuedAt: Date | null;
  claims: SessionClaims;
};

