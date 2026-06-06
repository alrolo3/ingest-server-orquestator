from __future__ import annotations

import os
from typing import Any

from config.config import ServerConfig, get_server_config


def configure_gpu_environment(server_config: ServerConfig | None = None) -> None:
    """Apply CUDA-related environment values from project config."""
    config = server_config or get_server_config()
    os.environ["CUDA_DEVICE_ORDER"] = config.cuda_device_order
    os.environ["CUDA_VISIBLE_DEVICES"] = config.visible_cuda_devices
    os.environ["DOCLING_DEVICE"] = config.docling_device


def configure_torch_cuda_device(
    torch_module: Any,
    server_config: ServerConfig | None = None,
) -> None:
    config = server_config or get_server_config()
    configure_gpu_environment(config)
    if torch_module.cuda.is_available():
        torch_module.cuda.set_device(config.logical_cuda_device_index)
