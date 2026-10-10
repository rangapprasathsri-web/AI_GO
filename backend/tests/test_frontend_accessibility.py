"""
Automated Frontend Accessibility & Honesty Specification Verification Suite.

Validates the static structure of frontend/index.html:
- Single H1 per page
- WCAG AA accessibility attributes on interactive controls (aria-checked, role, tabIndex)
- Modal dialog accessibility attributes (role="dialog", aria-modal="true", aria-labelledby)
- Honesty labels and watermarks ("DEMO PLACEHOLDER", "simulated", "estimated savings vs maximum tier (not run)")
- Self-hosted Geist font references (no external runtime CDN)
- Responsive viewport meta tag
- Explicit text origin badges (Simulated, Estimated, Provider-reported, Measured)
"""

from pathlib import Path
from bs4 import BeautifulSoup
import pytest

FRONTEND_PATH = Path(__file__).resolve().parent.parent.parent / "frontend" / "index.html"


@pytest.fixture(scope="module")
def html_soup():
    assert FRONTEND_PATH.exists(), f"Frontend index.html missing at {FRONTEND_PATH}"
    with open(FRONTEND_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    return BeautifulSoup(content, "html.parser")


def test_single_h1_heading_structure(html_soup):
    """Semantic HTML requirement: Exactly one h1 per page."""
    h1_elements = html_soup.find_all("h1")
    assert len(h1_elements) == 1, f"Expected exactly 1 <h1> tag, found {len(h1_elements)}"
    assert "Right effort." in h1_elements[0].get_text()


def test_responsive_viewport_meta_tag(html_soup):
    """Mobile responsiveness: Viewport meta tag properly configured."""
    viewport = html_soup.find("meta", attrs={"name": "viewport"})
    assert viewport is not None
    assert "width=device-width" in viewport.get("content", "")


def test_self_hosted_fonts_no_google_fonts_cdn(html_soup):
    """Typography requirement: Geist font is self-hosted with no runtime Google Fonts CDN."""
    links = html_soup.find_all("link", rel="stylesheet")
    for link in links:
        href = link.get("href", "")
        assert "fonts.googleapis.com" not in href, "Found unauthorized runtime Google Fonts CDN request"


def test_honesty_labels_present_in_markup(html_soup):
    """Honesty constraints: Disclaimers and placeholder marks must remain prominent."""
    text_content = html_soup.get_text()
    assert "DEMO PLACEHOLDER" in text_content
    assert "estimated avoided compute vs the Maximum tier baseline (not run)" in text_content.lower() or \
           "avoided compute vs the maximum tier baseline (not run)" in text_content.lower()
    assert "not estimated" in text_content.lower()
    assert "simulated" in text_content.lower()


def test_modal_accessibility_attributes(html_soup):
    """Accessible modal requirements: role='dialog', aria-modal='true', labeled."""
    modal = html_soup.find(id="accessibleModal")
    assert modal is not None
    assert modal.get("role") == "dialog"
    assert modal.get("aria-modal") == "true"
    assert modal.get("aria-labelledby") == "modalTitle"


def test_origin_badges_carry_text_labels(html_soup):
    """Origin badges must never rely on color alone; text label must be explicit."""
    badges = html_soup.find_all(class_=lambda c: c and "origin-badge" in c)
    assert len(badges) >= 4, f"Expected at least 4 origin badges, found {len(badges)}"
    for badge in badges:
        text = badge.get_text(strip=True)
        assert len(text) > 0, "Origin badge missing visible text label"


def test_all_interactive_purpose_cards_have_keyboard_support(html_soup):
    """Quality purposes must have role='radio', aria-checked, and tabindex for keyboard access."""
    cards = html_soup.find_all(class_=lambda c: c and "purpose-card" in c)
    assert len(cards) == 6, f"Expected 6 Section 4 purpose cards, found {len(cards)}"
    for card in cards:
        assert card.get("role") == "radio"
        assert card.get("tabindex") == "0"
        assert card.get("aria-checked") in ["true", "false"]


def test_quality_tier_selector_cards_have_keyboard_support(html_soup):
    """Tier selector cards must be accessible controls with aria-checked and tabindex."""
    tier_cards = html_soup.find_all(class_=lambda c: c and "tier-card" in c)
    assert len(tier_cards) == 3, f"Expected 3 quality tiers, found {len(tier_cards)}"
    for card in tier_cards:
        assert card.get("role") == "radio"
        assert card.get("tabindex") == "0"
        assert card.get("aria-checked") in ["true", "false"]
