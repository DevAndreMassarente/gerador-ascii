from __future__ import annotations

import io
import os
import stat
import sys
from pathlib import Path

import pytest
from PIL import Image

import image2ascii as app


def test_load_image_applies_exif_orientation(tmp_path: Path) -> None:
    path = tmp_path / "oriented.jpg"
    image = Image.new("RGB", (2, 3), (255, 0, 0))
    exif = image.getexif()
    exif[274] = 6  # Rotate 90 degrees clockwise for display.
    image.save(path, quality=100, subsampling=0, exif=exif)

    loaded, frame_count = app.load_image(str(path))

    assert frame_count == 1
    assert loaded.mode == "RGBA"
    assert loaded.size == (3, 2)


def test_load_image_selects_requested_animation_frame(tmp_path: Path) -> None:
    path = tmp_path / "animated.gif"
    first = Image.new("RGB", (2, 2), (255, 0, 0))
    second = Image.new("RGB", (2, 2), (0, 255, 0))
    first.save(path, save_all=True, append_images=[second], duration=10, loop=0)

    loaded, frame_count = app.load_image(str(path), frame=1)

    assert frame_count == 2
    red, green, blue, alpha = loaded.getpixel((0, 0))
    assert green > red and green > blue
    assert alpha == 255


def test_load_image_rejects_frame_out_of_range(tmp_path: Path) -> None:
    path = tmp_path / "single.png"
    Image.new("RGB", (1, 1)).save(path)

    with pytest.raises(ValueError, match="frame 1 inexistente"):
        app.load_image(str(path), frame=1)


def test_load_image_rejects_empty_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"")))

    with pytest.raises(ValueError, match="nenhum dado"):
        app.load_image("-")


def test_load_image_rejects_unrecognized_file(tmp_path: Path) -> None:
    path = tmp_path / "not-an-image.txt"
    path.write_text("not an image", encoding="utf-8")

    with pytest.raises(ValueError, match="nao e uma imagem"):
        app.load_image(str(path))


def test_atomic_write_creates_new_file_with_expected_contents_and_mode(tmp_path: Path) -> None:
    output = tmp_path / "art.txt"

    app.atomic_write_text(output, "ASCII\n", force=False)

    assert output.read_bytes() == b"ASCII\n"
    assert stat.S_IMODE(output.stat().st_mode) == 0o644
    assert not list(tmp_path.glob(".art.txt.*.tmp"))


def test_atomic_write_refuses_existing_output_without_force(tmp_path: Path) -> None:
    output = tmp_path / "art.txt"
    output.write_text("original", encoding="utf-8")

    with pytest.raises(FileExistsError, match="--force"):
        app.atomic_write_text(output, "replacement", force=False)

    assert output.read_text(encoding="utf-8") == "original"
    assert not list(tmp_path.glob(".art.txt.*.tmp"))


def test_atomic_write_replaces_existing_output_with_force(tmp_path: Path) -> None:
    output = tmp_path / "art.txt"
    output.write_text("original", encoding="utf-8")

    app.atomic_write_text(output, "replacement\n", force=True)

    assert output.read_text(encoding="utf-8") == "replacement\n"
    assert not list(tmp_path.glob(".art.txt.*.tmp"))


def test_atomic_write_rejects_missing_parent_without_leaving_temporary_file(
    tmp_path: Path,
) -> None:
    output = tmp_path / "missing" / "art.txt"

    with pytest.raises(OSError, match="diretorio de saida nao existe"):
        app.atomic_write_text(output, "data", force=False)

    assert not output.exists()


def test_same_file_detects_identical_path_hardlink_and_symlink(tmp_path: Path) -> None:
    source = tmp_path / "image.png"
    source.write_bytes(b"image")
    hardlink = tmp_path / "hardlink.png"
    os.link(source, hardlink)
    symlink = tmp_path / "symlink.png"
    symlink.symlink_to(source)

    assert app._same_file(str(source), source)
    assert app._same_file(str(source), hardlink)
    assert app._same_file(str(source), symlink)
    assert not app._same_file("-", source)
    assert not app._same_file(str(source), tmp_path / "new-output.txt")
