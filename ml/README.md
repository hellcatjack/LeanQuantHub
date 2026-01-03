# 机器学习叠加（日线）

本目录提供可落地的 ML 训练脚本与模型输出格式，用于在规则策略之上叠加 ML 打分。
当前支持 **PyTorch 推理**（推荐使用服务器 `/data/anomalib/.venv/bin/python`）。

## 目录结构
- `config.json`：训练配置（特征窗口、标签周期、walk-forward 设置）
- `feature_engineering.py`：特征与标签生成
- `train.py`：训练脚本（线性模型 + walk-forward 输出）
- `train_torch.py`：PyTorch 训练脚本（MLP）
- `predict_torch.py`：PyTorch 推理脚本（生成分数 CSV）
- `model_io.py`：模型读写
- `models/`：输出模型与指标（建议不提交）

## 训练流程
1) 确保数据已在 `DATA_ROOT/curated_adjusted` 下（复权后）。
2) 运行训练：
```bash
python ml/train.py --config ml/config.json --data-root /data/share/stock/data
```
3) 输出：
```
ml/models/linear_model.json
ml/models/metrics.csv
```

## PyTorch 训练与推理
建议使用服务器已部署的 venv：
```bash
/data/anomalib/.venv/bin/python ml/train_torch.py --config ml/config.json --data-root /data/share/stock/data
/data/anomalib/.venv/bin/python ml/predict_torch.py --config ml/config.json --data-root /data/share/stock/data --output ml/models/scores.csv
```

输出：
- `ml/models/torch_model.pt`
- `ml/models/torch_payload.json`
- `ml/models/scores.csv`

## 模型输出格式（JSON）
```json
{
  "model_type": "linear",
  "features": ["ret_5", "ret_20", "ma_bias_60", "..."],
  "coef": [0.12, -0.08, 0.03],
  "intercept": 0.01,
  "mean": {"ret_5": 0.002, "...": 0.0},
  "std": {"ret_5": 0.04, "...": 1.0},
  "label_horizon_days": 20,
  "trained_at": "2026-01-03T00:00:00",
  "train_window": {
    "train_start": "2014-01-01",
    "train_end": "2022-01-01",
    "valid_end": "2023-01-01",
    "test_end": "2024-01-01"
  }
}
```

## Lean 叠加方式（推荐）
- 规则策略先生成候选池；
- ML 只做**排序/过滤/权重倾斜**；
- 重点使用 `linear_model.json`，减少依赖。

如果需要支持 LightGBM/XGBoost，可在本地训练后输出 **预测分数** 到 CSV，再由 Lean 读取分数做排序。
