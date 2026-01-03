from __future__ import annotations

from typing import Iterable

import torch
from torch import nn


class TorchMLP(nn.Module):
    def __init__(
        self, input_dim: int, hidden: Iterable[int], dropout: float = 0.1
    ) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        last_dim = input_dim
        for width in hidden:
            layers.append(nn.Linear(last_dim, width))
            layers.append(nn.ReLU())
            if dropout > 0:
                layers.append(nn.Dropout(dropout))
            last_dim = width
        layers.append(nn.Linear(last_dim, 1))
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)
