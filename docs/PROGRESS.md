# 開發進度（2026-09-13）

## Phase 1 已實作

- 獨立專案、架構提案、單一 VERSION、來源/資料分離與 Git 白名單。
- 約 12 MB launcher；私有 Python 安裝器與即時 log，明確 interpreter。
- 固定 environment manifest、版本檢查、GPU/driver 查詢、self test。
- PySide6 九頁骨架、背景工作、設定、更新查詢。
- Dataset contract、影像/標籤/遮罩旗標/洩漏驗證、fingerprint、本機複製驗證。
- Synthetic trainer subprocess、status/metrics/log、checkpoint、Stop/Resume、OOM/exit code。
- 使用者追加要求：CPU 必須明確授權，預設停用；run 保存授權與實際裝置。
- Release payload、SHA256、檔案白名單、staging、原子 active pointer、rollback。
- Windows CI、tag Release assets、自動化測試。

## 待驗收 / 限制

- AI01 RTX A5000 managed runtime 的首次安裝與完整 GUI → CUDA → checkpoint 鏈尚待驗收。
- 本機無可用 NVIDIA 監控；GPU 整合測試僅在明確啟用時執行。
- 原生 Python installer 的 portable 部署行為尚須乾淨 Windows 驗收，不能宣稱已完成安裝測試。
- 更新 GUI 僅查詢。自動下載/退出/安裝/重啟、異環境 parallel runtime、migration 屬後續 Phase 4。
- Phase 1 只允許相同完整環境 manifest/lock 的更新；變更則拒絕，保留舊 runtime。
- 第一版資料契約尚未與 DatasetManager 實際 export schema 接軌；不可直接假設相容。
- 相鄰事件目前以 event_id 禁止跨 split；時間鄰近且不同 event_id 的規則仍待定義。
- Dataset 統計尚未加入 camera/year，Run 曲線、進階設定與模型管理未完成。
- Phase 2（backbone、sampler、CE+Triplet、正式 metrics）與 Phase 3 尚未開始。
- 未發佈正式 Release；公開 repo 保存可測試的開發進度。

## 驗證記錄

本機 Windows Python 3.13：36 passed / 1 skipped（CUDA integration）。
CPU 真實 forward/backward/optimizer、Stop/Resume 已通過；production Python 3.12/CUDA 路徑仍待 AI01 驗收。
PyInstaller launcher 成功建置，11,923,153 bytes；update payload 已產生。所有測試資料皆為人工合成，本機原始資料未修改。
初次測試因系統 Temp 權限失敗，改用專案內獨立 basetemp 後正常。
GUI 已做 offscreen 啟動及控制項測試；畫面截圖工具因環境限制無法完成目視檢查。
