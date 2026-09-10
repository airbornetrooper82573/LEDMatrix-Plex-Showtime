"""Plex Showtime v1.6.0 for ChuckBuilds LEDMatrix.

Adds independent horizontal scrolling for long TV series names and episode
lines, and fixes subtitle clipping by laying out TV rows from actual font
bounding boxes rather than configured font-size guesses.
"""

from __future__ import annotations

import time
from PIL import Image, ImageDraw

from manager_v11 import PlexShowtimePlugin as PlexShowtimePluginV153


class PlexShowtimePlugin(PlexShowtimePluginV153):
    """Plex Showtime with dual-row TV marquee scrolling."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self.enable_episode_scroll = bool(config.get("enable_episode_scroll", True))
        self.episode_scroll_speed = max(
            1.0, float(config.get("episode_scroll_speed", self.title_scroll_speed))
        )
        self.episode_scroll_pause = max(
            0.0, float(config.get("episode_scroll_pause", self.title_scroll_pause))
        )
        self.episode_scroll_gap = max(
            8, int(config.get("episode_scroll_gap", self.title_scroll_gap))
        )
        self.tv_row_gap = max(0, min(4, int(config.get("tv_row_gap", 1))))

        self.logger.info(
            "Plex Showtime v1.6.0 TV scrolling: title=%s episode=%s "
            "title_speed=%.1f episode_speed=%.1f row_gap=%d",
            self.enable_title_scroll,
            self.enable_episode_scroll,
            self.title_scroll_speed,
            self.episode_scroll_speed,
            self.tv_row_gap,
        )

    @staticmethod
    def _is_recent_tv_episode(item) -> bool:
        return bool(
            item
            and item.source == "RECENTLY ADDED"
            and item.media_type in ("episode", "clip")
        )

    def _episode_line(self, item) -> str:
        parts = []
        code = self._episode_code(item)
        if code:
            parts.append(code)
        if item.title:
            parts.append(item.title)
        return "  |  ".join(parts) or "TV EPISODE"

    @staticmethod
    def _font_metrics(draw, font, sample="Ag"):
        """Return actual text top/bottom/height for a font."""
        left, top, right, bottom = draw.textbbox((0, 0), sample, font=font)
        return top, bottom, max(1, bottom - top)

    def _tv_geometry(self):
        """Calculate row positions from real glyph heights, not nominal sizes."""
        art_w = min(max(self.H, self.artwork_width), max(self.H, self.W - 120))
        x = art_w + self.accent_width + 6
        w = max(1, self.W - x - 5)

        probe = Image.new("RGB", (1, 1), "black")
        draw = ImageDraw.Draw(probe)
        h_top, _, h_h = self._font_metrics(draw, self._font_heading)
        t_top, _, t_h = self._font_metrics(draw, self._font_title)
        s_top, _, s_h = self._font_metrics(draw, self._font_subtitle)

        # Keep the complete three-line stack inside the 32px canvas. Reduce
        # inter-row gaps first if the selected fonts are unusually tall.
        heading_h = h_h if self.show_heading else 0
        gaps = self.tv_row_gap * (2 if self.show_heading else 1)
        required = heading_h + t_h + s_h + gaps
        top_pad = max(0, (self.H - required) // 2)

        heading_y = top_pad
        title_y = heading_y + heading_h + (self.tv_row_gap if self.show_heading else 0)
        subtitle_y = title_y + t_h + self.tv_row_gap

        return {
            "art_w": art_w,
            "x": x,
            "w": w,
            "heading_y": heading_y,
            "heading_h": heading_h,
            "heading_top": h_top,
            "title_y": title_y,
            "title_h": t_h,
            "title_top": t_top,
            "subtitle_y": subtitle_y,
            "subtitle_h": s_h,
            "subtitle_top": s_top,
        }

    def _draw_scrolling_strip(self, text, font, width, height, font_top, offset, gap, fill):
        """Draw one clipped text row with its glyph top aligned to the strip."""
        width = max(1, int(width))
        height = max(1, int(height))
        strip = Image.new("RGB", (width, height), "black")
        draw = ImageDraw.Draw(strip)
        text_width = self._text_width(draw, text, font)
        baseline_y = -font_top

        if text_width <= width or offset <= 0:
            draw.text((0, baseline_y), text, font=font, fill=fill)
        else:
            draw.text((-offset, baseline_y), text, font=font, fill=fill)
            second_x = text_width + gap - offset
            if second_x < width:
                draw.text((second_x, baseline_y), text, font=font, fill=fill)
        return strip

    def _render_recent_tv_with_offsets(self, item, title_offset=0, episode_offset=0):
        g = self._tv_geometry()
        canvas = Image.new("RGB", (self.W, self.H), "black")
        draw = ImageDraw.Draw(canvas)

        if self.current_image:
            art = (
                self._contain(self.current_image, (g["art_w"], self.H))
                if self.current_image.height >= self.current_image.width
                else self._cover(self.current_image, (g["art_w"], self.H))
            )
            canvas.paste(art, (0, 0))

        draw.rectangle(
            (
                g["art_w"],
                0,
                min(self.W - 1, g["art_w"] + self.accent_width - 1),
                self.H - 1,
            ),
            fill=(229, 160, 13),
        )

        if self.show_heading and g["heading_h"] > 0:
            heading = self._draw_scrolling_strip(
                "RECENTLY ADDED",
                self._font_heading,
                g["w"],
                g["heading_h"],
                g["heading_top"],
                0,
                self.title_scroll_gap,
                (229, 160, 13),
            )
            canvas.paste(heading, (g["x"], g["heading_y"]))

        show_name = item.grandparent_title or item.parent_title or item.title or "TV"
        title_strip = self._draw_scrolling_strip(
            show_name,
            self._font_title,
            g["w"],
            g["title_h"],
            g["title_top"],
            title_offset,
            self.title_scroll_gap,
            (255, 255, 255),
        )
        canvas.paste(title_strip, (g["x"], g["title_y"]))

        episode_line = self._episode_line(item)
        subtitle_strip = self._draw_scrolling_strip(
            episode_line,
            self._font_subtitle,
            g["w"],
            g["subtitle_h"],
            g["subtitle_top"],
            episode_offset,
            self.episode_scroll_gap,
            (190, 190, 190),
        )
        canvas.paste(subtitle_strip, (g["x"], g["subtitle_y"]))

        if self.show_panel_dividers:
            draw = ImageDraw.Draw(canvas)
            for px in range(self.panel_width, self.W, self.panel_width):
                draw.line((px, 0, px, self.H - 1), fill=(20, 20, 20))

        return canvas

    def _render_with_title_offset(self, item, offset=0):
        # Parent display() calls this for the initial frame. For TV episodes we
        # use the new measured renderer; movies and other content retain the
        # established v1.5 marquee behavior.
        if self._is_recent_tv_episode(item):
            return self._render_recent_tv_with_offsets(item, title_offset=offset, episode_offset=0)
        return super()._render_with_title_offset(item, offset)

    def _tv_scroll_requirements(self, item):
        if not self._is_recent_tv_episode(item):
            return False, False

        g = self._tv_geometry()
        probe = Image.new("RGB", (1, 1), "black")
        draw = ImageDraw.Draw(probe)
        show_name = item.grandparent_title or item.parent_title or item.title or "TV"
        episode_line = self._episode_line(item)

        title_needed = bool(
            self.enable_title_scroll
            and self._text_width(draw, show_name, self._font_title) > g["w"]
        )
        episode_needed = bool(
            self.enable_episode_scroll
            and self._text_width(draw, episode_line, self._font_subtitle) > g["w"]
        )
        return title_needed, episode_needed

    def _title_needs_scroll(self, item):
        if self._is_recent_tv_episode(item):
            title_needed, episode_needed = self._tv_scroll_requirements(item)
            return title_needed or episode_needed
        return super()._title_needs_scroll(item)

    @staticmethod
    def _marquee_offset(elapsed, text_width, gap, speed, pause):
        if elapsed <= pause:
            return 0
        travel = text_width + gap
        scroll_time = travel / speed
        cycle = scroll_time + pause
        phase = (elapsed - pause) % cycle
        if phase >= scroll_time:
            return 0
        return int(phase * speed)

    def _scroll_worker(self, generation, item, duration):
        # Keep the existing movie/title worker untouched. TV episodes get two
        # independently measured/animated rows.
        if not self._is_recent_tv_episode(item):
            return super()._scroll_worker(generation, item, duration)

        title_needed, episode_needed = self._tv_scroll_requirements(item)
        if not title_needed and not episode_needed:
            return

        g = self._tv_geometry()
        probe = Image.new("RGB", (1, 1), "black")
        draw = ImageDraw.Draw(probe)
        show_name = item.grandparent_title or item.parent_title or item.title or "TV"
        episode_line = self._episode_line(item)
        title_width = self._text_width(draw, show_name, self._font_title)
        episode_width = self._text_width(draw, episode_line, self._font_subtitle)
        frame_delay = 1.0 / self.title_scroll_fps
        started = time.monotonic()

        while time.monotonic() - started < max(0.1, duration - 0.15):
            with self._scroll_lock:
                if generation != self._scroll_generation or self.current_item is not item:
                    return

            elapsed = time.monotonic() - started
            title_offset = (
                self._marquee_offset(
                    elapsed,
                    title_width,
                    self.title_scroll_gap,
                    self.title_scroll_speed,
                    self.title_scroll_pause,
                )
                if title_needed
                else 0
            )
            episode_offset = (
                self._marquee_offset(
                    elapsed,
                    episode_width,
                    self.episode_scroll_gap,
                    self.episode_scroll_speed,
                    self.episode_scroll_pause,
                )
                if episode_needed
                else 0
            )

            try:
                frame = self._render_recent_tv_with_offsets(
                    item,
                    title_offset=title_offset,
                    episode_offset=episode_offset,
                )
                self.display_manager.image.paste(frame, (0, 0))
                self.display_manager.update_display()
            except Exception as exc:
                self.logger.debug("TV title/episode scroll stopped: %s", exc)
                return
            time.sleep(frame_delay)

    def get_info(self):
        info = super().get_info()
        info.update({
            "tv_display_version": "1.6.0-dual-scroll",
            "enable_episode_scroll": self.enable_episode_scroll,
            "episode_scroll_speed": self.episode_scroll_speed,
            "tv_row_gap": self.tv_row_gap,
        })
        return info
