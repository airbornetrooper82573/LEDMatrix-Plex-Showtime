"""Native Plex Showtime plugin for ChuckBuilds LEDMatrix.

Optimized for ultra-wide LEDMatrix installations such as five chained 64x32
panels (320x32). Displays Plex playback, recently added, recently played, or
random library media with aspect-correct artwork and marquee-style typography.
"""

from __future__ import annotations

import io
import random
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps

from src.plugin_system.base_plugin import BasePlugin


@dataclass
class PlexItem:
    source: str
    media_type: str
    title: str
    parent_title: str = ""
    grandparent_title: str = ""
    year: str = ""
    summary: str = ""
    thumb: str = ""
    art: str = ""
    index: str = ""
    parent_index: str = ""

    @property
    def display_title(self) -> str:
        if self.media_type == "episode" and self.grandparent_title:
            return self.grandparent_title
        return self.title or self.parent_title or self.grandparent_title or "Plex"

    @property
    def subtitle(self) -> str:
        if self.media_type == "episode":
            parts = []
            if self.parent_index and self.index:
                try:
                    parts.append(f"S{int(self.parent_index):02d}E{int(self.index):02d}")
                except ValueError:
                    pass
            if self.title:
                parts.append(self.title)
            return " • ".join(parts)
        if self.media_type in ("track", "album") and self.parent_title:
            return self.parent_title
        return self.year


class PlexShowtimePlugin(BasePlugin):
    """Display Plex artwork and metadata natively on LEDMatrix."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        self.plex_url = str(config.get("plex_url", "")).rstrip("/")
        self.plex_token = str(config.get("plex_token", ""))

        self.show_playing = bool(config.get("show_playing", True))
        self.show_recently_added = bool(config.get("show_recently_added", True))
        self.show_recently_played = bool(config.get("show_recently_played", True))
        self.show_library = bool(config.get("show_library", True))

        self.filter_movies = bool(config.get("filter_movies", True))
        self.filter_tv = bool(config.get("filter_tv", True))
        self.filter_music = bool(config.get("filter_music", False))

        self.show_heading = bool(config.get("show_heading", True))
        self.show_year = bool(config.get("show_year", True))
        self.show_summary = bool(config.get("show_summary", False))

        # Do NOT use self.layout here. BasePlugin owns a read-only adaptive
        # layout property named `layout`.
        self.display_layout = str(config.get("layout", "auto"))
        self.artwork_mode = str(config.get("artwork_mode", "auto"))
        self.recent_count = max(1, int(config.get("recent_count", 20)))
        self.live_priority = bool(config.get("live_priority", False))

        self.artwork_width = max(32, int(config.get("artwork_width", 72)))
        self.accent_width = max(1, int(config.get("accent_width", 2)))
        self.show_panel_dividers = bool(config.get("show_panel_dividers", False))
        self.panel_width = max(1, int(config.get("panel_width", 64)))
        self.title_font_size = max(6, int(config.get("title_font_size", 11)))
        self.subtitle_font_size = max(5, int(config.get("subtitle_font_size", 7)))
        self.heading_font_size = max(5, int(config.get("heading_font_size", 6)))

        self.W = int(self.display_manager.width)
        self.H = int(self.display_manager.height)

        self.current_item: Optional[PlexItem] = None
        self.current_image: Optional[Image.Image] = None
        self.last_update = 0.0
        self.last_error = ""

        self._font_heading = self._load_font(self.heading_font_size)
        self._font_subtitle = self._load_font(self.subtitle_font_size)
        self._font_title = self._load_font(self.title_font_size)

        self.logger.info(
            "Plex Showtime initialized for %dx%d (layout=%s, ultra-wide=%s)",
            self.W,
            self.H,
            self.display_layout,
            self.W >= self.H * 5,
        )

    def _load_font(self, size: int):
        for path in (
            Path("assets/fonts/PressStart2P-Regular.ttf"),
            Path("/home/ledpi/LEDMatrix/assets/fonts/PressStart2P-Regular.ttf"),
        ):
            if path.exists():
                try:
                    return ImageFont.truetype(str(path), size)
                except Exception:
                    pass
        return ImageFont.load_default()

    def _plex_xml(self, path: str) -> Optional[ET.Element]:
        if not self.plex_url or not self.plex_token:
            return None
        sep = "&" if "?" in path else "?"
        url = f"{self.plex_url}{path}{sep}X-Plex-Token={urllib.parse.quote(self.plex_token)}"
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "LEDMatrix-Plex-Showtime/1.1.1"}
            )
            with urllib.request.urlopen(req, timeout=8) as response:
                return ET.fromstring(response.read())
        except Exception as exc:
            self.last_error = str(exc)
            self.logger.warning("Plex request failed for %s: %s", path, exc)
            return None

    def _allowed_type(self, media_type: str) -> bool:
        if media_type == "movie":
            return self.filter_movies
        if media_type in ("show", "season", "episode"):
            return self.filter_tv
        if media_type in ("artist", "album", "track"):
            return self.filter_music
        return False

    def _item_from_element(self, element: ET.Element, source: str) -> Optional[PlexItem]:
        media_type = element.get("type", "")
        if not self._allowed_type(media_type):
            return None
        title = element.get("title", "").strip()
        if not title and not element.get("grandparentTitle"):
            return None
        return PlexItem(
            source=source,
            media_type=media_type,
            title=title,
            parent_title=element.get("parentTitle", "").strip(),
            grandparent_title=element.get("grandparentTitle", "").strip(),
            year=element.get("year", "").strip(),
            summary=element.get("summary", "").strip(),
            thumb=element.get("thumb", "").strip(),
            art=element.get("art", "").strip(),
            index=element.get("index", "").strip(),
            parent_index=element.get("parentIndex", "").strip(),
        )

    def _items_from_root(self, root: Optional[ET.Element], source: str) -> List[PlexItem]:
        if root is None:
            return []
        items: List[PlexItem] = []
        for element in root:
            item = self._item_from_element(element, source)
            if item:
                items.append(item)
            if len(items) >= self.recent_count:
                break
        return items

    def _playing_items(self) -> List[PlexItem]:
        if not self.show_playing:
            return []
        return self._items_from_root(self._plex_xml("/status/sessions"), "NOW PLAYING")

    def _recently_added_items(self) -> List[PlexItem]:
        if not self.show_recently_added:
            return []
        return self._items_from_root(
            self._plex_xml("/library/recentlyAdded"), "RECENTLY ADDED"
        )

    def _recently_played_items(self) -> List[PlexItem]:
        if not self.show_recently_played:
            return []
        return self._items_from_root(
            self._plex_xml("/status/sessions/history/all?sort=viewedAt:desc"),
            "RECENTLY PLAYED",
        )

    def _library_items(self) -> List[PlexItem]:
        if not self.show_library:
            return []
        sections = self._plex_xml("/library/sections")
        if sections is None:
            return []

        eligible = []
        for section in sections:
            section_type = section.get("type", "")
            if section_type == "movie" and self.filter_movies:
                eligible.append((section.get("key", ""), "movie"))
            elif section_type == "show" and self.filter_tv:
                eligible.append((section.get("key", ""), "show"))
            elif section_type == "artist" and self.filter_music:
                eligible.append((section.get("key", ""), "artist"))

        random.shuffle(eligible)
        for key, section_type in eligible:
            if not key:
                continue
            path = f"/library/sections/{key}/all"
            if section_type == "show":
                path += "?type=4"
            items = self._items_from_root(self._plex_xml(path), "FROM YOUR LIBRARY")
            if items:
                return items
        return []

    def _choose_item(self) -> Optional[PlexItem]:
        playing = self._playing_items()
        if playing:
            return random.choice(playing)

        getters = []
        if self.show_recently_added:
            getters.append(self._recently_added_items)
        if self.show_recently_played:
            getters.append(self._recently_played_items)
        if self.show_library:
            getters.append(self._library_items)
        random.shuffle(getters)

        for getter in getters:
            items = getter()
            if items:
                return random.choice(items)
        return None

    def _image_path_for_item(self, item: PlexItem) -> str:
        if self.artwork_mode == "poster":
            return item.thumb or item.art
        if self.artwork_mode == "background":
            return item.art or item.thumb
        if self.W >= self.H * 5 or self.show_summary:
            return item.thumb or item.art
        return item.art or item.thumb

    def _load_plex_image(self, item: PlexItem) -> Optional[Image.Image]:
        path = self._image_path_for_item(item)
        if not path:
            return None
        url = path if path.startswith(("http://", "https://")) else f"{self.plex_url}{path}"
        sep = "&" if "?" in url else "?"
        url += f"{sep}X-Plex-Token={urllib.parse.quote(self.plex_token)}"
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "LEDMatrix-Plex-Showtime/1.1.1"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return Image.open(io.BytesIO(response.read())).convert("RGB")
        except Exception as exc:
            self.logger.debug("Artwork request failed: %s", exc)
            return None

    def update(self):
        self.last_update = time.time()
        if not self.plex_url or not self.plex_token:
            self.current_item = None
            self.current_image = None
            self.last_error = "Configure plex_url and plex_token"
            return
        try:
            self.current_item = self._choose_item()
            self.current_image = (
                self._load_plex_image(self.current_item) if self.current_item else None
            )
            if self.current_item:
                self.last_error = ""
        except Exception as exc:
            self.current_item = None
            self.current_image = None
            self.last_error = str(exc)
            self.logger.error("Plex Showtime update failed: %s", exc, exc_info=True)

    def has_live_content(self) -> bool:
        if not self.live_priority or not self.show_playing:
            return False
        return bool(self._playing_items())

    @staticmethod
    def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
        box = draw.textbbox((0, 0), text, font=font)
        return max(0, box[2] - box[0])

    @classmethod
    def _fit_text(cls, draw: ImageDraw.ImageDraw, text: str, font, width: int) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        if cls._text_width(draw, text, font) <= width:
            return text
        suffix = "..."
        while text and cls._text_width(draw, text + suffix, font) > width:
            text = text[:-1]
        return text.rstrip() + suffix if text else ""

    @staticmethod
    def _cover(image: Image.Image, size) -> Image.Image:
        return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))

    @staticmethod
    def _contain(image: Image.Image, size) -> Image.Image:
        canvas = Image.new("RGB", size, "black")
        copy = image.copy()
        copy.thumbnail(size, Image.Resampling.LANCZOS)
        canvas.paste(copy, ((size[0] - copy.width) // 2, (size[1] - copy.height) // 2))
        return canvas

    def _draw_panel_dividers(self, draw: ImageDraw.ImageDraw):
        if not self.show_panel_dividers:
            return
        for x in range(self.panel_width, self.W, self.panel_width):
            draw.line((x, 0, x, self.H - 1), fill=(20, 20, 20))

    def _render_marquee(self, item: PlexItem) -> Image.Image:
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

        accent_x = art_w
        draw.rectangle(
            (accent_x, 0, min(self.W - 1, accent_x + self.accent_width - 1), self.H - 1),
            fill=(229, 160, 13),
        )

        text_x = art_w + self.accent_width + 6
        text_w = max(1, self.W - text_x - 5)
        y = 1

        if self.show_heading:
            heading = self._fit_text(draw, item.source, self._font_heading, text_w)
            draw.text((text_x, y), heading, font=self._font_heading, fill=(229, 160, 13))
            y += self.heading_font_size + 2

        title = self._fit_text(draw, item.display_title, self._font_title, text_w)
        draw.text((text_x, y), title, font=self._font_title, fill=(255, 255, 255))
        y += self.title_font_size + 2

        type_label = {
            "movie": "MOVIE", "show": "TV", "season": "TV", "episode": "TV",
            "artist": "MUSIC", "album": "MUSIC", "track": "MUSIC",
        }.get(item.media_type, item.media_type.upper())

        meta = [type_label] if type_label else []
        if item.media_type == "episode" and item.subtitle:
            meta.append(item.subtitle)
        elif self.show_year and item.year:
            meta.append(item.year)
        elif item.subtitle:
            meta.append(item.subtitle)

        if meta and y < self.H:
            line = self._fit_text(draw, "  |  ".join(meta), self._font_subtitle, text_w)
            draw.text((text_x, y), line, font=self._font_subtitle, fill=(190, 190, 190))

        self._draw_panel_dividers(draw)
        return canvas

    def _render_standard(self, item: PlexItem) -> Image.Image:
        canvas = Image.new("RGB", (self.W, self.H), "black")
        draw = ImageDraw.Draw(canvas)
        art_w = max(1, min(self.H, self.W // 3))
        if self.current_image:
            canvas.paste(self._cover(self.current_image, (art_w, self.H)), (0, 0))
        text_x = art_w + 4
        text_w = max(1, self.W - text_x - 2)
        y = 2
        if self.show_heading:
            draw.text((text_x, y), self._fit_text(draw, item.source, self._font_heading, text_w), font=self._font_heading, fill=(229, 160, 13))
            y += self.heading_font_size + 2
        draw.text((text_x, y), self._fit_text(draw, item.display_title, self._font_title, text_w), font=self._font_title, fill="white")
        y += self.title_font_size + 2
        if item.subtitle and y < self.H:
            draw.text((text_x, y), self._fit_text(draw, item.subtitle, self._font_subtitle, text_w), font=self._font_subtitle, fill=(190, 190, 190))
        return canvas

    def _render(self) -> Image.Image:
        if self.current_item is None:
            canvas = Image.new("RGB", (self.W, self.H), "black")
            draw = ImageDraw.Draw(canvas)
            msg = self.last_error or "No Plex media found"
            draw.text((3, max(0, self.H // 2 - 4)), self._fit_text(draw, msg, self._font_subtitle, self.W - 6), font=self._font_subtitle, fill="white")
            return canvas

        mode = self.display_layout
        if mode == "auto":
            mode = "marquee" if self.W >= self.H * 5 else "artwork_info"

        if mode == "marquee":
            return self._render_marquee(self.current_item)
        return self._render_standard(self.current_item)

    def display(self, force_clear=False):
        try:
            if force_clear:
                self.display_manager.clear()
            if self.current_item is None and not self.last_error:
                self.update()
            frame = self._render()
            self.display_manager.image.paste(frame, (0, 0))
            self.display_manager.update_display()
            return True
        except Exception as exc:
            self.logger.error("Plex Showtime display failed: %s", exc, exc_info=True)
            return False

    def validate_config(self):
        if not super().validate_config():
            return False
        if self.display_layout not in ("auto", "marquee", "artwork_info", "full_artwork"):
            self.logger.error("layout must be auto, marquee, artwork_info, or full_artwork")
            return False
        if self.artwork_mode not in ("auto", "poster", "background"):
            self.logger.error("artwork_mode must be auto, poster, or background")
            return False
        return True

    def get_info(self):
        info = super().get_info()
        info.update({
            "last_update": self.last_update,
            "last_error": self.last_error,
            "current_title": self.current_item.display_title if self.current_item else "",
            "current_source": self.current_item.source if self.current_item else "",
            "display_layout": self.display_layout,
        })
        return info
