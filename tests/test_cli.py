from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Callable

import pytest
from PIL import Image

import image2ascii as app


def neutral_flags(*, include_charset: bool = True) -> list[str]:
    flags = [
        "--fit",
        "stretch",
        "--style",
        "normal",
        "--contrast",
        "1",
        "--brightness",
        "1",
        "--gamma",
        "1",
        "--edges",
        "0",
        "--threshold",
        "0",
        "--alpha-threshold",
        "1",
        "--polarity",
        "dark",
        "--background",
        "black",
    ]
    if include_charset:
        flags.extend(["--chars", " @"])
    return flags


def test_cli_help_and_version_work() -> None:
    # Call main directly here so these two parser-only operations stay very fast.
    with pytest.raises(SystemExit) as help_exit:
        app.main(["--help"])
    with pytest.raises(SystemExit) as version_exit:
        app.main(["--version"])

    assert help_exit.value.code == 0
    assert version_exit.value.code == 0


def test_cli_ascii_text_to_stdout(save_image: Callable[[Image.Image, str], Path], run_cli) -> None:
    image = Image.new("RGBA", (2, 1))
    image.putdata([(0, 0, 0, 255), (255, 255, 255, 255)])
    source = save_image(image, "ramp.png")

    result = run_cli(source, "2x1", *neutral_flags(), "--format", "text")

    assert result.returncode == 0
    assert result.stdout == " @\n"
    assert result.stderr == ""


def test_cli_reads_image_from_stdin(run_cli) -> None:
    stream = io.BytesIO()
    Image.new("RGB", (1, 1), (255, 255, 255)).save(stream, format="PNG")

    result = run_cli(
        "-",
        "1x1",
        *neutral_flags(),
        "--format",
        "text",
        input_bytes=stream.getvalue(),
    )

    assert result.returncode == 0
    assert result.stdout == b"@\n"
    assert result.stderr == b""


@pytest.mark.parametrize(
    ("mode", "image", "size", "extra", "expected"),
    [
        (
            "halfblock",
            [(255, 255, 255, 255), (0, 0, 0, 255)],
            (1, 2),
            [],
            "▀\n",
        ),
        (
            "braille",
            [
                (255, 255, 255, 255),
                (0, 0, 0, 255),
                (0, 0, 0, 255),
                (0, 0, 0, 255),
                (0, 0, 0, 255),
                (0, 0, 0, 255),
                (0, 0, 0, 255),
                (0, 0, 0, 255),
            ],
            (2, 4),
            ["--braille-threshold", "128"],
            "⠁\n",
        ),
    ],
)
def test_cli_high_resolution_modes(
    mode: str,
    image: list[tuple[int, int, int, int]],
    size: tuple[int, int],
    extra: list[str],
    expected: str,
    save_image: Callable[[Image.Image, str], Path],
    run_cli,
) -> None:
    source_image = Image.new("RGBA", size)
    source_image.putdata(image)
    source = save_image(source_image, f"{mode}.png")

    result = run_cli(
        source,
        "1x1",
        "--mode",
        mode,
        *neutral_flags(include_charset=False),
        *extra,
        "--format",
        "text",
    )

    assert result.returncode == 0
    assert result.stdout == expected


def test_cli_ordered_dither_is_observable(
    save_image: Callable[[Image.Image, str], Path], run_cli
) -> None:
    source = save_image(Image.new("L", (4, 4), 128), "gray.png")

    result = run_cli(
        source,
        "4x4",
        *neutral_flags(),
        "--dither",
        "ordered",
        "--keep-trailing-spaces",
        "--format",
        "text",
    )

    assert result.returncode == 0
    assert result.stdout == " @ @\n@ @ \n @ @\n@ @ \n"


def test_cli_ansi_output_contains_color_and_ends_with_newline(
    save_image: Callable[[Image.Image, str], Path], run_cli
) -> None:
    source = save_image(Image.new("RGB", (1, 1), "white"), "white.png")

    result = run_cli(
        source,
        "1x1",
        *neutral_flags(),
        "--color-mode",
        "mono",
        "--mono-color",
        "#010203",
        "--format",
        "ansi",
    )

    assert result.returncode == 0
    assert "\x1b[38;2;1;2;3m@\x1b[0m" in result.stdout
    assert result.stdout.endswith("\n")


def test_cli_auto_detects_html_output(
    tmp_path: Path,
    save_image: Callable[[Image.Image, str], Path],
    run_cli,
) -> None:
    source = save_image(Image.new("RGB", (1, 1), "white"), "white.png")
    output = tmp_path / "art.HTML"

    result = run_cli(
        source,
        "1x1",
        *neutral_flags(),
        "--color-mode",
        "image",
        "--quiet",
        "-o",
        output,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    document = output.read_text(encoding="utf-8")
    assert document.startswith("<!doctype html>")
    assert "<title>Arte ASCII de white.png</title>" in document
    assert "color:#ffffff" in document


def test_cli_trailing_space_policy(save_image: Callable[[Image.Image, str], Path], run_cli) -> None:
    image = Image.new("RGBA", (3, 1))
    image.putdata([(255, 255, 255, 255), (0, 0, 0, 255), (0, 0, 0, 255)])
    source = save_image(image, "spaces.png")

    trimmed = run_cli(source, "3x1", *neutral_flags(), "--format", "text")
    kept = run_cli(
        source,
        "3x1",
        *neutral_flags(),
        "--format",
        "text",
        "--keep-trailing-spaces",
    )

    assert trimmed.stdout == "@\n"
    assert kept.stdout == "@  \n"


def test_cli_rejects_missing_and_corrupt_inputs(tmp_path: Path, run_cli) -> None:
    missing = run_cli(tmp_path / "missing.png", "1x1")
    corrupt_path = tmp_path / "corrupt.png"
    corrupt_path.write_bytes(b"this is not a PNG")
    corrupt = run_cli(corrupt_path, "1x1")

    assert missing.returncode == 1
    assert "imagem nao encontrada" in missing.stderr
    assert corrupt.returncode == 1
    assert "nao e uma imagem" in corrupt.stderr
    assert "Traceback" not in missing.stderr + corrupt.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ["2x1", "--width", "2"],
        ["2x1", "--size", "2x1"],
        ["--aspect", "nan"],
        ["--gamma", "0"],
        ["--alpha-threshold", "256"],
        ["--mode", "halfblock", "--chars", " @"],
    ],
)
def test_cli_rejects_conflicting_or_invalid_arguments(
    arguments: list[str],
    save_image: Callable[[Image.Image, str], Path],
    run_cli,
) -> None:
    source = save_image(Image.new("RGB", (2, 1), "white"), "input.png")

    result = run_cli(source, *arguments)

    assert result.returncode == 2
    assert "error:" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_rejects_oversized_grid_before_rendering(
    save_image: Callable[[Image.Image, str], Path], run_cli
) -> None:
    source = save_image(Image.new("RGB", (1, 1), "white"), "small.png")

    result = run_cli(source, f"{app.MAX_GRID_DIMENSION + 1}x1")

    assert result.returncode == 2
    assert "no maximo" in result.stderr


def test_cli_applies_mode_aware_sample_limit(
    save_image: Callable[[Image.Image, str], Path], run_cli
) -> None:
    source = save_image(Image.new("RGB", (1, 1), "white"), "small.png")

    result = run_cli(source, "500x501", "--mode", "braille")

    assert result.returncode == 2
    assert "amostras" in result.stderr


def test_cli_paint_background_enables_ansi_automatically(
    save_image: Callable[[Image.Image, str], Path], run_cli
) -> None:
    source = save_image(Image.new("RGB", (1, 1), "white"), "white.png")

    result = run_cli(source, "1x1", "--paint-background", "--quiet")

    assert result.returncode == 0
    assert "\x1b[48;2;255;255;255m" in result.stdout


def test_cli_refuses_to_overwrite_input_even_with_force(
    save_image: Callable[[Image.Image, str], Path], run_cli
) -> None:
    source = save_image(Image.new("RGB", (1, 1), "white"), "source.png")
    original = source.read_bytes()

    result = run_cli(
        source,
        "1x1",
        *neutral_flags(),
        "--format",
        "text",
        "--force",
        "-o",
        source,
    )

    assert result.returncode == 1
    assert "nao pode sobrescrever" in result.stderr
    assert source.read_bytes() == original


def test_cli_refuses_hardlink_to_input(
    tmp_path: Path,
    save_image: Callable[[Image.Image, str], Path],
    run_cli,
) -> None:
    source = save_image(Image.new("RGB", (1, 1), "white"), "source.png")
    hardlink = tmp_path / "same-file.txt"
    os.link(source, hardlink)
    original = source.read_bytes()

    result = run_cli(source, "1x1", *neutral_flags(), "--force", "-o", hardlink)

    assert result.returncode == 1
    assert "nao pode sobrescrever" in result.stderr
    assert source.read_bytes() == hardlink.read_bytes() == original


def test_cli_existing_output_requires_force_and_is_preserved_on_failure(
    tmp_path: Path,
    save_image: Callable[[Image.Image, str], Path],
    run_cli,
) -> None:
    source = save_image(Image.new("RGB", (1, 1), "white"), "source.png")
    output = tmp_path / "art.txt"
    output.write_text("sentinel", encoding="utf-8")

    refused = run_cli(source, "1x1", *neutral_flags(), "-o", output)

    assert refused.returncode == 1
    assert "--force" in refused.stderr
    assert output.read_text(encoding="utf-8") == "sentinel"

    replaced = run_cli(
        source,
        "1x1",
        *neutral_flags(),
        "--format",
        "text",
        "--force",
        "--quiet",
        "-o",
        output,
    )
    assert replaced.returncode == 0
    assert replaced.stderr == ""
    assert output.read_text(encoding="utf-8") == "@\n"


def test_cli_reports_missing_output_directory_without_traceback(
    tmp_path: Path,
    save_image: Callable[[Image.Image, str], Path],
    run_cli,
) -> None:
    source = save_image(Image.new("RGB", (1, 1), "white"), "source.png")
    output = tmp_path / "does-not-exist" / "art.txt"

    result = run_cli(source, "1x1", *neutral_flags(), "-o", output)

    assert result.returncode == 1
    assert "diretorio de saida nao existe" in result.stderr
    assert "Traceback" not in result.stderr
    assert not output.exists()
