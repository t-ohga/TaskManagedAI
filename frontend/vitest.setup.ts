import { configure } from "@testing-library/react";

import "@testing-library/jest-dom/vitest";

// CI 負荷下では waitFor / findBy の default 1000ms timeout が時折不足し、2 段非同期 (例:
// bulk-status-changer の click → update → reload) で timing flake になる。非同期ユーティリティの
// 待ち時間を延長して flake を抑止する (失敗時の最大待ち時間のみ延び、pass 時は即解決のため遅くならない)。
configure({ asyncUtilTimeout: 5000 });
