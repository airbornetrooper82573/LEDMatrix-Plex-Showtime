"""Plex Showtime v1.6.2 for ChuckBuilds LEDMatrix.

Improves TV episode-line scrolling with its own trigger ratio and moves the
standard movie/media marquee onto measured font geometry so subtitle glyphs
are not clipped vertically on 32px displays.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from manager_v13 import PlexShowtimePlugin as PlexShowtimePluginV161


class PlexShowtimePlugin(PlexShowtimePluginV161):
    """Plex Showtime with reliable TV subtitle scrolling and measured movie rows."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self.episode_scroll_trigger_ratio = max(
            0.40,
            min(1.00, float(config.get("episode_scroll_trigger_ratio", 0.70))),
        )
        self.media_row_gap = max(0, min(4, int(config.get("media_row_gap", 1))))

        self.logger.info(
            "Plex Showtime v1.6.2: title_trigger=%.2f episode_trigger=%.2f media_row_gap=%d",
            self.scroll_trigger_ratio,
            self.episode_scroll_trigger_ratio,
            self.media_row_gap,
        )

    def _tv_scroll_requirements(self, item):
        """Use independent trigger ratios for show-name and episode rows."""
        if not self._is_recent_tv_episode(item):
            return False, False

        g = self._tv_geometry()
        probe = Image.new("RGB", (1, 1), "black")
        draw = ImageDraw.Draw(probe)
        show_name = item.grandparent_title or item.parent_title or item.title or "TV"
        episode_line = self._episode_line(item)

        title_width = self._text_width(draw, show_name, self._font_title)
        episode_width = self._text_width(draw, episode_line, self._font_subtitle)
        title_threshold = max(1, int(g["w"] * self.scroll_trigger_ratio))
        episode_threshold = max(1, int(g["w"] * self.episode_scroll_trigger_ratio))

        title_needed = bool(
            self.enable_title_scroll and title_width > title_threshold
        )
        episode_needed = bool(
            self.enable_episode_scroll and episode_width > episode_threshold
        )

        self.logger.info(
            "Plex Showtime scroll check TV v1.6.2: area=%d "
            "title_threshold=%d show_width=%d show_scroll=%s "
            "episode_threshold=%d episode_width=%d episode_scroll=%s "
            "show='%s' episode='%s'",
            g["w"],
            title_threshold,
            title_width,
            title_needed,
            episode_threshold,
            episode_width,
            episode_needed,
            show_name,
            episode_line,
        )
        return title_needed, episode_needed

    def _generic_meta_line(self, item) -> str:
        label = {
            "movie": "MOVIE",
            "show": "TV",
            "season": "TV",
            "episode": "TV",
            "clip": "TV",
            "artist": "MUSIC",
            "album": "MUSIC",
            "track": "MUSIC",
        }.get(item.media_type, (item.media_type or "").upper())

        meta = [label] if label else []
        if item.media_type == "episode" and item.subtitle:
            meta.append(item.subtitle)
        elif self.show_year and item.year:
            meta.append(item.year)
        elif item.subtitle:
            meta.append(item.subtitle)
        return "  |  ".join(meta)

    def _generic_geometry(self):
        """Measured three-row geometry for movies and other non-TV-special items."""
        art_w = min(max(self.H, self.artwork_width), max(self.H, self.W - 120))
        x = art_w + self.accent_width + 6
        w = max(1, self.W - x - 5)

        probe = Image.new("RGB", (1, 1), "black")
        draw = ImageDraw.Draw(probe)
        h_top, _, h_h = self._font_metrics(draw, self._font_heading)
        t_top, _, t_h = self._font_metrics(draw, self._font_title)
        s_top, _, s_h = self._font_metrics(draw, self._font_subtitle)

        heading_h = h_h if self.show_heading else 0
        gap_count = 2 if self.show_heading else 1
        gaps = self.media_row_gap * gap_count
        required = heading_h + t_h + s_h + gaps
        top_pad = max(0, (self.H - required) // 2)

        heading_y = top_pad
        title_y = heading_y + heading_h + (self.media_row_gap if self.show_heading else 0)
        subtitle_y = title_y + t_h + self.media_row_gap

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

    def _render_generic_with_title_offset(self, item, offset=0):
        """Render non-TV-special media using measured/clipped text strips."""
        g = self._generic_geometry()
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
                item.source,
                self._font_heading,
                g["w"],
                g["heading_h"],
                g["heading_top"],
                0,
                self.title_scroll_gap,
                (229, 160, 13),
            )
            canvas.paste(heading, (g["x"], g["heading_y"]))

        title = self._title_for_item(item)
        title_strip = self._draw_scrolling_strip(
            title,
            self._font_title,
            g["w"],
            g["title_h"],
            g["title_top"],
            offset,
            self.title_scroll_gap,
            (255, 255, 255),
        )
        canvas.paste(title_strip, (g["x"], g["title_y"]))

        meta_line = self._generic_meta_line(item)
        if meta_line:
            subtitle_strip = self._draw_scrolling_strip(
                meta_line,
                self._font_subtitle,
                g["w"],
                g["subtitle_h"],
                g["subtitle_top"],
                0,
                self.title_scroll_gap,
                (190, 190, 190),
            )
            canvas.paste(subtitle_strip, (g["x"], g["subtitle_y"]))

        if self.show_panel_dividers:
            draw = ImageDraw.Draw(canvas)
            for px in range(self.panel_width, self.W, self.panel_width):
                draw.line((px, 0, px, self.H - 1), fill=(20, 20, 20))

        return canvas

    def _render_with_title_offset(self, item, offset=0):
        # Preserve the dedicated dual-row Recently Added TV renderer.
        if self._is_recent_tv_episode(item):
            return super()._render_with_title_offset(item, offset)
        # Movies and all other standard marquee items now use measured rows.
        return self._render_generic_with_title_offset(item, offset)

    def get_info(self):
        info = super().get_info()
        info.update({
            "tv_display_version": "1.6.2-subtitle-scroll",
            "episode_scroll_trigger_ratio": self.episode_scroll_trigger_ratio,
            "media_row_gap": self.media_row_gap,
        })
        return info
