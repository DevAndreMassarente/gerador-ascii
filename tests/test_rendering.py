from __future__ import annotations

from collections.abc import Mapping

import pytest
from PIL import Image

import image2ascii as app


def ascii_art(
    image: Image.Image,
    options: Mapping[str, object],
    **overrides: object,
) -> app.Artwork:
    arguments = dict(options)
    arguments.update(overrides)
    return app.render_ascii_art(
        image,
        cols=int(arguments.pop("cols", image.width)),
        rows=int(arguments.pop("rows", image.height)),
        charset=str(arguments.pop("charset", " @")),
        threshold=int(arguments.pop("threshold", 0)),
        **arguments,
    )


def halfblock_art(
    image: Image.Image,
    options: Mapping[str, object],
    **overrides: object,
) -> app.Artwork:
    arguments = dict(options)
    arguments.update(overrides)
    return app.render_halfblock_art(
        image,
        cols=int(arguments.pop("cols", image.width)),
        rows=int(arguments.pop("rows", image.height // 2)),
        threshold=int(arguments.pop("threshold", 0)),
        **arguments,
    )


def braille_art(
    image: Image.Image,
    options: Mapping[str, object],
    **overrides: object,
) -> app.Artwork:
    arguments = dict(options)
    arguments.update(overrides)
    return app.render_braille_art(
        image,
        cols=int(arguments.pop("cols", image.width // 2)),
        rows=int(arguments.pop("rows", image.height // 4)),
        braille_threshold=int(arguments.pop("braille_threshold", 128)),
        **arguments,
    )


def test_transparent_black_subject_gets_contrasting_background() -> None:
    image = Image.new("RGBA", (3, 3), (0, 0, 0, 0))
    image.putpixel((1, 1), (0, 0, 0, 255))

    assert app.visible_mean_luma(image) == 0
    assert app.choose_background(image) == (255, 255, 255)


@pytest.mark.parametrize(
    ("color", "expected_background"),
    [((255, 255, 255), (255, 255, 255)), ((0, 0, 0), (0, 0, 0))],
)
def test_incidental_alpha_does_not_flip_opaque_background(
    color: tuple[int, int, int], expected_background: tuple[int, int, int]
) -> None:
    image = Image.new("RGBA", (20, 20), (*color, 255))
    image.putpixel((10, 10), (*color, 254))

    assert app.transparency_fraction(image) < 0.01
    assert app.choose_background(image) == expected_background


def test_transparent_black_subject_remains_visible_in_ascii() -> None:
    image = Image.new("RGBA", (3, 3), (0, 0, 0, 0))
    image.putpixel((1, 1), (0, 0, 0, 255))

    artwork = app.render_ascii_art(
        image,
        cols=3,
        rows=3,
        aspect=1.0,
        fit="stretch",
        charset=" @",
        color_mode="none",
        mono_color=(255, 0, 0),
        style="normal",
        contrast=1.0,
        brightness=1.0,
        gamma=1.0,
        edges=0.0,
        polarity="auto",
        threshold=0,
        alpha_threshold=1,
        invert_flag=False,
        disable_auto_invert=False,
        dither="none",
        background="auto",
    )

    assert artwork.background == (255, 255, 255)
    assert artwork.rows[1][1] == app.Cell("@")
    assert sum(cell != app.Cell() for row in artwork.rows for cell in row) == 1


def test_fully_transparent_image_is_blank() -> None:
    image = Image.new("RGBA", (2, 2), (255, 255, 255, 0))

    artwork = app.render_ascii_art(
        image,
        cols=2,
        rows=2,
        aspect=1.0,
        fit="stretch",
        charset=" @",
        color_mode="none",
        mono_color=(255, 0, 0),
        style="normal",
        contrast=1.0,
        brightness=1.0,
        gamma=1.0,
        edges=0.0,
        polarity="auto",
        threshold=0,
        alpha_threshold=1,
        invert_flag=False,
        disable_auto_invert=False,
        background="auto",
    )

    assert artwork.background == (0, 0, 0)
    assert all(cell == app.Cell() for row in artwork.rows for cell in row)


def test_alpha_threshold_is_inclusive(neutral_render_options: dict[str, object]) -> None:
    image = Image.new("RGBA", (2, 1))
    image.putdata([(255, 255, 255, 11), (255, 255, 255, 12)])

    # Both density levels are visible glyphs so this assertion isolates alpha
    # semantics from the low luminance caused by compositing over black.
    artwork = ascii_art(image, neutral_render_options, alpha_threshold=12, charset="@@")

    assert artwork.rows[0] == [app.Cell(), app.Cell("@")]


def test_ascii_density_maps_charset_endpoints(neutral_render_options: dict[str, object]) -> None:
    image = Image.new("RGBA", (3, 1))
    image.putdata([(0, 0, 0, 255), (128, 128, 128, 255), (255, 255, 255, 255)])

    artwork = ascii_art(image, neutral_render_options, charset=" .@")

    assert [cell.char for cell in artwork.rows[0]] == [" ", ".", "@"]


def test_ascii_contain_pads_to_requested_grid(neutral_render_options: dict[str, object]) -> None:
    image = Image.new("RGBA", (4, 1), (255, 255, 255, 255))

    artwork = ascii_art(
        image,
        neutral_render_options,
        cols=4,
        rows=4,
        aspect=1.0,
        fit="contain",
    )

    assert artwork.width == 4
    assert artwork.height == 4
    assert [cell.char for cell in artwork.rows[1]] == ["@", "@", "@", "@"]
    assert all(cell == app.Cell() for cell in artwork.rows[0] + artwork.rows[2] + artwork.rows[3])


@pytest.mark.parametrize(
    ("top", "bottom", "expected"),
    [
        ((0, 0, 0, 0), (0, 0, 0, 0), app.Cell()),
        ((255, 0, 0, 255), (0, 0, 0, 0), app.Cell("▀", (255, 0, 0))),
        ((0, 0, 0, 0), (0, 255, 0, 255), app.Cell("▄", (0, 255, 0))),
        (
            (255, 0, 0, 255),
            (0, 255, 0, 255),
            app.Cell("▀", (255, 0, 0), (0, 255, 0)),
        ),
    ],
)
def test_halfblock_four_alpha_combinations(
    top: tuple[int, int, int, int],
    bottom: tuple[int, int, int, int],
    expected: app.Cell,
    neutral_render_options: dict[str, object],
) -> None:
    image = Image.new("RGBA", (1, 2))
    image.putdata([top, bottom])

    artwork = halfblock_art(
        image,
        neutral_render_options,
        color_mode="image",
        cols=1,
        rows=1,
        alpha_threshold=1,
    )

    assert artwork.rows == [[expected]]


def test_halfblock_uses_full_block_when_both_colors_match(
    neutral_render_options: dict[str, object],
) -> None:
    image = Image.new("RGBA", (1, 2), (12, 34, 56, 255))

    artwork = halfblock_art(image, neutral_render_options, color_mode="image")

    assert artwork.rows == [[app.Cell("█", (12, 34, 56))]]


@pytest.mark.parametrize(
    ("pixels", "glyph"),
    [
        ([(255, 255, 255, 255), (255, 255, 255, 255)], "█"),
        ([(255, 255, 255, 255), (0, 0, 0, 255)], "▀"),
        ([(0, 0, 0, 255), (255, 255, 255, 255)], "▄"),
        ([(0, 0, 0, 255), (0, 0, 0, 255)], " "),
    ],
)
def test_halfblock_without_color_uses_luminance(
    pixels: list[tuple[int, int, int, int]],
    glyph: str,
    neutral_render_options: dict[str, object],
) -> None:
    image = Image.new("RGBA", (1, 2))
    image.putdata(pixels)

    artwork = halfblock_art(image, neutral_render_options, color_mode="none")

    assert artwork.rows[0][0].char == glyph


def test_halfblock_transparent_half_does_not_emit_black_background(
    neutral_render_options: dict[str, object],
) -> None:
    image = Image.new("RGBA", (1, 2))
    image.putdata([(255, 0, 0, 255), (0, 0, 0, 0)])
    artwork = halfblock_art(image, neutral_render_options, color_mode="image")

    [line] = app.artwork_to_terminal_lines(artwork, "truecolor")

    assert "▀" in line
    assert "48;" not in line
    assert app.bg_escape((0, 0, 0), "truecolor") not in line


def test_ordered_dither_produces_stable_bayer_checkerboard() -> None:
    density = Image.new("L", (4, 4), 128)

    levels = app.quantize_density(density, 2, "ordered", threshold=0)

    assert levels == [
        0,
        1,
        0,
        1,
        1,
        0,
        1,
        0,
        0,
        1,
        0,
        1,
        1,
        0,
        1,
        0,
    ]


def test_floyd_steinberg_dither_differs_from_plain_quantization_and_is_deterministic() -> None:
    density = Image.new("L", (4, 4), 128)

    plain = app.quantize_density(density, 2, "none", threshold=0)
    first = app.quantize_density(density, 2, "floyd-steinberg", threshold=0)
    second = app.quantize_density(density, 2, "floyd-steinberg", threshold=0)

    assert plain == [1] * 16
    assert first == second
    assert first != plain
    assert set(first) == {0, 1}


def test_dither_does_not_activate_transparent_pixels() -> None:
    density = Image.new("L", (4, 1), 255)
    alpha = Image.new("L", (4, 1))
    alpha.putdata([255, 0, 11, 12])

    levels = app.quantize_density(
        density,
        2,
        "floyd-steinberg",
        threshold=0,
        alpha=alpha,
        alpha_threshold=12,
    )

    assert levels == [1, -1, -1, 1]


@pytest.mark.parametrize(
    ("cutoff", "expected_first_active"),
    [(0, 1), (32, 33), (64, 65), (127, 128), (200, 201), (255, None)],
)
def test_binary_cutoff_is_applied_directly(cutoff: int, expected_first_active: int | None) -> None:
    density = Image.new("L", (256, 1))
    density.putdata(range(256))

    levels = app.quantize_density(density, 2, "none", cutoff, binary_cutoff=True)
    first_active = next((index for index, level in enumerate(levels) if level == 1), None)

    assert first_active == expected_first_active


def test_ordered_binary_dither_preserves_black_and_white_extremes() -> None:
    black = Image.new("L", (16, 16), 0)
    white = Image.new("L", (16, 16), 255)

    black_levels = app.quantize_density(black, 2, "ordered", 0, binary_cutoff=True)
    white_levels = app.quantize_density(white, 2, "ordered", 0, binary_cutoff=True)

    assert black_levels == [-1] * 256
    assert white_levels == [1] * 256


def test_binary_dithers_apply_cutoff_as_a_black_point() -> None:
    below_cutoff = Image.new("L", (16, 16), 64)
    middle_gray = Image.new("L", (4, 4), 128)

    ordered_black = app.quantize_density(below_cutoff, 2, "ordered", 128, binary_cutoff=True)
    floyd_black = app.quantize_density(below_cutoff, 2, "floyd-steinberg", 128, binary_cutoff=True)
    ordered_middle = app.quantize_density(middle_gray, 2, "ordered", 0, binary_cutoff=True)

    assert ordered_black == [-1] * 256
    assert floyd_black == [-1] * 256
    assert ordered_middle.count(1) == 8


@pytest.mark.parametrize(
    ("position", "expected_codepoint"),
    [(position, 0x2800 + bit) for position, bit in app.BRAILLE_BITS.items()],
)
def test_braille_dot_mapping(
    position: tuple[int, int],
    expected_codepoint: int,
    neutral_render_options: dict[str, object],
) -> None:
    image = Image.new("RGBA", (2, 4), (0, 0, 0, 255))
    image.putpixel(position, (255, 255, 255, 255))

    artwork = braille_art(image, neutral_render_options)

    assert artwork.rows == [[app.Cell(chr(expected_codepoint))]]


def test_braille_all_dots_and_no_dots(
    neutral_render_options: dict[str, object],
) -> None:
    full = braille_art(
        Image.new("RGBA", (2, 4), (255, 255, 255, 255)),
        neutral_render_options,
    )
    empty = braille_art(
        Image.new("RGBA", (2, 4), (0, 0, 0, 255)),
        neutral_render_options,
    )

    assert full.rows == [[app.Cell("⣿")]]
    assert empty.rows == [[app.Cell()]]


def test_braille_image_color_is_average_of_active_dots(
    neutral_render_options: dict[str, object],
) -> None:
    image = Image.new("RGBA", (2, 4), (0, 0, 0, 255))
    image.putpixel((0, 0), (255, 255, 255, 255))
    image.putpixel((1, 0), (255, 255, 0, 255))

    artwork = braille_art(
        image,
        neutral_render_options,
        color_mode="image",
        braille_threshold=128,
    )

    assert artwork.rows == [[app.Cell(chr(0x2800 + 0x01 + 0x08), (255, 255, 128))]]


def test_renderers_do_not_mutate_input(neutral_render_options: dict[str, object]) -> None:
    image = Image.new("RGBA", (2, 4))
    image.putdata([(x * 20, y * 20, 100, (x + y) * 40) for y in range(4) for x in range(2)])
    before = image.tobytes()

    ascii_art(image, neutral_render_options, cols=2, rows=4)
    halfblock_art(image, neutral_render_options, cols=2, rows=2)
    braille_art(image, neutral_render_options, cols=1, rows=1)

    assert image.tobytes() == before
