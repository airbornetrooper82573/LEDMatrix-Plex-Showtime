"""Plex Showtime v1.2.0 for ChuckBuilds LEDMatrix.

Adds independent Recently Added pool limits for movies, TV, and music while
retaining the robust Plex parsing and ultra-wide renderer from v1.1.2.
"""

from typing import List

from manager_v2 import PlexItem, PlexShowtimePlugin as PlexShowtimePluginV112


class PlexShowtimePlugin(PlexShowtimePluginV112):
    """Plex Showtime with independent Recently Added category limits."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        self.recently_added_movies_limit = max(
            0, int(config.get("recently_added_movies_limit", 10))
        )
        self.recently_added_tv_limit = max(
            0, int(config.get("recently_added_tv_limit", 10))
        )
        self.recently_added_music_limit = max(
            0, int(config.get("recently_added_music_limit", 10))
        )

        self.logger.info(
            "Plex Showtime v1.2.0 Recently Added limits: movies=%d tv=%d music=%d",
            self.recently_added_movies_limit,
            self.recently_added_tv_limit,
            self.recently_added_music_limit,
        )

    @staticmethod
    def _recent_category(media_type: str) -> str:
        """Map a Plex media type into a Recently Added category."""
        media_type = (media_type or "").lower()
        if media_type == "movie":
            return "movie"
        if media_type in ("show", "season", "episode", "clip"):
            return "tv"
        if media_type in ("artist", "album", "track"):
            return "music"
        return "other"

    def _recently_added_items(self) -> List[PlexItem]:
        """Return the newest enabled items with independent category caps.

        Plex's /library/recentlyAdded endpoint is already ordered newest first,
        so we walk it in response order and keep only the first configured
        number from each media category. This creates the pool from which the
        plugin randomly selects a Recently Added item.
        """
        if not self.show_recently_added:
            return []

        root = self._request_xml("/library/recentlyAdded")
        if root is None:
            return []

        limits = {
            "movie": self.recently_added_movies_limit,
            "tv": self.recently_added_tv_limit,
            "music": self.recently_added_music_limit,
        }
        counts = {"movie": 0, "tv": 0, "music": 0}
        items: List[PlexItem] = []
        seen = set()
        raw_types = {}

        for element in root.iter():
            media_type = (element.get("type") or "").lower()
            if media_type:
                raw_types[media_type] = raw_types.get(media_type, 0) + 1

            item = self._to_item(element, "RECENTLY ADDED")
            if not item:
                continue

            category = self._recent_category(item.media_type)
            if category not in limits or limits[category] <= 0:
                continue
            if counts[category] >= limits[category]:
                continue

            key = (
                item.media_type,
                item.title,
                item.grandparent_title,
                item.parent_index,
                item.index,
            )
            if key in seen:
                continue

            seen.add(key)
            items.append(item)
            counts[category] += 1

            if all(counts[name] >= limit for name, limit in limits.items() if limit > 0):
                break

        self.logger.info(
            "Plex Showtime Recently Added: Plex types=%s selected=%s pool=%d",
            raw_types or "none",
            counts,
            len(items),
        )
        return items

    def get_info(self):
        info = super().get_info()
        info.update({
            "recently_added_movies_limit": self.recently_added_movies_limit,
            "recently_added_tv_limit": self.recently_added_tv_limit,
            "recently_added_music_limit": self.recently_added_music_limit,
        })
        return info
