"""Plex Showtime v1.9.1: scroll full long titles without core scroll-state mode.

Keep all v1.9.0 selection, TV artwork, user filters, and persistent sessions.
The main LEDMatrix scrolling-state flag caused text distortion in the user's
five-panel setup. Plex's existing time-based scrolling worker does not require
that flag. Bypass only the v1.6.1 wrapper that enables it.
"""

from __future__ import annotations

from manager_v17 import PlexShowtimePlugin as PlexShowtimePluginV190
from manager_v12 import PlexShowtimePlugin as PlexShowtimePluginV160


class PlexShowtimePlugin(PlexShowtimePluginV190):
    """Persistent full-title and independent episode scrolling."""

    def _scroll_worker(self, generation, item, duration):
        # Run the full movie/TV scroll implementation directly rather than
        # the v1.6.1 wrapper which calls set_scrolling_state(True). This
        # preserves separate title/episode speeds and offsets and avoids the
        # physical-panel corruption isolated in Home Assistant v1.6.5.
        set_scroll = getattr(self.display_manager, "set_scrolling_state", None)
        if callable(set_scroll):
            set_scroll(False)
        return PlexShowtimePluginV160._scroll_worker(
            self, generation, item, duration
        )

    def get_info(self):
        info = super().get_info()
        info["presentation_version"] = "1.9.1"
        info["scroll_rendering"] = "full-text-without-core-scroll-state"
        return info
