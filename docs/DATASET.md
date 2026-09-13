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
不猜測現有 DatasetManager 輸出格式；正式接軌前需以匿名 schema 驗證。
