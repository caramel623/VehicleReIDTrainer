# v0.1.2 安裝驗證修正

適用已使用 v0.1.1，且套件已安裝、最後驗證出現 60 秒 timeout 的資料夾。

1. 關閉舊的 VehicleReIDTrainer 安裝視窗與程式。
2. 將 VehicleReIDTrainer-repair-v0.1.2-win64.zip 解壓到原安裝目錄，例如 E:\VehicleReIDTrainer，覆蓋 ZIP 內的程式檔。
3. 保留 runtime、cache、state、models、runs 和 datasets，不要刪除，也不必換新空目錄。
4. 執行原資料夾的新 VehicleReIDTrainer.exe，按 Install Environment 再驗證。需要 CPU 時須自行勾選允許。

修補 ZIP 不包含 runtime、cache、state 或 configs，不會替換已安裝 Python/PyTorch 或環境 manifest。
套件版本符合時完全跳過 pip install；CPU 使用授權預設仍關閉。

首次驗證最多 600 秒，每 10 秒顯示仍在進行的步驟。torch 與 torchvision 匯入、CUDA 查詢及
matrix multiply 在同一個子程序完成，避免反覆載入大型 DLL。持續停留時每 60 秒輸出 Python stack 診斷。

逾時只表示驗證沒有完成，不等於 CUDA 不可用。失敗時保留套件與重試標記；
將 logs/environment.log 與 state/environment-verification.json 提供給開發者可定位最後步驟。
不需要因 runtime/Scripts 不在 PATH 的警告而修改系統 PATH，也不需要手動升級 pip。
