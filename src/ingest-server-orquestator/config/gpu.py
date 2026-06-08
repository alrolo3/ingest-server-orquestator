from __future__ import annotations

import os
from typing import Any

from config.config import ServerConfig, get_server_config


def configure_gpu_environment(server_config: ServerConfig | None = None) -> None:
    """Apply runtime environment values before CUDA/model libraries load."""
    config = server_config or get_server_config()
    os.environ["CUDA_DEVICE_ORDER"] = config.cuda_device_order
    os.environ["CUDA_VISIBLE_DEVICES"] = config.visible_cuda_devices
    os.environ["DOCLING_DEVICE"] = config.docling_device
    os.environ["DOCLING_ARTIFACTS_PATH"] = str(config.docling_artifacts_path)
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"


def configure_torch_cuda_device(
    torch_module: Any,
    server_config: ServerConfig | None = None,
) -> None:
    config = server_config or get_server_config()
    configure_gpu_environment(config)
    if torch_module.cuda.is_available():
        torch_module.cuda.set_device(config.logical_cuda_device_index)
