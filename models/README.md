# Detection model

YOLO26n Detect, two classes: whole visible rope (0) and player marker (1). Input is the full client image letterboxed to 640×640. Output is NMS-free `[1,300,6]`. Confidence threshold: 0.15.

`rope.onnx` is the FP32 portable graph. `rope.fp16.onnx` is the exact mixed-precision graph used to build the tested TensorRT engine. It preserves FP32 input/output. GPU-specific engines are generated locally and are not tracked.

`rope.directml.onnx` contains the same 204 initializers. A bounded, exact rewrite of the final integer remainder operation lets DirectML execute the entire graph with CPU fallback disabled. `directml-graph.json` records source/output hashes and the conversion contract. No training or weight changes are involved.

The model is derived from Ultralytics YOLO26 and carries [AGPL-3.0](AGPL-3.0.txt). The current integrated program is also AGPL-3.0; the historical archive retains its MIT License. See [NOTICE.md](../NOTICE.md).

Training used 500 real annotated training images plus 100 synthetic training images; 125 separate real images were used for development validation. The update adds 100 late-game training images and 25 development-validation images, separated by whole recorded game. The public annotation package remains the previously published set; the additional 125 late-game annotations are not included in it. The [public annotation package](../annotations/README.md) contains the human annotation records and gameplay screenshots, with separate rights notices. Extracted rendering resources and synthetic renders are not distributed. Runtime uses only the trained graph, numeric temporal references and pixels from the game window.

`rope.pt` is the trained source checkpoint. [Training and export tools](../training/README.md) and the original recipe are included.

The player runtime uses TensorRT 10.13 with the CUDA Driver API and no PyTorch. FP16 remains the default; device-specific engines are built and hash-checked locally. Training dependencies are separate.
