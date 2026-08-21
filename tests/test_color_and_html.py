from __future__ import annotations

import re

import pytest

import image2ascii as app


@pytest.mark.parametrize(
    ("rgb", "expected"),
    [
        ((0, 0, 0), 0),
        ((255, 0, 0), 196),
        ((95, 135, 175), 67),
        ((128, 128, 128), 244),
        ((255, 255, 255), 15),
    ],
)
def test_ansi256_uses_nearest_xterm_palette(rgb: tuple[int, int, int], expected: int) -> None:
    assert app.ansi256_code(*rgb) == expected


def test_ansi256_palette_has_every_code_exactly_once() -> None:
    codes = [entry[3] for entry in app.ANSI256_PALETTE]
    assert len(codes) == 256
    assert sorted(codes) == list(range(256))


def test_ansi_escape_generation() -> None:
    assert app.fg_escape((1, 2, 3), "truecolor") == "\x1b[38;2;1;2;3m"
    assert app.bg_escape((1, 2, 3), "truecolor") == "\x1b[48;2;1;2;3m"
    gray_code = app.ansi256_code(128, 128, 128)
    assert app.fg_escape((128, 128, 128), "ansi256") == f"\x1b[38;5;{gray_code}m"
    assert app.bg_escape((128, 128, 128), "ansi256") == f"\x1b[48;5;{gray_code}m"


def test_terminal_renderer_coalesces_colors_that_quantize_to_same_ansi256_code() -> None:
    first = (128, 128, 128)
    second = (129, 129, 129)
    assert app.ansi256_code(*first) == app.ansi256_code(*second)
    artwork = app.Artwork([[app.Cell("A", first), app.Cell("B", second)]], (0, 0, 0))

    [line] = app.artwork_to_terminal_lines(artwork, "ansi256")

    assert line.count("\x1b[38;5;") == 1
    assert line.endswith("AB\x1b[0m")


def test_terminal_renderer_resets_only_changed_channels() -> None:
    artwork = app.Artwork(
        [
            [
                app.Cell("▀", (255, 0, 0), (0, 0, 255)),
                app.Cell("▄", (0, 255, 0)),
                app.Cell(" "),
            ]
        ],
        (0, 0, 0),
    )

    [line] = app.artwork_to_terminal_lines(artwork, "truecolor", keep_trailing_spaces=True)

    assert app.RESET_BG in line
    assert app.RESET_FG in line
    assert line.endswith(" ")
    assert not line.endswith(app.RESET)
    assert "\x1b[48;2;0;0;0m" not in line


def test_terminal_renderer_can_paint_the_artwork_background() -> None:
    artwork = app.Artwork([[app.Cell("@", (0, 0, 0)), app.Cell()]], (255, 255, 255))

    [line] = app.artwork_to_terminal_lines(artwork, "truecolor", paint_background=True)

    assert line.startswith("\x1b[38;2;0;0;0m\x1b[48;2;255;255;255m@")
    assert line.endswith(" \x1b[0m")


def test_text_renderer_trims_only_trailing_blank_cells() -> None:
    artwork = app.Artwork(
        [[app.Cell(), app.Cell("A"), app.Cell(" ", (255, 0, 0)), app.Cell()]],
        (0, 0, 0),
    )

    assert app.artwork_to_text_lines(artwork) == [" A "]
    assert app.artwork_to_text_lines(artwork, keep_trailing_spaces=True) == [" A  "]


def test_html_is_complete_escaped_and_uses_artwork_background() -> None:
    artwork = app.Artwork(
        [
            [
                app.Cell("<", (255, 0, 1), (0, 2, 3)),
                app.Cell("&", (255, 0, 1), (0, 2, 3)),
                app.Cell(">"),
            ]
        ],
        (1, 2, 3),
    )

    document = app.artwork_to_html(artwork, title='<script>alert("x")</script>')

    assert document.startswith("<!doctype html>")
    assert document.endswith("</html>\n")
    assert "<script>alert" not in document
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in document
    assert "background: #010203" in document
    assert '<span style="color:#ff0001;background:#000203">&lt;&amp;</span>&gt;' in document
    assert "\x1b" not in document


def test_html_groups_adjacent_cells_with_identical_styles() -> None:
    color = (12, 34, 56)
    artwork = app.Artwork(
        [[app.Cell("A", color), app.Cell("B", color), app.Cell("C", (1, 2, 3))]],
        (255, 255, 255),
    )

    document = app.artwork_to_html(artwork)
    art = re.search(r"<pre[^>]*>(.*)</pre>", document, re.DOTALL)

    assert art is not None
    assert art.group(1).count("<span") == 2
    assert '<span style="color:#0c2238">AB</span>' in art.group(1)


def test_html_preserves_an_initial_blank_pre_line() -> None:
    artwork = app.Artwork([[app.Cell()], [app.Cell("@")]], (0, 0, 0))

    document = app.artwork_to_html(artwork)

    # Evita a regra HTML que descarta o primeiro LF de um elemento <pre>.
    assert '<pre role="img" aria-label="Arte ASCII"><i hidden></i>\n@</pre>' in document


def test_html_trailing_space_policy() -> None:
    artwork = app.Artwork([[app.Cell("X"), app.Cell(), app.Cell()]], (0, 0, 0))

    trimmed = app.artwork_to_html(artwork, keep_trailing_spaces=False)
    preserved = app.artwork_to_html(artwork, keep_trailing_spaces=True)

    assert ">X</pre>" in trimmed
    assert ">X  </pre>" in preserved
