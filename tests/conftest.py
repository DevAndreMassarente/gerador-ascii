from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "image2ascii.py"


@pytest.fixture
def save_image(tmp_path: Path) -> Callable[[Image.Image, str], Path]:
    """Save a Pillow image under tmp_path and return its path."""

    def save(image: Image.Image, name: str = "input.png") -> Path:
        path = tmp_path / name
        image.save(path)
        return path

    return save


@pytest.fixture
def run_cli() -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run the real command-line program in an isolated subprocess."""

    def run(
        *arguments: str | Path,
        input_bytes: bytes | None = None,
        timeout: float = 10,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.setdefault("PYTHONUTF8", "1")
        return subprocess.run(
            [sys.executable, str(SCRIPT), *(str(argument) for argument in arguments)],
            cwd=PROJECT_ROOT,
            env=environment,
            input=input_bytes,
            capture_output=True,
            timeout=timeout,
            check=False,
            text=input_bytes is None,
        )

    return run


@pytest.fixture
def neutral_render_options() -> dict[str, object]:
    """Options that make luminance conversion deterministic for tiny fixtures."""

    return {
        "aspect": 0.5,
        "fit": "stretch",
        "color_mode": "none",
        "mono_color": (255, 32, 32),
        "style": "normal",
        "contrast": 1.0,
        "brightness": 1.0,
        "gamma": 1.0,
        "edges": 0.0,
        "polarity": "dark",
        "alpha_threshold": 1,
        "invert_flag": False,
        "disable_auto_invert": True,
        "dither": "none",
        "background": (0, 0, 0),
        "mono_shading": False,
    }
