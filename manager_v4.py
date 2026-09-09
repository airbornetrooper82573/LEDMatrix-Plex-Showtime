"""Plex Showtime v1.3.0 for ChuckBuilds LEDMatrix.

Adds granular Recently Added TV show/episode limits plus independent
Recently Played limits for movies, TV, and music. Backward compatible with
v1.2.0 configuration keys.
"""

from typing import Dict, List

from manager_v3 import PlexItem, PlexShowtimePlugin as PlexShowtimePluginV120


class PlexShowtimePlugin(PlexShowtimePluginV120):
    """Plex Showtime with granular source/category rotation limits."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Backward compatibility: the v1.2.0 `recently_added_tv_limit` becomes
        # the fallback for both show/season and episode pools.
        legacy_tv_limit = max(0, int(config.get("recently_added_tv_limit", 10)))
        self.recently_added_tv_shows_limit = max(
            0, int(config.get("recently_added_tv_shows_limit", legacy_tv_limit))
        )
        self.recently_added_tv_episodes_limit = max(
            0, int(config.get("recently_added_tv_episodes_limit", legacy_tv_limit))
        )

        self.recently_played_movies_limit = max(
            0, int(config.get("recently_played_movies_limit", 10))
        )
        self.recently_played_tv_limit = max(
            0, int(config.get("recently_played_tv_limit", 10))
        )
        self.recently_played_music_limit = max(
            0, int(config.get("recently_played_music_limit", 10))
        )

        self.logger.info(
            "Plex Showtime v1.3.0 limits: added(movie=%d shows=%d episodes=%d music=%d) "
            "played(movie=%d tv=%d music=%d)",
            self.recently_added_movies_limit,
            self.recently_added_tv_shows_limit,
            self.recently_added_tv_episodes_limit,
            self.recently_added_music_limit,
            self.recently_played_movies_limit,
            self.recently_played_tv_limit,
            self.recently_played_music_limit,
        )

    @staticmethod
    def _added_category(media_type: str) -> str:
        media_type = (media_type or "").lower()
        if media_type == "movie":
            return "movie"
        if media_type in ("show", "season"):
            return "tv_show"
        if media_type in ("episode", "clip"):
            return "tv_episode"
        if media_type in ("artist", "album", "track"):
            return "music"
        return "other"

    @staticmethod
    def _played_category(media_type: str) -> str:
        media_type = (media_type or "").lower()
        if media_type == "movie":
            return "movie"
        if media_type in ("show", "season", "episode", "clip"):
            return "tv"
        if media_type in ("artist", "album", "track"):
            return "music"
        return "other"

    @staticmethod
    def _dedupe_key(item: PlexItem):
        return (
            item.media_type,
            item.title,
            item.grandparent_title,
            item.parent_index,
            item.index,
        )

    def _collect_limited_items(
        self,
        root,
        source: str,
        limits: Dict[str, int],
        category_fn,
    ) -> List[PlexItem]:
        """Collect media in Plex response order with independent category caps."""
        if root is None:
            return []

        counts = {name: 0 for name in limits}
        items: List[PlexItem] = []
        seen = set()
        raw_types = {}

        for element in root.iter():
            media_type = (element.get("type") or "").lower()
            if media_type:
                raw_types[media_type] = raw_types.get(media_type, 0) + 1

            item = self._to_item(element, source)
            if not item:
                continue

            category = category_fn(item.media_type)
            if category not in limits:
                continue
            limit = limits[category]
            if limit <= 0 or counts[category] >= limit:
                continue

            key = self._dedupe_key(item)
            if key in seen:
                continue

            seen.add(key)
            items.append(item)
            counts[category] += 1

            enabled_limits = {k: v for k, v in limits.items() if v > 0}
            if enabled_limits and all(counts[k] >= v for k, v in enabled_limits.items()):
                break

        self.logger.info(
            "Plex Showtime %s: Plex types=%s selected=%s pool=%d",
            source,
            raw_types or "none",
            counts,
            len(items),
        )
        return items

    def _recently_added_items(self) -> List[PlexItem]:
        if not self.show_recently_added:
            return []

        limits = {
            "movie": self.recently_added_movies_limit,
            "tv_show": self.recently_added_tv_shows_limit,
            "tv_episode": self.recently_added_tv_episodes_limit,
            "music": self.recently_added_music_limit,
        }
        return self._collect_limited_items(
            self._request_xml("/library/recentlyAdded"),
            "RECENTLY ADDED",
            limits,
            self._added_category,
        )

    def _recently_played_items(self) -> List[PlexItem]:
        if not self.show_recently_played:
            return []

        limits = {
            "movie": self.recently_played_movies_limit,
            "tv": self.recently_played_tv_limit,
            "music": self.recently_played_music_limit,
        }
        return self._collect_limited_items(
            self._request_xml("/status/sessions/history/all?sort=viewedAt%3Adesc"),
            "RECENTLY PLAYED",
            limits,
            self._played_category,
        )

    def get_info(self):
        info = super().get_info()
        info.update({
            "recently_added_tv_shows_limit": self.recently_added_tv_shows_limit,
            "recently_added_tv_episodes_limit": self.recently_added_tv_episodes_limit,
            "recently_played_movies_limit": self.recently_played_movies_limit,
            "recently_played_tv_limit": self.recently_played_tv_limit,
            "recently_played_music_limit": self.recently_played_music_limit,
        })
        return info
