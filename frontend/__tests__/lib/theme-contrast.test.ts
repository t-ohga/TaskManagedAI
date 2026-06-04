import { describe, expect, it } from "vitest";

// M-2 (ADR-00047 / Codex adversarial F-E2): dark テーマの semantic token が、通常文字サイズで WCAG 2.2 AA
// (4.5:1) を満たすことの回帰テスト。globals.css の `.dark` token 値と同期する (drift 検知)。
// 値を変えるときは本テストも更新し、AA を割らないことを保証する。

// globals.css `.dark` の token 値 (light surface 上の文字ではなく dark surface 上の文字を想定)。
const DARK = {
  canvas: "#0f1419",
  panel: "#192734",
  ink: "#e1e8ed",
  muted: "#8899a6",
  accent: "#2dd4bf",
  attention: "#f59e0b",
  // bg-danger ボタンの塗り (上に白文字)。
  dangerFill: "#dc2626",
  // text-danger の dark override (panel/canvas 上の文字)。
  dangerText: "#f87171",
  white: "#ffffff"
} as const;

function channelLuminance(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

function relativeLuminance(hex: string): number {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  const rHex = m?.[1];
  const gHex = m?.[2];
  const bHex = m?.[3];
  if (rHex === undefined || gHex === undefined || bHex === undefined) {
    throw new Error(`invalid hex: ${hex}`);
  }
  const r = channelLuminance(parseInt(rHex, 16));
  const g = channelLuminance(parseInt(gHex, 16));
  const b = channelLuminance(parseInt(bHex, 16));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

const AA_NORMAL = 4.5;

describe("dark theme token contrast (WCAG 2.2 AA, normal text)", () => {
  it("本文・補助テキスト token は dark panel 上で AA を満たす", () => {
    expect(contrast(DARK.ink, DARK.panel)).toBeGreaterThanOrEqual(AA_NORMAL);
    expect(contrast(DARK.muted, DARK.panel)).toBeGreaterThanOrEqual(AA_NORMAL);
  });

  it("accent / attention text は dark panel 上で AA を満たす", () => {
    expect(contrast(DARK.accent, DARK.panel)).toBeGreaterThanOrEqual(AA_NORMAL);
    expect(contrast(DARK.attention, DARK.panel)).toBeGreaterThanOrEqual(AA_NORMAL);
  });

  it("text-danger (override) は dark panel / canvas 上で AA を満たす (F-E2)", () => {
    expect(contrast(DARK.dangerText, DARK.panel)).toBeGreaterThanOrEqual(AA_NORMAL);
    expect(contrast(DARK.dangerText, DARK.canvas)).toBeGreaterThanOrEqual(AA_NORMAL);
  });

  it("bg-danger ボタンの白文字は dark で AA を満たす (F-E2)", () => {
    expect(contrast(DARK.white, DARK.dangerFill)).toBeGreaterThanOrEqual(AA_NORMAL);
  });

  it("旧 #ef4444 は bg-danger 白文字 / text-danger とも AA 未達だったことを記録 (regression guard)", () => {
    // 旧値が text としても fill としても AA を割っていたことを明示 (再導入防止)。
    expect(contrast("#ef4444", DARK.panel)).toBeLessThan(AA_NORMAL);
    expect(contrast(DARK.white, "#ef4444")).toBeLessThan(AA_NORMAL);
  });
});
