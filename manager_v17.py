"""Plex Showtime v1.9.0 for ChuckBuilds LEDMatrix.

Adds three quality-of-life upgrades on top of the proven v1.8.0 behavior:
- balanced round-robin selection across non-live sources and Recently Added media categories
- better TV episode artwork by preferring series-level poster/backdrop metadata
- optional Plex user label on Now Playing items
"""

from __future__ import annotations

import random

from manager_v16 import PlexShowtimePlugin as PlexShowtimePluginV180


class PlexShowtimePlugin(PlexShowtimePluginV180):
    """Plex Showtime with fairer rotation and richer Plex presentation."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        self.balanced_rotation = bool(config.get("balanced_rotation", True))
        self.prefer_series_artwork_for_tv = bool(
            config.get("prefer_series_artwork_for_tv", True)
        )
        self.show_now_playing_user = bool(config.get("show_now_playing_user", False))
        self.now_playing_user_prefix = str(
            config.get("now_playing_user_prefix", "USER")
        ).strip() or "USER"

        self._source_rotation_index = 0
        self._recent_category_index = 0

        self.logger.info(
            "Plex Showtime v1.9.0: balanced_rotation=%s series_tv_art=%s "
            "show_now_playing_user=%s",
            self.balanced_rotation,
            self.prefer_series_artwork_for_tv,
            self.show_now_playing_user,
        )

    def _to_item(self, element, source):
        """Build the normal PlexItem and preserve richer Plex metadata on it."""
        item = super()._to_item(element, source)
        if not item:
            return None

        # PlexItem predates these fields, so attach them dynamically to remain
        # backward compatible with the existing manager chain.
        item.parent_thumb = (element.get("parentThumb") or "").strip()
        item.grandparent_thumb = (element.get("grandparentThumb") or "").strip()
        item.parent_art = (element.get("parentArt") or "").strip()
        item.grandparent_art = (element.get("grandparentArt") or "").strip()
        return item

    def _playing_items(self):
        """Preserve the v1.8 allowlist while attaching the accepted Plex user."""
        if not self.show_playing:
            return []

        root = self._request_xml("/status/sessions")
        if root is None:
            return []

        items = []
        seen = set()
        accepted = 0
        rejected = 0
        missing_user = 0

        for element in list(root):
            media_type = (element.get("type") or "").lower()
            if not media_type:
                continue

            allowed, display_user, identities = self._session_user_allowed(element)
            if not identities:
                missing_user += 1

            if not allowed:
                rejected += 1
                self.logger.info(
                    "Plex Showtime Now Playing rejected user='%s' identities=%s title='%s'",
                    display_user,
                    identities,
                    element.get("title") or element.get("grandparentTitle") or "<unknown>",
                )
                continue

            item = self._to_item(element, "NOW PLAYING")
            if not item:
                continue

            key = self._dedupe_key(item)
            if key in seen:
                continue
            seen.add(key)

            item.plex_user = "" if display_user == "<unknown>" else display_user
            items.append(item)
            accepted += 1

            self.logger.info(
                "Plex Showtime Now Playing accepted user='%s' title='%s'",
                display_user,
                item.display_title,
            )

            if len(items) >= self.recent_count:
                break

        self.logger.info(
            "Plex Showtime Now Playing result: accepted=%d rejected=%d "
            "missing_user=%d allowlist=%s",
            accepted,
            rejected,
            missing_user,
            self.now_playing_users if self.now_playing_users else "ALL USERS",
        )
        return items

    def _image_path(self, item):
        """Prefer series-level imagery for TV episodes when Plex provides it."""
        if not self.prefer_series_artwork_for_tv or item.media_type not in ("episode", "clip"):
            return super()._image_path(item)

        parent_thumb = getattr(item, "parent_thumb", "")
        grandparent_thumb = getattr(item, "grandparent_thumb", "")
        parent_art = getattr(item, "parent_art", "")
        grandparent_art = getattr(item, "grandparent_art", "")

        if self.artwork_mode == "background":
            return (
                grandparent_art
                or parent_art
                or item.art
                or grandparent_thumb
                or parent_thumb
                or item.thumb
            )
        if self.artwork_mode == "poster":
            return (
                grandparent_thumb
                or parent_thumb
                or item.thumb
                or grandparent_art
                or parent_art
                or item.art
            )
        return (
            grandparent_thumb
            or parent_thumb
            or item.thumb
            or grandparent_art
            or parent_art
            or item.art
        )

    @staticmethod
    def _rotation_category(item):
        media_type = (getattr(item, "media_type", "") or "").lower()
        if media_type == "movie":
            return "movie"
        if media_type in ("show", "season", "episode", "clip"):
            return "tv"
        if media_type in ("artist", "album", "track"):
            return "music"
        return "other"

    def _choose_balanced_recent_item(self, items):
        """Round-robin across movie/TV/music pools instead of weighting by pool size."""
        if not items:
            return None
        if not self.balanced_rotation:
            return random.choice(items)

        grouped = {"movie": [], "tv": [], "music": [], "other": []}
        for item in items:
            grouped[self._rotation_category(item)].append(item)

        order = ["movie", "tv", "music", "other"]
        for offset in range(len(order)):
            idx = (self._recent_category_index + offset) % len(order)
            category = order[idx]
            pool = grouped[category]
            if not pool:
                continue
            self._recent_category_index = (idx + 1) % len(order)
            choice = random.choice(pool)
            self.logger.info(
                "Plex Showtime balanced Recently Added selection: category=%s title='%s'",
                category,
                choice.display_title,
            )
            return choice
        return random.choice(items)

    def _choose_item(self):
        """Keep Now Playing priority, then fairly rotate the enabled non-live sources."""
        playing = self._playing_items()
        if playing:
            self.logger.info("Plex Showtime selected active playback")
            return random.choice(playing)

        sources = []
        if self.show_recently_added:
            sources.append(("recently_added", self._recently_added_items))
        if self.show_recently_played:
            sources.append(("recently_played", self._recently_played_items))
        if self.show_library:
            sources.append(("library", self._library_items))

        if not sources:
            if not self.last_error:
                self.last_error = "Plex connected, but no enabled media sources are available"
            return None

        if not self.balanced_rotation:
            random.shuffle(sources)
            for name, getter in sources:
                items = getter()
                if items:
                    if name == "recently_added":
                        return self._choose_balanced_recent_item(items)
                    return random.choice(items)
        else:
            for offset in range(len(sources)):
                idx = (self._source_rotation_index + offset) % len(sources)
                name, getter = sources[idx]
                items = getter()
                if not items:
                    continue
                self._source_rotation_index = (idx + 1) % len(sources)
                if name == "recently_added":
                    choice = self._choose_balanced_recent_item(items)
                else:
                    choice = random.choice(items)
                self.logger.info(
                    "Plex Showtime balanced source selection: source=%s title='%s'",
                    name,
                    choice.display_title,
                )
                return choice

        if not self.last_error:
            self.last_error = "Plex connected, but no enabled media matched filters"
        return None

    def _generic_meta_line(self, item):
        line = super()._generic_meta_line(item)
        if (
            self.show_now_playing_user
            and item.source == "NOW PLAYING"
            and getattr(item, "plex_user", "")
        ):
            user_part = f"{self.now_playing_user_prefix}: {item.plex_user}"
            return f"{line}  |  {user_part}" if line else user_part
        return line

    def get_info(self):
        info = super().get_info()
        info.update({
            "balanced_rotation": self.balanced_rotation,
            "prefer_series_artwork_for_tv": self.prefer_series_artwork_for_tv,
            "show_now_playing_user": self.show_now_playing_user,
            "presentation_version": "1.9.0",
        })
        return info
