# v0.1.3 原目錄修補

1. 關閉 VehicleReIDTrainer 與訓練作業。
2. 將 VehicleReIDTrainer-repair-v0.1.3-win64.zip 解壓到既有 E:\VehicleReIDTrainer，覆蓋程式檔。
3. 保留 runtime、cache、state、runs、datasets 及使用者資料；環境依賴版本未變更，無需重裝。
4. 重新啟動，Dataset 頁再次 Validate。
5. Training 頁可 Resume checkpoint，選擇先前失敗的 run 目錄。這仍是 synthetic smoke，並非正式 dataset 訓練。

修正 DatasetManager 使用 reid_crop/plate_mask_bbox 與整數 JSONL image_id 的格式相容性。
上游未提供 event_id 時會清楚警告，無法完成事件洩漏檢查；見 DATASET.md。

針對 status.json 暫時遭 Windows 占用，加入有限次重試；GUI 輪詢僅讀取，
寫入仍持續失敗時先記錄 traceback，再嘗試 FAILED 狀態。Runs 顯示 train.log 路徑與最後錯誤。
若持續出現 WinError 5，新紀錄可協助區分暫時鎖定、檔案權限等原因，程式不會擅自變更權限。
