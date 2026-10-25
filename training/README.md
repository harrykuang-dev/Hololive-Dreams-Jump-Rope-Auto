# Training and model export

The public annotation package provides Detect boxes, Seg polygons, and canonical masks. See [annotations/](../annotations/README.md) for counts, grouped splits, unresolved records and rights.

```powershell
python -m venv .training-venv
.training-venv\Scripts\activate
python -m pip install -r training/requirements.txt
python training/train.py --task detect --variant n --output training-work/detect-n
python training/train.py --task segment --variant l --output training-work/seg-l
```

`--variant n|l` selects the small or large model. `--task detect|segment` selects boxes or masks. The initial checkpoint is the corresponding official YOLO26 pretrained model; Ultralytics downloads it if absent. Use a new `--output` directory for every run. `--check-only` validates image/mask/label hashes and prepares the dataset without loading a model or starting training. Unknown records are excluded.

`recipe.json` contains the training settings used for the released Detect n model, including 640 input, AdamW, learning rate 0.0005, seed 26023, up to 100 epochs and patience 20. The original model used 400 real training images plus 100 synthetic training images, and 100 real development-validation images. The synthetic renders are not distributed; training on this public human-only package is a new experiment and is not a bit-identical reconstruction of that run.

The trained source checkpoint is [models/rope.pt](../models/rope.pt). The current runtime uses the exported [model graphs](../models/README.md). To export a newly trained Detect model:

```powershell
python training/export_model.py training-work/detect-n/model/weights/best.pt
```

Do not blindly replace a runtime graph: input/output layout, class order, confidence threshold, DirectML operator placement and control geometry must be validated. `tools/prepare_directml_model.py` intentionally accepts only the reviewed shipped graph. TensorRT engines are device-specific and are generated locally from the matching mixed-precision graph.

The current program, model weights and training tools use AGPL-3.0. Original annotation data use CC BY 4.0; screenshot rights are separate. No game extraction tools or extracted game assets are included.

## 繁體中文

使用 `--task detect|segment` 及 `--variant n|l` 選擇四種訓練組合；每次指定新的輸出資料夾。程式先核對圖片、遮罩與標籤雜湊，依錄製群組隔離訓練與開發驗證，排除未確定樣本。`--check-only` 不載入模型或開始訓練。

`models/rope.pt` 是目前程式的來源權重。原訓練包含 100 張未公開的合成圖，因此用此人工資料包重訓屬於新實驗，不宣稱可逐位元重現舊訓練結果。匯出後仍須核對模型介面、GPU 後端及控制時機，不能直接替換檔案就視為驗收完成。
