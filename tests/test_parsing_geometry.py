from __future__ import annotations

import argparse

import pytest
from PIL import Image

import image2ascii as app


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("100x50", (100, 50)),
        (" 70 X 35 ", (70, 35)),
        ("9×4", (9, 4)),
        ("1x1", (1, 1)),
    ],
)
def test_parse_size_accepts_supported_separators(value: str, expected: tuple[int, int]) -> None:
    assert app.parse_size(value) == expected


@pytest.mark.parametrize("value", ["", "20", "20*10", "0x1", "1x0", "-1x2", "1.5x2", "2x"])
def test_parse_size_rejects_invalid_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        app.parse_size(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("red", (255, 0, 0)),
        ("#0f8", (0, 255, 136)),
        ("#102030", (16, 32, 48)),
        ("rgb(1, 2, 3)", (1, 2, 3)),
    ],
)
def test_parse_rgb(value: str, expected: tuple[int, int, int]) -> None:
    assert app.parse_rgb(value) == expected


def test_parse_rgb_rejects_unknown_color() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="cor invalida"):
        app.parse_rgb("definitely-not-a-color")


def test_parse_background_accepts_auto_case_insensitively_and_rgb() -> None:
    assert app.parse_background(" AUTO ") == "auto"
    assert app.parse_background("#010203") == (1, 2, 3)


@pytest.mark.parametrize("parser", [app.finite_positive, app.finite_nonnegative])
@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_float_parsers_reject_non_finite_values(parser, value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="finito"):
        parser(value)


@pytest.mark.parametrize("value", ["0", "-0.1", "-10"])
def test_finite_positive_rejects_zero_and_negative(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        app.finite_positive(value)


@pytest.mark.parametrize(("value", "expected"), [("0", 0), ("255", 255)])
def test_byte_value_boundaries(value: str, expected: int) -> None:
    assert app.byte_value(value) == expected


@pytest.mark.parametrize("value", ["-1", "256", "1.5"])
def test_byte_value_rejects_out_of_range(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        app.byte_value(value)


@pytest.mark.parametrize("charset", ["a", "a\n", "a\t", "a\x1b", " 😀", " e\u0301"])
def test_validate_charset_rejects_unsafe_or_non_single_width_characters(charset: str) -> None:
    with pytest.raises(ValueError):
        app.validate_charset(charset)


@pytest.mark.parametrize("charset", [" @", " .:+#@", " ░▒▓█"])
def test_validate_charset_accepts_single_column_ramps(charset: str) -> None:
    assert app.validate_charset(charset) == charset


@pytest.mark.parametrize(
    ("size", "width", "height", "aspect", "expected"),
    [
        ((80, 30), None, None, 0.5, (80, 30)),
        (None, 100, 40, 0.5, (100, 40)),
        (None, 100, None, 0.5, (100, 25)),
        (None, None, 25, 0.5, (100, 25)),
        (None, None, None, 0.5, (app.DEFAULT_WIDTH, 25)),
    ],
)
def test_resolve_grid(
    size: tuple[int, int] | None,
    width: int | None,
    height: int | None,
    aspect: float,
    expected: tuple[int, int],
) -> None:
    assert app.resolve_grid(200, 100, size, width, height, aspect) == expected


@pytest.mark.parametrize("fit", ["stretch", "cover"])
def test_fit_dimensions_fill_requested_grid(fit: str) -> None:
    assert app.fit_dimensions(400, 100, 80, 40, 0.5, fit) == (80, 40)


def test_fit_dimensions_contain_landscape_and_portrait() -> None:
    assert app.fit_dimensions(400, 100, 80, 40, 0.5, "contain") == (80, 10)
    assert app.fit_dimensions(100, 400, 80, 40, 0.5, "contain") == (20, 40)


def test_crop_for_cover_is_centered_horizontally() -> None:
    image = Image.new("RGB", (6, 2))
    image.putdata([(x, 0, 0) for _y in range(2) for x in range(6)])

    cropped = app.crop_for_cover(image, cols=2, rows=2, aspect=1.0)

    assert cropped.size == (2, 2)
    assert [cropped.getpixel((x, 0))[0] for x in range(2)] == [2, 3]


def test_crop_for_cover_is_centered_vertically() -> None:
    image = Image.new("RGB", (2, 6))
    image.putdata([(0, y, 0) for y in range(6) for _x in range(2)])

    cropped = app.crop_for_cover(image, cols=2, rows=2, aspect=1.0)

    assert cropped.size == (2, 2)
    assert [cropped.getpixel((0, y))[1] for y in range(2)] == [2, 3]


def test_validate_grid_enforces_dimension_and_cell_limits() -> None:
    app.validate_grid(1, 1)
    app.validate_grid(app.MAX_GRID_DIMENSION, 1)
    with pytest.raises(ValueError, match="dimensao"):
        app.validate_grid(app.MAX_GRID_DIMENSION + 1, 1)
    with pytest.raises(ValueError, match="amostras"):
        app.validate_grid(2_000, 1_001)
    with pytest.raises(ValueError, match="amostras"):
        app.validate_grid(500, 501, sample_multiplier=8)


def test_validate_grid_allow_large_only_bypasses_safety_limits() -> None:
    app.validate_grid(app.MAX_GRID_DIMENSION + 1, 1, allow_large=True)
    with pytest.raises(ValueError, match="positivas"):
        app.validate_grid(0, 10, allow_large=True)


@pytest.mark.parametrize(
    ("requested", "output", "color_mode", "expected"),
    [
        ("text", None, "image", "text"),
        ("auto", "art.HTML", "none", "html"),
        ("auto", None, "image", "ansi"),
        ("auto", None, "none", "text"),
    ],
)
def test_resolve_output_format(
    requested: str, output: str | None, color_mode: str, expected: str
) -> None:
    assert app._resolve_output_format(requested, output, color_mode) == expected


def test_paint_background_makes_auto_output_ansi() -> None:
    assert app._resolve_output_format("auto", None, "none", paint_background=True) == "ansi"
