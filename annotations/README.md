# Jump-rope annotations

Original human rope annotations for *hololive Dreams*. There are **675 records**: **543 train**, **129 development validation**, and **3 unresolved** records excluded from training. No unreviewed model drafts or synthetic images are included.

- `images/`: recorded game screenshots at their annotated resolution.
- `masks/rope/`: exact human-corrected visible-rope masks. Occluded spans remain unpainted.
- `masks/marker/`: player-triangle masks obtained from source pixels. These are automatic annotations, with later source-pixel corrections where available; they are not claimed as human-drawn masks.
- `labels/detect/`: one class-0 bounding box enclosing all visible rope fragments, plus the class-1 marker box.
- `labels/segment/`: class-0 visible-fragment polygons and class-1 marker polygons. Exact masks remain the canonical labels; conversion IoU is recorded.
- `manifest.json`: dimensions, SHA-256, split, anonymous recording group, annotation origin, review state, and conversion quality.

Classes: `0 = visible_rope`, `1 = player_marker`. Coordinates in YOLO files are normalized to each image's width and height. `coordinate_space` distinguishes full images from older recorded crops; their coordinates must not be mixed without rescaling. The 3 `review` records have no training label files. Empty masks are not inferred to be negative examples when review is unresolved.

Train and validation are separated by entire recording group. Any group with an original validation record stays in validation. These are development splits, not a new independent blind test. The 500 real samples associated with the shipped model have `release_model_split`; the model's additional synthetic training images are not part of this publication.

To materialize a standard YOLO directory and verify hashes:

```powershell
python training/train.py --task detect --output training-work/check --check-only
```

For training and export, see [training/README.md](../training/README.md). Original annotations use [CC BY 4.0](LICENSE); game screenshots retain third-party rights. Read [NOTICE.md](NOTICE.md) before reuse.

## 繁體中文

共 675 筆人工繩子標註：543 張訓練、129 張開發驗證，以及 3 張排除訓練的未確定樣本。繩子遮罩保留人工修正；三角標記另標為來源像素自動處理，不偽稱人工標註。沒有未核對草稿或解包合成圖。

Detect 將全部可見繩段合為一個外框，Seg 保留可見片段；遮擋處不補線。精確遮罩、圖片尺寸、資料來源類型、分組與雜湊均保存在此資料夾。完整畫面與較早的裁切畫面分別記錄，座標不可直接混用。

原創標註採 CC BY 4.0；遊戲截圖不由本專案重新授權。使用方式與權利範圍見上述訓練說明及 NOTICE。
