"""Plex Showtime v1.5.0 for ChuckBuilds LEDMatrix.

Adds optional horizontal marquee scrolling for oversized media titles while
keeping short titles static. Scrolling runs only for the active display window
and preserves the existing 320x32 artwork/title/metadata layout.
"""

from __future__ import annotations

import threading
import time
from PIL import Image, ImageDraw

from manager_v7 import PlexShowtimePlugin as PlexShowtimePluginV142


class PlexShowtimePlugin(PlexShowtimePluginV142):
    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self.enable_title_scroll = bool(config.get("enable_title_scroll", True))
        self.title_scroll_speed = max(1.0, float(config.get("title_scroll_speed", 14.0)))
        self.title_scroll_pause = max(0.0, float(config.get("title_scroll_pause", 1.25)))
        self.title_scroll_gap = max(8, int(config.get("title_scroll_gap", 28)))
        self.title_scroll_fps = max(5, min(30, int(config.get("title_scroll_fps", 15))))
        self._scroll_generation = 0
        self._scroll_lock = threading.Lock()
        self.logger.info(
            "Plex Showtime v1.5.0 title scroll: enabled=%s speed=%.1f pause=%.2f gap=%d fps=%d",
            self.enable_title_scroll,
            self.title_scroll_speed,
            self.title_scroll_pause,
            self.title_scroll_gap,
            self.title_scroll_fps,
        )

    def _title_for_item(self, item):
        if item.source == "RECENTLY ADDED" and item.media_type in ("episode", "clip"):
            return item.grandparent_title or item.parent_title or item.title or "TV"
        return item.display_title

    def _title_geometry(self):
        art_w = min(max(self.H, self.artwork_width), max(self.H, self.W - 120))
        x = art_w + self.accent_width + 6
        w = max(1, self.W - x - 5)
        y = 1 + (self.heading_font_size + 2 if self.show_heading else 0)
        return art_w, x, w, y

    def _render_with_title_offset(self, item, offset=0):
        # Start with the established renderer so artwork, heading and metadata
        # remain identical to the previous release.
        canvas = super()._render_marquee(item)
        _, x, w, y = self._title_geometry()
        title = self._title_for_item(item)
        draw = ImageDraw.Draw(canvas)

        # Clear only the title row, then redraw it clipped to its own strip.
        title_h = max(self.title_font_size + 3, 12)
        draw.rectangle((x, y, min(self.W - 1, x + w - 1), min(self.H - 1, y + title_h - 1)), fill="black")

        strip = Image.new("RGB", (w, title_h), "black")
        sdraw = ImageDraw.Draw(strip)
        text_width = self._text_width(sdraw, title, self._font_title)

        if text_width <= w or offset <= 0:
            sdraw.text((0, 0), title, font=self._font_title, fill="white")
        else:
            sdraw.text((-offset, 0), title, font=self._font_title, fill="white")
            # Once the first copy approaches the left edge, draw a second copy
            # after a configurable gap for a seamless marquee loop.
            second_x = text_width + self.title_scroll_gap - offset
            if second_x < w:
                sdraw.text((second_x, 0), title, font=self._font_title, fill="white")

        canvas.paste(strip, (x, y))
        return canvas

    def _title_needs_scroll(self, item):
        if not self.enable_title_scroll or item is None:
            return False
        _, _, w, _ = self._title_geometry()
        probe = Image.new("RGB", (1, 1), "black")
        draw = ImageDraw.Draw(probe)
        return self._text_width(draw, self._title_for_item(item), self._font_title) > w

    def _scroll_worker(self, generation, item, duration):
        _, _, w, _ = self._title_geometry()
        probe = Image.new("RGB", (1, 1), "black")
        draw = ImageDraw.Draw(probe)
        title = self._title_for_item(item)
        text_width = self._text_width(draw, title, self._font_title)
        travel = text_width + self.title_scroll_gap
        frame_delay = 1.0 / self.title_scroll_fps
        started = time.monotonic()

        while time.monotonic() - started < max(0.1, duration - 0.15):
            with self._scroll_lock:
                if generation != self._scroll_generation or self.current_item is not item:
                    return

            elapsed = time.monotonic() - started
            if elapsed <= self.title_scroll_pause:
                offset = 0
            else:
                moving = elapsed - self.title_scroll_pause
                cycle = (travel / self.title_scroll_speed) + self.title_scroll_pause
                phase = moving % cycle
                if phase >= travel / self.title_scroll_speed:
                    offset = 0
                else:
                    offset = int(phase * self.title_scroll_speed)

            try:
                frame = self._render_with_title_offset(item, offset)
                self.display_manager.image.paste(frame, (0, 0))
                self.display_manager.update_display()
            except Exception as exc:
                self.logger.debug("Title scroll stopped: %s", exc)
                return
            time.sleep(frame_delay)

    def display(self, force_clear=False):
        try:
            if force_clear:
                self.display_manager.clear()
            if self.current_item is None:
                self.update()

            item = self.current_item
            if item is None:
                self.display_manager.image.paste(self._render(), (0, 0))
                self.display_manager.update_display()
                return True

            frame = self._render_with_title_offset(item, 0)
            self.display_manager.image.paste(frame, (0, 0))
            self.display_manager.update_display()

            with self._scroll_lock:
                self._scroll_generation += 1
                generation = self._scroll_generation

            if self._title_needs_scroll(item):
                duration = float(self.config.get("display_duration", 20))
                thread = threading.Thread(
                    target=self._scroll_worker,
                    args=(generation, item, duration),
                    daemon=True,
                    name="plex-showtime-title-scroll",
                )
                thread.start()
                self.logger.debug("Started title marquee for '%s'", self._title_for_item(item))
            return True
        except Exception as exc:
            self.logger.error("Display failed: %s", exc, exc_info=True)
            return False

    def cleanup(self):
        with self._scroll_lock:
            self._scroll_generation += 1
        try:
            return super().cleanup()
        except AttributeError:
            return None

    def get_info(self):
        info = super().get_info()
        info.update({
            "enable_title_scroll": self.enable_title_scroll,
            "title_scroll_speed": self.title_scroll_speed,
            "title_scroll_pause": self.title_scroll_pause,
        })
        return info
