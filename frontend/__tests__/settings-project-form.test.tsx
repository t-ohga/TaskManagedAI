import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProjectSettingsForm } from "../app/(admin)/settings/_components/project-settings-form";
import { fullReload } from "../lib/full-reload";
import type * as FullReloadModule from "../lib/full-reload";
import {
  updateAutonomyLevelAction,
  updateProjectProfileAction
} from "../app/(admin)/settings/actions";

// Server Action は vitest では実行しないため no-op に mock (useActionState 経由で参照される)
vi.mock("../app/(admin)/settings/actions", () => ({
  updateProjectProfileAction: vi.fn(async () => ({ kind: "idle" })),
  updateAutonomyLevelAction: vi.fn(async () => ({ kind: "idle" }))
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() })
}));

// C-5: useDeferredRouterRefresh は内部で fullReload (window.location.reload) を呼ぶため mock。
// confirmDiscardUnsavedDrafts は実ロジックを使い、saved-form-dirty による false confirm を検証する。
vi.mock("../lib/full-reload", async (importOriginal) => {
  const actual = await importOriginal<typeof FullReloadModule>();
  return { ...actual, fullReload: vi.fn() };
});

const PROJECT_ID = "00000000-0000-4000-8000-0000000cc001";

afterEach(() => {
  vi.clearAllMocks();
});

describe("ProjectSettingsForm (M-3 / ADR-00035)", () => {
  it("renders name / description editable fields with current values", () => {
    render(
      <ProjectSettingsForm
        projectId={PROJECT_ID}
        name="My Project"
        description="既存の説明"
        autonomyLevel="L1"
        policyProfile="default"
      />
    );

    const nameInput = screen.getByRole("textbox", { name: "プロジェクト名" });
    expect(nameInput).toHaveValue("My Project");

    const descInput = screen.getByRole("textbox", { name: "説明" });
    expect(descInput).toHaveValue("既存の説明");

    expect(
      screen.getByRole("button", { name: "基本情報を保存" })
    ).toBeInTheDocument();
  });

  it("renders autonomy_level selector with the current level selected", () => {
    render(
      <ProjectSettingsForm
        projectId={PROJECT_ID}
        name="My Project"
        description={null}
        autonomyLevel="L2"
        policyProfile="default"
      />
    );

    const select = screen.getByRole("combobox", { name: /autonomy_level/u });
    expect(select).toHaveValue("L2");
    // L0-L3 の 4 択が存在
    expect(screen.getByRole("option", { name: "L0 — 完全手動" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "L3 — 高自律" })).toBeInTheDocument();
  });

  it("displays policy_profile as read-only derived value (no editable control)", () => {
    render(
      <ProjectSettingsForm
        projectId={PROJECT_ID}
        name="My Project"
        description={null}
        autonomyLevel="L0"
        policyProfile="default"
      />
    );

    // policy_profile の実値が表示される
    expect(screen.getByText("default")).toBeVisible();
    // policy_profile を編集する input/select/textbox は存在しない (server-owned)
    const editControls = screen.getAllByRole("textbox");
    for (const control of editControls) {
      expect(control).not.toHaveAttribute("name", "policy_profile");
    }
    expect(
      screen.queryByRole("combobox", { name: /policy_profile/u })
    ).not.toBeInTheDocument();
    // 導出である旨の注記
    expect(
      screen.getByText(/policy_profile は UI から直接変更できません/u)
    ).toBeVisible();
  });

  it("includes project_id as a hidden field in both forms", () => {
    const { container } = render(
      <ProjectSettingsForm
        projectId={PROJECT_ID}
        name="My Project"
        description={null}
        autonomyLevel="L0"
        policyProfile="default"
      />
    );

    const hidden = container.querySelectorAll<HTMLInputElement>(
      'input[type="hidden"][name="project_id"]'
    );
    expect(hidden.length).toBe(2);
    for (const input of Array.from(hidden)) {
      expect(input.value).toBe(PROJECT_ID);
    }
  });

  // Codex adversarial R4 (MEDIUM): 未編集の name は送信せず、編集された field だけ送る
  // (stale なタブから未編集 field を送って他方の更新を巻き戻す lost update を防ぐ)。
  it("submits only the changed field, omitting an unedited name", async () => {
    render(
      <ProjectSettingsForm
        projectId={PROJECT_ID}
        name="My Project"
        description="旧説明"
        autonomyLevel="L1"
        policyProfile="default"
      />
    );

    // description だけ編集 (name は触らない)
    const descInput = screen.getByRole("textbox", { name: "説明" });
    fireEvent.change(descInput, { target: { value: "新説明" } });

    fireEvent.click(screen.getByRole("button", { name: "基本情報を保存" }));

    await waitFor(() => {
      expect(vi.mocked(updateProjectProfileAction)).toHaveBeenCalledTimes(1);
    });

    const sentFormData = vi.mocked(updateProjectProfileAction).mock.lastCall?.[1];
    expect(sentFormData).toBeInstanceOf(FormData);
    expect(sentFormData?.get("project_id")).toBe(PROJECT_ID);
    expect(sentFormData?.get("description")).toBe("新説明");
    // 未編集の name は送信しない
    expect(sentFormData?.has("name")).toBe(false);
  });

  it("sends the name field when it is cleared (so the server rejects a blank name)", async () => {
    render(
      <ProjectSettingsForm
        projectId={PROJECT_ID}
        name="My Project"
        description="旧説明"
        autonomyLevel="L1"
        policyProfile="default"
      />
    );

    const nameInput = screen.getByRole("textbox", { name: "プロジェクト名" });
    fireEvent.change(nameInput, { target: { value: "" } });

    fireEvent.click(screen.getByRole("button", { name: "基本情報を保存" }));

    await waitFor(() => {
      expect(vi.mocked(updateProjectProfileAction)).toHaveBeenCalledTimes(1);
    });

    const sentFormData = vi.mocked(updateProjectProfileAction).mock.lastCall?.[1];
    expect(sentFormData).toBeInstanceOf(FormData);
    // blank name は「変更あり」として送信され、server action 側で検証エラーになる
    expect(sentFormData?.get("name")).toBe("");
  });

  // Codex adversarial R5 (MEDIUM): router.refresh() 後に props.name だけ更新され
  // uncontrolled input の DOM 値が古いまま残っても、未編集の name は送信されない
  // (値比較ではなく touch/dirty で判定するため lost-update が再発しない)。
  it("does not resend an unedited name after a props update (refresh regression)", async () => {
    const { rerender } = render(
      <ProjectSettingsForm
        projectId={PROJECT_ID}
        name="Old Name"
        description="旧説明"
        autonomyLevel="L1"
        policyProfile="default"
      />
    );

    // server 側で name が更新され、refresh により props.name だけ新しくなる状況を再現
    rerender(
      <ProjectSettingsForm
        projectId={PROJECT_ID}
        name="Server New Name"
        description="旧説明"
        autonomyLevel="L1"
        policyProfile="default"
      />
    );

    // ユーザーは description だけ編集 (name は一度も触っていない)
    const descInput = screen.getByRole("textbox", { name: "説明" });
    fireEvent.change(descInput, { target: { value: "新説明" } });

    fireEvent.click(screen.getByRole("button", { name: "基本情報を保存" }));

    await waitFor(() => {
      expect(vi.mocked(updateProjectProfileAction)).toHaveBeenCalledTimes(1);
    });

    const sentFormData = vi.mocked(updateProjectProfileAction).mock.lastCall?.[1];
    expect(sentFormData).toBeInstanceOf(FormData);
    expect(sentFormData?.get("description")).toBe("新説明");
    // props 更新後でも未編集 name は送らない (server の new name を revert しない)
    expect(sentFormData?.has("name")).toBe(false);
  });
});

describe("ProjectSettingsForm autonomy dirty guard (M-3 / ADR-00035, Codex R6 HIGH)", () => {
  it("does not submit autonomy_level when the selector was not changed", async () => {
    render(
      <ProjectSettingsForm
        projectId={PROJECT_ID}
        name="My Project"
        description={null}
        autonomyLevel="L3"
        policyProfile="default"
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "自律レベルを保存" }));

    await waitFor(() => {
      expect(screen.getByText("自律レベルは変更されていません")).toBeVisible();
    });
    // 未編集 (stale な高レベルの再送) では server action を呼ばない (re-escalation 防止)
    expect(vi.mocked(updateAutonomyLevelAction)).not.toHaveBeenCalled();
  });

  it("submits autonomy_level only after the selector is changed", async () => {
    render(
      <ProjectSettingsForm
        projectId={PROJECT_ID}
        name="My Project"
        description={null}
        autonomyLevel="L0"
        policyProfile="default"
      />
    );

    const select = screen.getByRole("combobox", { name: /autonomy_level/u });
    fireEvent.change(select, { target: { value: "L2" } });

    fireEvent.click(screen.getByRole("button", { name: "自律レベルを保存" }));

    await waitFor(() => {
      expect(vi.mocked(updateAutonomyLevelAction)).toHaveBeenCalledTimes(1);
    });
  });

  it("does not resend a stale autonomy level after a props update (re-escalation guard)", async () => {
    const { rerender } = render(
      <ProjectSettingsForm
        projectId={PROJECT_ID}
        name="My Project"
        description={null}
        autonomyLevel="L3"
        policyProfile="default"
      />
    );

    // server 側で L0 に下がり、refresh で props.autonomyLevel だけ更新される状況を再現
    // (uncontrolled select の DOM は L3 のまま残りうる)
    rerender(
      <ProjectSettingsForm
        projectId={PROJECT_ID}
        name="My Project"
        description={null}
        autonomyLevel="L0"
        policyProfile="default"
      />
    );

    // ユーザーは selector を触っていない
    fireEvent.click(screen.getByRole("button", { name: "自律レベルを保存" }));

    await waitFor(() => {
      expect(screen.getByText("自律レベルは変更されていません")).toBeVisible();
    });
    // stale な L3 を再送して server の L0 を巻き戻さない
    expect(vi.mocked(updateAutonomyLevelAction)).not.toHaveBeenCalled();
  });

  // C-5 adversarial finding: 保存成功した autonomy form 自身が dirty のまま残ると、reload 直前の
  // confirmDiscardUnsavedDrafts が自分自身を未保存と誤検知し full reload を止めてしまう。
  // 保存成功で自分の dirty を解除し、他に draft が無ければ confirm なしで reload へ進むことを固定する。
  it("clears its own dirty after a successful autonomy save so reload is not blocked by a false confirm", async () => {
    vi.mocked(updateAutonomyLevelAction).mockResolvedValueOnce({
      kind: "ok",
      message: "更新しました"
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    const { container } = render(
      <ProjectSettingsForm
        projectId={PROJECT_ID}
        name="My Project"
        description={null}
        autonomyLevel="L0"
        policyProfile="default"
      />
    );

    const select = screen.getByRole("combobox", { name: /autonomy_level/u });
    fireEvent.change(select, { target: { value: "L2" } });

    const autonomyForm = container.querySelector('[data-testid="autonomy-level-form"]');
    expect(autonomyForm).toHaveAttribute("data-dirty", "true");

    fireEvent.click(screen.getByRole("button", { name: "自律レベルを保存" }));

    await waitFor(() => {
      expect(vi.mocked(updateAutonomyLevelAction)).toHaveBeenCalledTimes(1);
    });
    // 保存成功で自分の dirty は解除される (修正前: dirty のまま残り false confirm を誘発)
    await waitFor(() => {
      expect(autonomyForm).not.toHaveAttribute("data-dirty");
    });
    // 他に未保存 draft が無いので、reload 直前の破棄確認は出ず full reload へ進む
    await waitFor(() => {
      expect(vi.mocked(fullReload)).toHaveBeenCalled();
    });
    expect(confirmSpy).not.toHaveBeenCalled();

    confirmSpy.mockRestore();
  });
});

describe("ProjectSettingsForm autonomy lock-after-save (Codex adversarial R9 HIGH)", () => {
  // R9: 保存済み値を CAS baseline に流用すると、server が元値へ戻る soft-refresh で saved を解除できず
  // CAS expected が汚染され AI 権限制御が編集不能になる穴がある。対策として CAS expected は常に prop を
  // 送り、保存成功後は form を lock (reload/remount で解除) して stale baseline からの chained edit を
  // 物理禁止する。本 test はその 2 点 (expected=prop / 保存後 lock) を固定する。
  it("CAS expected は常に prop を送り、保存成功後は form を lock して chained edit を禁止する", async () => {
    vi.mocked(updateAutonomyLevelAction).mockResolvedValue({ kind: "ok", message: "更新しました" });

    const { container } = render(
      <ProjectSettingsForm
        projectId={PROJECT_ID}
        name="My Project"
        description={null}
        autonomyLevel="L0"
        policyProfile="default"
      />
    );

    const select = screen.getByRole("combobox", { name: /autonomy_level/u });
    const expectedInput = () =>
      container.querySelector('input[name="expected_autonomy_level"]');

    // 初期: prop が CAS expected、form は編集可。
    expect(expectedInput()).toHaveValue("L0");
    expect(select).toBeEnabled();

    // L0 → L2 へ変更して保存成功。
    fireEvent.change(select, { target: { value: "L2" } });
    fireEvent.click(screen.getByRole("button", { name: "自律レベルを保存" }));
    await waitFor(() =>
      expect(vi.mocked(updateAutonomyLevelAction)).toHaveBeenCalledTimes(1)
    );

    // 1 回目 submit の CAS expected は server 由来の prop (L0)、saved 値で汚染しない。
    const firstFormData = vi.mocked(updateAutonomyLevelAction).mock.calls[0]?.[1] as
      | FormData
      | undefined;
    expect(firstFormData?.get("expected_autonomy_level")).toBe("L0");
    expect(firstFormData?.get("autonomy_level")).toBe("L2");

    // 保存後 (reload は mock で no-op = reload 拒否相当) は form が lock され、select / 保存ボタンが
    // disabled になる → stale baseline からの chained CAS edit が物理的に不能。
    await waitFor(() => expect(select).toBeDisabled());
    expect(screen.getByRole("button", { name: "自律レベルを保存" })).toBeDisabled();
    // 再読み込みを促すメッセージを表示する。
    expect(screen.getByText(/続けて変更するにはページを再読み込み/u)).toBeVisible();
    // CAS expected は prop のまま (L2 に汚染されない)。
    expect(expectedInput()).toHaveValue("L0");
  });

  // lock の解除 (server prop が真に更新されたら resync して再び編集可能) は、prop 更新時の
  // controlled state 同期を検証する既存 test "does not resend a stale autonomy level after a
  // props update" がカバーする (resync block が autonomySaved=null も同時にクリアし lock を外す)。
});
