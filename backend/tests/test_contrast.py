"""
Automated WCAG 2.1 AA Contrast Ratio Verification Test Suite.

Verifies that every foreground and background color combination defined in the
design tokens and used across the application meets or exceeds the WCAG AA
standard:
- Normal text (< 18pt or < 14pt bold): minimum 4.5:1
- Large text (>= 18pt or >= 14pt bold) and graphical components: minimum 3.0:1
"""

import pytest

def srgb_to_linear(channel: int) -> float:
    """Convert sRGB 8-bit integer channel (0-255) to linear luminance."""
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def relative_luminance(hex_code: str) -> float:
    """Calculate relative luminance per WCAG 2.1 algorithm."""
    hex_clean = hex_code.lstrip('#')
    if len(hex_clean) == 3:
        hex_clean = ''.join([c * 2 for c in hex_clean])
    r = int(hex_clean[0:2], 16)
    g = int(hex_clean[2:4], 16)
    b = int(hex_clean[4:6], 16)
    return 0.2126 * srgb_to_linear(r) + 0.7152 * srgb_to_linear(g) + 0.0722 * srgb_to_linear(b)

def contrast_ratio(hex1: str, hex2: str) -> float:
    """Calculate contrast ratio between two hex colors."""
    l1 = relative_luminance(hex1)
    l2 = relative_luminance(hex2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


THEME_TOKENS = {
    "canvas": "#FFFFFF",
    "surface": "#F7F7FA",
    "border": "#E8E8ED",
    "lavender": "#F2EDFF",
    "ink": "#111113",
    "muted": "#6B6B72",
    "muted_strong": "#55555C",
    "purple_600": "#6E34E2",
    "purple_700": "#5221BA",
    "purple_500": "#9B73F5",
    "green": "#6AAF24",
    "green_text": "#286208",
    "amber_text": "#8A4B00",
    "rose_text": "#B31B38",
}

PAIRS_UNDER_TEST = [
    # (Pair Name, Foreground Token, Background Token, Required Ratio, Element Type)
    ("Ink headline/text on white canvas", "ink", "canvas", 4.5, "normal_text"),
    ("Ink text on pale surface", "ink", "surface", 4.5, "normal_text"),
    ("Muted text on canvas", "muted", "canvas", 4.5, "normal_text"),
    ("Muted-strong body text on canvas", "muted_strong", "canvas", 4.5, "normal_text"),
    ("Muted-strong text on surface", "muted_strong", "surface", 4.5, "normal_text"),
    ("White button text on purple-600 pill", "canvas", "purple_600", 4.5, "normal_text"),
    ("Purple-700 text on lavender metadata chip", "purple_700", "lavender", 4.5, "normal_text"),
    ("Purple-700 text on canvas", "purple_700", "canvas", 4.5, "normal_text"),
    ("Green text on canvas (positive status/savings)", "green_text", "canvas", 4.5, "normal_text"),
    ("Amber warning text on canvas", "amber_text", "canvas", 4.5, "normal_text"),
    ("Rose error text on canvas", "rose_text", "canvas", 4.5, "normal_text"),
    ("White text on dark ink cards", "canvas", "ink", 4.5, "normal_text"),
    ("Purple-500 decorative headline word / UI icon", "purple_500", "canvas", 3.0, "large_text_or_graphic"),
]


@pytest.mark.parametrize("name,fg,bg,required,elem_type", PAIRS_UNDER_TEST)
def test_wcag_contrast_ratio_meets_specification(name, fg, bg, required, elem_type):
    c1 = THEME_TOKENS[fg]
    c2 = THEME_TOKENS[bg]
    ratio = contrast_ratio(c1, c2)
    assert ratio >= required, (
        f"Contrast failure for '{name}': {c1} on {c2} achieves {ratio:.2f}:1, "
        f"which is below required {required}:1 for {elem_type}."
    )


def test_theme_tokens_include_required_palette():
    required_keys = [
        "canvas", "surface", "border", "lavender", "ink",
        "muted", "purple_600", "purple_700", "purple_500", "green"
    ]
    for key in required_keys:
        assert key in THEME_TOKENS, f"Missing required token '{key}' in design system."
