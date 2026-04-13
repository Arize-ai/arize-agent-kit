"""Tests for the VS Code activity bar icon SVG."""

import os
import xml.etree.ElementTree as ET

import pytest

ICON_PATH = os.path.join(
    os.path.dirname(__file__), "..", "vscode-extension", "media", "icon.svg"
)


@pytest.fixture
def svg_root():
    tree = ET.parse(ICON_PATH)
    return tree.getroot()


@pytest.fixture
def svg_content():
    with open(ICON_PATH, "r") as f:
        return f.read()


NS = {"svg": "http://www.w3.org/2000/svg"}


class TestIconExists:
    def test_file_exists(self):
        assert os.path.isfile(ICON_PATH), f"Icon file not found at {ICON_PATH}"

    def test_file_under_1kb(self):
        size = os.path.getsize(ICON_PATH)
        assert size < 1024, f"Icon is {size} bytes, must be under 1KB"

    def test_file_is_not_empty(self):
        assert os.path.getsize(ICON_PATH) > 0


class TestSvgStructure:
    def test_valid_xml(self, svg_content):
        """SVG must be valid XML."""
        ET.fromstring(svg_content)

    def test_root_element_is_svg(self, svg_root):
        assert svg_root.tag == "{http://www.w3.org/2000/svg}svg"

    def test_has_xmlns(self, svg_content):
        assert 'xmlns="http://www.w3.org/2000/svg"' in svg_content

    def test_has_viewbox(self, svg_root):
        viewbox = svg_root.get("viewBox")
        assert viewbox is not None, "SVG must have a viewBox attribute"

    def test_viewbox_is_square(self, svg_root):
        """Activity bar icons should be square."""
        viewbox = svg_root.get("viewBox")
        parts = viewbox.split()
        assert len(parts) == 4
        width = float(parts[2]) - float(parts[0])
        height = float(parts[3]) - float(parts[1])
        assert width == height, f"viewBox is {width}x{height}, should be square"

    def test_viewbox_size_acceptable(self, svg_root):
        """Icon should be 16x16 or 24x24 as specified."""
        viewbox = svg_root.get("viewBox")
        parts = viewbox.split()
        size = float(parts[2]) - float(parts[0])
        assert size in (16, 24), f"viewBox size is {size}, expected 16 or 24"


class TestTheming:
    """VS Code activity bar icons must use currentColor for theming."""

    def test_root_fill_is_current_color(self, svg_root):
        fill = svg_root.get("fill")
        assert fill == "currentColor", (
            f"Root fill is '{fill}', must be 'currentColor' for VS Code theming"
        )

    def test_no_hardcoded_colors(self, svg_content):
        """No hex colors, rgb(), or named colors (except 'none' and 'currentColor')."""
        import re

        # Check for hex colors
        hex_colors = re.findall(r"#[0-9a-fA-F]{3,8}", svg_content)
        assert hex_colors == [], f"Found hardcoded hex colors: {hex_colors}"

        # Check for rgb/rgba
        rgb_colors = re.findall(r"rgba?\([^)]+\)", svg_content)
        assert rgb_colors == [], f"Found hardcoded rgb colors: {rgb_colors}"

    def test_strokes_use_current_color(self, svg_root):
        """Any stroke attributes should use currentColor."""
        for elem in svg_root.iter():
            stroke = elem.get("stroke")
            if stroke and stroke != "none":
                assert stroke == "currentColor", (
                    f"Stroke '{stroke}' should be 'currentColor'"
                )

    def test_fills_use_current_color_or_none(self, svg_root):
        """Any explicit fill attributes should be currentColor or none."""
        allowed = {"currentColor", "none", None}
        for elem in svg_root.iter():
            fill = elem.get("fill")
            if fill not in allowed:
                pytest.fail(
                    f"Fill '{fill}' is not allowed. Use 'currentColor' or 'none'."
                )


class TestIconContent:
    """Verify the icon has meaningful visual content."""

    def test_has_path_elements(self, svg_root):
        paths = svg_root.findall("svg:path", NS)
        assert len(paths) >= 1, "Icon must contain at least one path element"

    def test_paths_have_d_attribute(self, svg_root):
        for path in svg_root.findall("svg:path", NS):
            d = path.get("d")
            assert d is not None and len(d) > 0, "Path elements must have a 'd' attribute"

    def test_no_text_elements(self, svg_root):
        """Activity bar icons should not use text elements (font rendering varies)."""
        texts = svg_root.findall("svg:text", NS)
        assert len(texts) == 0, "Icon should not contain <text> elements"

    def test_no_image_elements(self, svg_root):
        """SVG should be vector only, no embedded images."""
        images = svg_root.findall("svg:image", NS)
        assert len(images) == 0, "Icon should not contain <image> elements"

    def test_no_script_elements(self, svg_content):
        """No scripts in the SVG."""
        assert "<script" not in svg_content.lower()
