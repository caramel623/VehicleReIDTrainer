# Dataset interface v1

必須存在 metadata/images.csv、vehicles.csv、labels.csv、manifest.jsonl，
以及 splits/train.csv、val.csv、test.csv 和 reid_crops/。

images.csv 欄位：image_id,path,vehicle_id,event_id,plate_masked；可選 camera_id,year。
path 必須是 reid_crops/ 下相對路徑。plate_masked 必須 true 或 1。
vehicles.csv: vehicle_id。labels.csv: image_id,vehicle_id。
manifest.jsonl: 每行 JSON，含 image_id,path,sha256。
split CSV: image_id。

每張圖僅能出現在一個 split；identity 與 event 不跨 split，避免資料洩漏。
每個 identity 至少兩張照片。Phase 2 評估 query/gallery 在各 split 內另行建立。
遮罩旗標是出口契約，無法單憑旗標證明像素已遮罩；上游負責實際遮罩。
Trainer 不讀取 OCR/INI 作為模型輸入。Validator 拒絕不符合此契約的資料，
v0.1.3 另支援下列已比對上游 exporter 原始碼的格式。

## DatasetManager 匯出格式（v0.1.3）

讀取 reid_crop 作為影像路徑，僅允許 reid_crops/。plate_mask_bbox 必須為有效遮罩框，且在影像範圍內。
CSV 的字串 image_id 與 JSONL 的整數 image_id 會在記憶體內正規化；不修改原始檔案。
manifest 與 CSV 的車輛標籤、裁切路徑、mask bbox、split 必須一致；split CSV 再次比對。

上游 sha256 是原圖的 hash，不拿來比對 reid crop。裁切圖 SHA256 由 Trainer 當場計算並納入 fingerprint。
這可辨識 dataset 內容變動，但不能證明裁切圖符合某個上游已簽署 hash。遮罩框也不等同於像素檢查。

目前上游沒有 event_id：以警告標示 event_leakage_checked=false，仍檢查 identity split 洩漏。
valid 表示已提供資訊的結構／影像／標籤檢查通過；缺少事件資料時 training_ready=false，
不能宣稱完整事件防洩漏已驗證。現在的 synthetic smoke 不讀 dataset，正式訓練功能仍屬 Phase 2。
若有 export_state.json 且 complete 不是 true，拒絕尚未完成的匯出。
Prepare Cache 僅複製標準 metadata/splits、reid crops，以及存在時的 export_config/state。
