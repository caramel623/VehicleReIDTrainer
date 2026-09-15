# 開發進度（2026-09-16）

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
- v0.1.1 已改用官方 NuGet 私有 runtime，實際 EXE 的 Python/pip 安裝與重試通過；完整 CUDA dependencies 與原部署機驗收仍待完成。
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

## v0.1.1：修正 managed Python WinError 2

使用者回報系統 Python installer 結束後，runtime/python.exe 不存在，下一步 Popen 發生 WinError 2。
舊流程未驗證 interpreter。已有 Python 的維護模式是可能原因，但未取得原機 installer log，不能確定原機觸發原因。

- 以官方 CPython NuGet 3.12.10 取代系統 EXE installer；environment/runtime version 升為 2。
- SHA256、限制解壓路徑、staging、64-bit/版本/executable/prefix/pip 驗證，通過後才呼叫 pip。
- 有失敗標記且缺少 python.exe 的目錄會保留在 state/runtime-incomplete-*。
- 已存在但不可用的 interpreter 保留原狀並中止，無偷偷切換到系統 Python。
- PyInstaller 子程序啟動時隔離 DLL 搜尋目錄與 PYTHONHOME/PYTHONPATH。
- CPU opt-in 保留；此次未更換 torch/torchvision 版本，也未新增模型功能。

驗證：50 passed / 1 skipped（CUDA）。包含官方 NuGet 真實 runtime/pip、舊安裝殘留保留、重試、
SHA256/路徑/缺少執行檔等回歸測試。已建置的 EXE 在含空白路徑及干擾 PYTHONHOME/PYTHONPATH 下
連續兩次執行 --prepare-runtime-only 成功，pip 25.0.1 確認來自專屬 Python 3.12 runtime。
沒有執行系統 Python 安裝／卸載，沒有下載大型 PyTorch/CUDA；完整環境仍需使用者原機驗收。

交付：dist/VehicleReIDTrainer-bootstrap-v0.1.1-win64.zip。
README 有新目錄解壓步驟。此版更動 launcher 與環境來源，不能用舊版 app-only updater 換版。
GitHub Windows CI 已增加官方 runtime 整合測試；上一輪 CI 已確認成功。
