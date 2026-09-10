"""Plex Showtime v1.6.1 for ChuckBuilds LEDMatrix.

Improves movie and TV text scrolling reliability by integrating with
DisplayManager.set_scrolling_state(), adding a configurable trigger ratio, and
logging measured row widths. Long TV show and episode rows can now begin
scrolling before they are fully clipped.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from manager_v12 import PlexShowtimePlugin as PlexShowtimePluginV160


class PlexShowtimePlugin(PlexShowtimePluginV160):
    """Plex Showtime with LEDMatrix-native scroll-state integration."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self.scroll_trigger_ratio = max(
            0.50, min(1.00, float(config.get("scroll_trigger_ratio", 0.85)))
        )
        self.logger.info(
            "Plex Showtime v1.6.1 scrolling: trigger_ratio=%.2f display=%dx%d",
            self.scroll_trigger_ratio,
            self.W,
            self.H,
        )

    def _scroll_threshold(self, width: int) -> int:
        return max(1, int(width * self.scroll_trigger_ratio))

    def _tv_scroll_requirements(self, item):
        if not self._is_recent_tv_episode(item):
            return False, False

        g = self._tv_geometry()
        probe = Image.new("RGB", (1, 1), "black")
        draw = ImageDraw.Draw(probe)
        show_name = item.grandparent_title or item.parent_title or item.title or "TV"
        episode_line = self._episode_line(item)

        title_width = self._text_width(draw, show_name, self._font_title)
        episode_width = self._text_width(draw, episode_line, self._font_subtitle)
        threshold = self._scroll_threshold(g["w"])

        title_needed = bool(
            self.enable_title_scroll and title_width > threshold
        )
        episode_needed = bool(
            self.enable_episode_scroll and episode_width > threshold
        )

        self.logger.info(
            "Plex Showtime scroll check TV: area=%d threshold=%d "
            "show_width=%d show_scroll=%s episode_width=%d episode_scroll=%s "
            "show='%s' episode='%s'",
            g["w"],
            threshold,
            title_width,
            title_needed,
            episode_width,
            episode_needed,
            show_name,
            episode_line,
        )
        return title_needed, episode_needed

    def _title_needs_scroll(self, item):
        if self._is_recent_tv_episode(item):
            title_needed, episode_needed = self._tv_scroll_requirements(item)
            return title_needed or episode_needed

        if not self.enable_title_scroll or item is None:
            return False

        _, _, width, _ = self._title_geometry()
        probe = Image.new("RGB", (1, 1), "black")
        draw = ImageDraw.Draw(probe)
        title = self._title_for_item(item)
        title_width = self._text_width(draw, title, self._font_title)
        threshold = self._scroll_threshold(width)
        needed = title_width > threshold

        self.logger.info(
            "Plex Showtime scroll check title: type=%s area=%d threshold=%d "
            "text_width=%d scroll=%s title='%s'",
            getattr(item, "media_type", "unknown"),
            width,
            threshold,
            title_width,
            needed,
            title,
        )
        return needed

    def _scroll_worker(self, generation, item, duration):
        """Run the inherited renderer while advertising active scrolling.

        LEDMatrix exposes set_scrolling_state() specifically so animated
        plugins can prevent deferred display work from racing with an active
        scroll. Older Plex Showtime releases updated frames without setting
        this state, which could make scrolling appear static or intermittent.
        """
        scrolling_state_set = False
        try:
            if hasattr(self.display_manager, "set_scrolling_state"):
                self.display_manager.set_scrolling_state(True)
                scrolling_state_set = True

            self.logger.info(
                "Plex Showtime scroll START: title='%s' duration=%.1fs fps=%d",
                self._title_for_item(item),
                duration,
                self.title_scroll_fps,
            )
            return super()._scroll_worker(generation, item, duration)
        finally:
            if scrolling_state_set:
                try:
                    self.display_manager.set_scrolling_state(False)
                except Exception as exc:
                    self.logger.debug("Could not release scrolling state: %s", exc)
            self.logger.info(
                "Plex Showtime scroll STOP: title='%s'",
                self._title_for_item(item) if item is not None else "<none>",
            )

    def get_info(self):
        info = super().get_info()
        info.update({
            "tv_display_version": "1.6.1-native-scroll-state",
            "scroll_trigger_ratio": self.scroll_trigger_ratio,
        })
        return info
