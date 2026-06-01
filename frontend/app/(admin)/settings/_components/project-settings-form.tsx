"use client";

import { useActionState, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  updateAutonomyLevelAction,
  updateProjectProfileAction,
  type SettingsActionState
} from "../actions";

type AutonomyLevel = "L0" | "L1" | "L2" | "L3";

type ProjectSettingsFormProps = {
  projectId: string;
  name: string;
  description: string | null;
  autonomyLevel: AutonomyLevel;
  policyProfile: string;
};

const INITIAL_STATE: SettingsActionState = { kind: "idle" };

const AUTONOMY_DESCRIPTIONS: Record<string, string> = {
  L0: "完全手動。AI は提案のみ、すべて承認が必要。",
  L1: "低リスク操作の一部を自動化 (承認ゲートは維持)。",
  L2: "中リスクまで自動化 (レビュー artifact 必須)。",
  L3: "高自律。AI が広い範囲を自動実行 (監査で追跡)。"
};

function StatusMessage({ state }: { state: SettingsActionState }) {
  if (state.kind === "error") {
    return (
      <p role="status" className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">
        {state.message}
      </p>
    );
  }
  if (state.kind === "ok") {
    return (
      <p role="status" className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
        {state.message}
      </p>
    );
  }
  return null;
}

export function ProjectSettingsForm({
  projectId,
  name,
  description,
  autonomyLevel,
  policyProfile
}: ProjectSettingsFormProps) {
  const router = useRouter();

  // Codex adversarial R4/R5 (MEDIUM): 基本情報フォームは name / description を両方持つが、
  // ユーザーが実際に編集した (touch した) field だけを送信する。これにより stale なタブから
  // 未編集 field を送って他方の更新を巻き戻す lost update を防ぐ。値の prop 比較ではなく
  // dirty flag (onChange で立つ) で判定するため、router.refresh() 後に server props だけが
  // 更新され uncontrolled input の DOM 値が古いままでも、未編集 field は送信されない (R5)。
  // name を空にした場合は touch 済みなので送信され、server action 側で検証エラーになる (R2)。
  const [nameDirty, setNameDirty] = useState(false);
  const [descriptionDirty, setDescriptionDirty] = useState(false);

  // Codex adversarial R6/R7 (HIGH): autonomy_level は AI 権限制御。controlled state で管理し、
  // server 値 (prop) が変わったら state を同期して stale な未保存選択を破棄する。これにより
  // 別タブ / refresh で server が下位レベルへ下がった後に古い高レベルを再送する permission
  // re-escalation を防ぐ。dirty は state と server baseline の差分で導出する。
  const [autonomyValue, setAutonomyValue] = useState<AutonomyLevel>(autonomyLevel);
  const [autonomyServerBaseline, setAutonomyServerBaseline] =
    useState<AutonomyLevel>(autonomyLevel);
  if (autonomyLevel !== autonomyServerBaseline) {
    // server 値が変わった (refresh / 別タブ更新) → controlled state を同期し古い選択を破棄。
    // render 中の state 調整 (React 公式パターン)。effect ではないため set-state-in-effect 非該当。
    setAutonomyServerBaseline(autonomyLevel);
    setAutonomyValue(autonomyLevel);
  }
  const autonomyDirty = autonomyValue !== autonomyLevel;

  const [profileState, profileAction, profilePending] = useActionState(
    async (
      prevState: SettingsActionState,
      formData: FormData
    ): Promise<SettingsActionState> => {
      const pruned = new FormData();
      pruned.set("project_id", projectId);
      let changed = false;

      if (nameDirty) {
        const submittedName = formData.get("name");
        if (typeof submittedName === "string") {
          pruned.set("name", submittedName);
          changed = true;
        }
      }

      if (descriptionDirty) {
        const submittedDescription = formData.get("description");
        if (typeof submittedDescription === "string") {
          pruned.set("description", submittedDescription);
          changed = true;
        }
      }

      if (!changed) {
        return { kind: "error", message: "変更する項目がありません" };
      }

      const result = await updateProjectProfileAction(prevState, pruned);
      if (result.kind === "ok") {
        // 保存成功後は dirty 状態をリセットし、次の未編集 submit で値が再送されないように
        // する (effect 内 setState を避けるため action callback 内でリセットする)。
        setNameDirty(false);
        setDescriptionDirty(false);
      }
      return result;
    },
    INITIAL_STATE
  );
  // ユーザーが実際に level を変更した場合のみ送信する。送信時は server compare-and-swap 用に
  // baseline (現在の server 値) も付与し、別タブ / retry で値が変わっていれば backend が
  // 409 で拒否する (re-escalation の二重防御)。dirty は controlled state の差分で導出するため、
  // refresh で server baseline が更新されれば古い選択は破棄され、未編集扱いとなる。
  const [autonomyState, autonomyAction, autonomyPending] = useActionState(
    async (
      prevState: SettingsActionState,
      formData: FormData
    ): Promise<SettingsActionState> => {
      if (!autonomyDirty) {
        return { kind: "error", message: "自律レベルは変更されていません" };
      }
      return updateAutonomyLevelAction(prevState, formData);
    },
    INITIAL_STATE
  );

  useEffect(() => {
    if (profileState.kind === "ok" || autonomyState.kind === "ok") {
      router.refresh();
    }
  }, [profileState, autonomyState, router]);

  return (
    <div className="grid gap-6">
      <form
        action={profileAction}
        className="grid gap-4"
        data-testid="project-profile-form"
      >
        <input type="hidden" name="project_id" value={projectId} />
        <fieldset className="grid gap-4" disabled={profilePending}>
          <legend className="sr-only">プロジェクト基本情報</legend>

          <label className="grid gap-2 text-sm">
            <span className="font-medium">プロジェクト名</span>
            <input
              name="name"
              defaultValue={name}
              onChange={() => setNameDirty(true)}
              className="rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            />
          </label>

          <label className="grid gap-2 text-sm">
            <span className="font-medium">説明</span>
            <textarea
              name="description"
              rows={3}
              defaultValue={description ?? ""}
              onChange={() => setDescriptionDirty(true)}
              className="min-h-20 resize-y rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            />
          </label>

          {/* S-1: 現在値の入力は印刷に残し、保存ボタン (mutation trigger) は印刷物に出さない */}
          <div className="no-print">
            <button
              type="submit"
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-accent/90 disabled:opacity-60"
            >
              {profilePending ? "保存中..." : "基本情報を保存"}
            </button>
          </div>
          <StatusMessage state={profileState} />
        </fieldset>
      </form>

      <form
        action={autonomyAction}
        className="grid gap-4 border-t border-line pt-6"
        data-testid="autonomy-level-form"
      >
        <input type="hidden" name="project_id" value={projectId} />
        {/* compare-and-swap baseline: ユーザーが編集の基にした現在の server 値。 */}
        <input type="hidden" name="expected_autonomy_level" value={autonomyLevel} />
        <fieldset className="grid gap-4" disabled={autonomyPending}>
          <legend className="text-sm font-medium">AI 自律レベル</legend>

          <label className="grid gap-2 text-sm">
            <span className="text-muted-foreground">
              autonomy_level (AI が自動実行できる範囲。変更は監査に記録されます)
            </span>
            <select
              name="autonomy_level"
              value={autonomyValue}
              onChange={(event) => setAutonomyValue(event.target.value as AutonomyLevel)}
              className="rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            >
              <option value="L0">L0 — 完全手動</option>
              <option value="L1">L1 — 低リスク自動化</option>
              <option value="L2">L2 — 中リスク自動化</option>
              <option value="L3">L3 — 高自律</option>
            </select>
            <span className="text-xs text-muted-foreground">
              {AUTONOMY_DESCRIPTIONS[autonomyValue] ?? ""}
            </span>
          </label>

          <div className="rounded-md border border-line bg-canvas p-3 text-xs">
            <span className="font-semibold text-muted-foreground">
              policy_profile (server-owned、autonomy_level から自動導出)
            </span>
            <p className="mt-1 font-mono text-ink">{policyProfile}</p>
            <p className="mt-1 text-muted-foreground">
              policy_profile は UI から直接変更できません。autonomy_level の変更に応じて
              サーバー側で解決されます。
            </p>
          </div>

          {/* S-1: 自律レベルの現在値は印刷に残し、保存ボタン (mutation trigger) は印刷物に出さない */}
          <div className="no-print">
            <button
              type="submit"
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-accent/90 disabled:opacity-60"
            >
              {autonomyPending ? "保存中..." : "自律レベルを保存"}
            </button>
          </div>
          <StatusMessage state={autonomyState} />
        </fieldset>
      </form>
    </div>
  );
}
