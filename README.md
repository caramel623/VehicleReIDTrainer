# VehicleReIDTrainer

獨立 Windows 11 車輛／機車 Re-ID Stage 2 訓練專案。此版本為 **Phase 1 基礎實作**，
提供 synthetic smoke training（CUDA 優先、CPU 需授權）；尚非完整 Re-ID 訓練產品。

## 架構

[Architecture Proposal](docs/ARCHITECTURE.md) · [Dataset contract](docs/DATASET.md) · [進度與驗收](docs/PROGRESS.md)

`VehicleReIDTrainer.exe` 是小型 launcher。`runtime/python.exe` 為私有 Python；
`app/` 放 GUI 與 trainer，`updater/` 放獨立更新器。`VERSION` 是唯一 app 版本來源。
資料、模型、logs、cache、runs、runtime、使用者設定皆不提交 GitHub，無 telemetry。

## Environment setup

Portable folder 需含 EXE、app/、updater/、configs/、VERSION。
執行 EXE → Install Environment。首次畫面用 launcher 內建 Tk，runtime 完成後主程式為 PySide6。
從官方 CPython NuGet 套件解壓建立私有 Python（不更動系統 Python、登錄或 PATH），
SHA256 驗證 → staging → 驗證 interpreter/pip → 移至 runtime → 再驗證 → 安裝依賴。
使用明確 `runtime/python.exe -I -m pip --isolated`。
只在明確安裝時下載；一般啟動不執行 pip。版本由 environment.json 和 requirements.lock 固定。

目前固定 Python 3.12.10、PyTorch 2.7.1+cu126 / torchvision 0.22.1+cu126，
並非宣稱最新版。CUDA 12.6 採保守 Windows driver 門檻 560.76。
參考 [PyTorch 官方配對](https://pytorch.org/get-started/previous-versions/)、
[Python 官方 Windows 安裝](https://docs.python.org/3.12/using/windows.html)、
[NVIDIA CUDA 12.6 release notes](https://docs.nvidia.com/cuda/archive/12.6.0/cuda-toolkit-release-notes/index.html)。
Python NuGet 套件 SHA256 固定於 manifest，來源見 [Python 官方 NuGet 說明](https://docs.python.org/3.12/using/windows.html#the-nuget-org-packages)。

預設無 CUDA 會拒絕訓練。依使用者新要求，安裝精靈與 Settings 可明確勾選允許 CPU；
允許後 CUDA 不可用才使用 CPU，實際裝置記錄於每個 run 的 device.json。版本錯誤仍拒絕執行。
環境安裝仍採同一套 CUDA wheel（也可在 CPU 執行），不會私自更換 wheel。安裝完成前執行選定裝置的 matrix multiply。
除非使用者允許才使用CPU。
無須完整 CUDA Toolkit。Driver 由使用者自行安裝；本程式不更動 driver。
既有 runtime 不會由 Phase 1 installer 自動修復／升級，避免破壞原環境。

## Dataset / Training / Resume

Dataset 頁選擇 immutable export，Validate，再 Prepare Local Cache 至新的本機資料夾。
精確欄位要求見 Dataset contract；未符合介面不可視為已接軌 Stage 1。
Training 頁可 Start Training Smoke、Stop、Resume checkpoint。只產生 synthetic tensors，
不會讀取私人訓練照片。停止於 step 邊界；checkpoint 保存模型、optimizer、scheduler、scaler、
epoch、best metric、config、fingerprint。Resume 僅接受相同 smoke config。
Runs 頁顯示 status/exit code；詳細錯誤在 runs/<id>/train.log。
OOM 會 FAILED；即使允許 CPU，也不會在 OOM 後偷偷切換裝置或調整參數。

## GitHub updates / Recovery

Updates 頁可讀取 latest stable GitHub Release。Phase 1 已提供下載、驗證、staging、
原子 active pointer 與 rollback 服務，GUI 自動 install/restart 留 Phase 4。
關閉 GUI 後可使用 `runtime/python.exe updater/updater.py --root <install> --package <zip> --manifest <json>`。
只接受 app/config/VERSION payload；SHA256 驗證與逐檔 manifest 驗證。
不得對正在運作的 app 做 git pull。環境變更更新會拒絕，保持舊版本。
回復：`runtime/python.exe updater/updater.py --root <install> --rollback`。
若異常退出留下 state/gui.lock，確認 GUI 與 trainer 全部退出後才能移除此 lock。
SHA256 不是數位簽章；release 帳號與 HTTPS 是目前信任來源。

## Developer setup

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m app.main
.\scripts\build_launcher.ps1
```

開發 GUI 可以在無 GPU 機器測試，production training 只使用 managed runtime。CPU 授權預設關閉，變更只影響後續作業。
AI01 安裝完成後：

```powershell
$env:VEHICLE_REID_CUDA_TEST = '1'
.\runtime\python.exe -m pip install pytest==8.3.5
.\runtime\python.exe -m pytest tests/integration/test_cuda.py -q
```

## Release process

修改 VERSION → tests → `python scripts/package_update.py` → 檢查 payload → tag vX.Y.Z。
GitHub Actions 執行 Windows tests 並產生 update ZIP、manifest.json、SHA256SUMS；
版本 tag 通過驗證才發佈 Release。Phase 1 不自動發佈未經 AI01 驗收的 bootstrap。
原始需求 README.txt 僅留本機（包含部署內網資訊）；公開文件使用抽象路徑。

## v0.1.1 安裝修正與換版

修正舊版系統 installer 結束後未建立 runtime/python.exe、接著安裝 pip 套件出現 WinError 2 的問題。
不再執行 Python 系統 installer；無需移除其他 Python。保留「CPU 需明確授權」規則。

請將 **完整 v0.1.1 bootstrap ZIP** 解壓到新的資料夾，例如 `E:\VehicleReIDTrainer-0.1.1`，
再執行該資料夾的 VehicleReIDTrainer.exe。不要只換 EXE：新版需要配套的 configs 和 app。
舊資料夾及資料不需刪除。若沿用先前失敗的資料夾，需完整替換程式檔，保留 state 和 cache；
安裝器會保留有失敗標記且缺少 python.exe 的 runtime 至 state/runtime-incomplete-*。
若已存在但無法執行的 python.exe，程式保留原檔並停止，請採新的解壓目錄。

此修正改變 environment manifest，舊版 app-only updater 會拒絕；必須使用 bootstrap。
進階診斷：`VehicleReIDTrainer.exe --prepare-runtime-only` 只建立並驗證 Python/pip，
不下載 PyTorch、不執行 AI 運算；结果在 state/runtime-probe.json 和 logs/environment.log。
此模式不會將完整訓練環境標示為 Ready；再次正常啟動仍會完成依賴安裝。

## v0.1.2：套件已安裝但驗證超過 60 秒

[原目錄修補步驟](docs/REPAIR_INSTALL.md)。提供 code-only repair ZIP，可保留 v0.1.1 已安裝的 runtime 與下載 cache。
套件 metadata 版本相符就跳過安裝；完整匯入/裝置 self-test 改用單一子程序，最多 600 秒，
持續顯示進度，逾時與真正的 CUDA/版本錯誤分開呈現。原環境 manifest 保持不變。
