# Phase 1 Architecture Proposal

獨立 Windows 專案，所有路徑以安裝目錄為準。GUI 與模型運算分離。

- launcher.py → 小型 PyInstaller launcher，使用 Windows 原生安裝精靈；不封裝 torch。
- runtime/python.exe → python.org 私有安裝，無 PATH 註冊、無系統 Python 依賴。
- app/ → PySide6 GUI、服務、獨立 CUDA smoke worker。
- updater/ → 僅 GitHub Release；SHA256、白名單解壓、版本目錄與 active.json 原子切換。
- state/、runs/、datasets/、models/、logs/、cache/ → 使用者本機資料，排除版本控制。

環境 manifest 固定 Python、torch、torchvision、CUDA index、最低 driver、環境版本與下載 SHA256。
使用官方完整 Windows installer 的 TargetDir/InstallAllUsers=0/PrependPath=0 建立私有 runtime，
不使用不支援一般 pip 管理的 embeddable distribution。安裝只由使用者按 Install 觸發；啟動僅檢查。

更新以版本目錄作為交易單位，驗證完成才原子切換 state/active.json。
Phase 1 拒絕 environment 不同的更新（保留既有 runtime），也拒絕 migration payload；
Phase 4 才開放平行 runtime 建置與資料庫 migration。失敗不得切換 active。
更新由獨立程序在 GUI 退出後執行；不覆蓋已載入的 app。

Dataset contract 見 DATASET.md。來源唯讀，驗證後複製至新的 cache 目錄，複製後比對 fingerprint。

Windows 風險：鎖檔、防毒、長路徑、SMB 中斷、driver 不足、下載失敗、spawn 模式。
使用原子 JSON、獨立 worker、明確 interpreter、限定解壓路徑；無 CUDA 時拒絕模型運算。
目前開發機沒有可用 nvidia-smi，GPU 真實整合需在 AI01 驗收。

## 使用者修訂（2026-09-13）
原 README CUDA-only 規定改為：預設 CUDA，使用者明確授權 allow_cpu=true 才可 CPU 訓練。安裝與 GUI 提供 opt-in；每個 run 保存授權及實際裝置。OOM 不切换裝置。
