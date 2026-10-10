"""Regression guard for shared form styling in static/css/portal.css."""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class SelectArrowCssTests(SimpleTestCase):
    """The chevron of <select class="form-select"> must not overlap its text."""

    def _css(self):
        path = Path(settings.BASE_DIR) / 'static' / 'css' / 'portal.css'
        return path.read_text(encoding='utf-8')

    def _form_select_block(self, css):
        # The rule body that reserves space for the arrow.
        match = re.search(
            r'\.form-select[^{}]*\{([^{}]*padding-right:\s*2\.5rem[^{}]*)\}',
            css,
        )
        return match.group(1) if match else None

    def test_form_select_reserves_space_for_arrow(self):
        block = self._form_select_block(self._css())
        self.assertIsNotNone(
            block,
            'Expected a .form-select rule reserving padding-right for the arrow',
        )
        self.assertIn('padding-right: 2.5rem', block)

    def test_form_select_truncates_and_anchors_arrow(self):
        block = self._form_select_block(self._css())
        self.assertIsNotNone(block)
        self.assertIn('text-overflow: ellipsis', block)
        self.assertIn('background-position: right 0.75rem center', block)
