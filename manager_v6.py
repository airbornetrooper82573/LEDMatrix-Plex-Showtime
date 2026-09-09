"""Plex Showtime v1.4.1 for ChuckBuilds LEDMatrix.

Improves Recently Added TV episode presentation so the marquee clearly shows
both the series name and episode name, with season/episode numbering included
in the compact third line.
"""

from PIL import Image, ImageDraw

from manager_v5 import PlexShowtimePlugin as PlexShowtimePluginV140


class PlexShowtimePlugin(PlexShowtimePluginV140):
    """Plex Showtime with improved Recently Added episode typography."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self.logger.info("Plex Showtime v1.4.1 TV episode display formatting enabled")

    @staticmethod
    def _episode_code(item) -> str:
        if item.parent_index and item.index:
            try:
                return f"S{int(item.parent_index):02d}E{int(item.index):02d}"
            except (TypeError, ValueError):
                pass
        return ""

    def _render_recent_episode_marquee(self, item):
        canvas = Image.new("RGB", (self.W, self.H), "black")
        draw = ImageDraw.Draw(canvas)
        art_w = min(max(self.H, self.artwork_width), max(self.H, self.W - 120))

        if self.current_image:
            art = (
                self._contain(self.current_image, (art_w, self.H))
                if self.current_image.height >= self.current_image.width
                else self._cover(self.current_image, (art_w, self.H))
            )
            canvas.paste(art, (0, 0))

        draw.rectangle(
            (art_w, 0, min(self.W - 1, art_w + self.accent_width - 1), self.H - 1),
            fill=(229, 160, 13),
        )

        x = art_w + self.accent_width + 6
        w = max(1, self.W - x - 5)
        y = 1

        # Line 1: source heading
        if self.show_heading:
            draw.text(
                (x, y),
                self._fit_text(draw, "RECENTLY ADDED", self._font_heading, w),
                font=self._font_heading,
                fill=(229, 160, 13),
            )
            y += self.heading_font_size + 2

        # Line 2: series name, emphasized
        show_name = item.grandparent_title or item.parent_title or item.title or "TV"
        draw.text(
            (x, y),
            self._fit_text(draw, show_name, self._font_title, w),
            font=self._font_title,
            fill=(255, 255, 255),
        )
        y += self.title_font_size + 2

        # Line 3: episode number + episode title
        episode_parts = []
        code = self._episode_code(item)
        if code:
            episode_parts.append(code)
        if item.title and item.title != show_name:
            episode_parts.append(item.title)

        episode_line = "  |  ".join(episode_parts) or "TV EPISODE"
        if y < self.H:
            draw.text(
                (x, y),
                self._fit_text(draw, episode_line, self._font_subtitle, w),
                font=self._font_subtitle,
                fill=(190, 190, 190),
            )

        if self.show_panel_dividers:
            for px in range(self.panel_width, self.W, self.panel_width):
                draw.line((px, 0, px, self.H - 1), fill=(20, 20, 20))

        return canvas

    def _render_marquee(self, item):
        if item.source == "RECENTLY ADDED" and item.media_type in ("episode", "clip"):
            return self._render_recent_episode_marquee(item)
        return super()._render_marquee(item)
