# 机器学习叠加（日线）

本目录提供可落地的 ML 训练脚本与模型输出格式，用于在规则策略之上叠加 ML 打分。
当前支持 **PyTorch MLP** 与 **LightGBM 排序**（推荐使用服务器 `/app/stocklean/.venv/bin/python`）。

## 目录结构
- `config.json`：训练配置（特征窗口、标签周期、walk-forward 设置，含 PIT 基本面快照与标签对齐）
- `feature_engineering.py`：特征与标签生成
- `train.py`：训练脚本（线性模型 + walk-forward 输出）
- `train_torch.py`：PyTorch 训练脚本（MLP）
- `predict_torch.py`：推理脚本（根据模型类型生成分数 CSV）
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

## PIT 周度因子与标签对齐
- `pit_fundamentals.enabled=true` 启用周度基本面快照特征（默认目录 `DATA_ROOT/factors/pit_weekly_fundamentals`）。
- `label_price=open` + `label_start_offset=1` 表示标签从下一交易日开盘起算。

## 基线因子打分（周度）
使用 PIT 周度快照 + 复权行情生成基线因子分数（动量/质量/估值/低波/流动性）：
```bash
/app/stocklean/.venv/bin/python scripts/build_factor_scores.py \\
  --data-root /data/share/stock/data \\
  --output ml/models/factor_scores.csv
```

- 因子权重配置：`configs/factor_scores.json`
- 结合回测：使用 `configs/portfolio_weights_factor.json`（`score_csv_path=ml/models/factor_scores.csv`）

## PyTorch 训练与推理
建议使用服务器已部署的 venv：
```bash
/app/stocklean/.venv/bin/python ml/train_torch.py --config ml/config.json --data-root /data/share/stock/data
/app/stocklean/.venv/bin/python ml/predict_torch.py --config ml/config.json --data-root /data/share/stock/data --output ml/models/scores.csv
```

输出（PyTorch）：
- `ml/models/torch_model.pt`
- `ml/models/torch_payload.json`
- `ml/models/scores.csv`

输出（LightGBM 排序，需安装 `lightgbm` 依赖）：
- `ml/models/lgbm_model.txt`
- `ml/models/torch_payload.json`（`model_type=lgbm_ranker`）
- `ml/models/scores.csv`

LightGBM 排序将连续收益标签按截面分箱（默认 5 桶），可在 `model_params.rank_label_bins` 调整。

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

LightGBM 模式可通过 `model_type=lgbm_ranker` 启用；未安装依赖时会提示缺失。
如需 GPU（OpenCL）训练，可在训练参数中设置 `device=cuda` 或在 `model_params` 写入 `device_type: "gpu"` 与 `gpu_platform_id/gpu_device_id`。
