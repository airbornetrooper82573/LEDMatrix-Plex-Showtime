"""Plex Showtime v1.4.0 for ChuckBuilds LEDMatrix.

Adds configurable show-level duplicate suppression for Recently Added TV
episodes so bulk season imports do not dominate the rotation pool.
"""

from typing import List

from manager_v4 import PlexItem, PlexShowtimePlugin as PlexShowtimePluginV130


class PlexShowtimePlugin(PlexShowtimePluginV130):
    """Plex Showtime with duplicate suppression for recently added episodes."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        self.suppress_recent_episode_duplicates = bool(
            config.get("suppress_recent_episode_duplicates", True)
        )
        self.recently_added_episodes_per_show = max(
            1, int(config.get("recently_added_episodes_per_show", 1))
        )

        self.logger.info(
            "Plex Showtime v1.4.0 episode suppression: enabled=%s per_show=%d",
            self.suppress_recent_episode_duplicates,
            self.recently_added_episodes_per_show,
        )

    @staticmethod
    def _show_identity(item: PlexItem) -> str:
        """Return a stable show-level identity for TV episode deduplication."""
        if item.media_type not in ("episode", "clip"):
            return ""
        show = (item.grandparent_title or item.parent_title or "").strip()
        return show.casefold()

    def _recently_added_items(self) -> List[PlexItem]:
        """Return Recently Added items with category caps and show suppression."""
        if not self.show_recently_added:
            return []

        root = self._request_xml("/library/recentlyAdded")
        if root is None:
            return []

        limits = {
            "movie": self.recently_added_movies_limit,
            "tv_show": self.recently_added_tv_shows_limit,
            "tv_episode": self.recently_added_tv_episodes_limit,
            "music": self.recently_added_music_limit,
        }
        counts = {name: 0 for name in limits}
        items: List[PlexItem] = []
        seen = set()
        show_counts = {}
        raw_types = {}
        suppressed = 0

        for element in root.iter():
            media_type = (element.get("type") or "").lower()
            if media_type:
                raw_types[media_type] = raw_types.get(media_type, 0) + 1

            item = self._to_item(element, "RECENTLY ADDED")
            if not item:
                continue

            category = self._added_category(item.media_type)
            if category not in limits:
                continue
            limit = limits[category]
            if limit <= 0 or counts[category] >= limit:
                continue

            key = self._dedupe_key(item)
            if key in seen:
                continue

            if (
                self.suppress_recent_episode_duplicates
                and category == "tv_episode"
            ):
                show_key = self._show_identity(item)
                if show_key:
                    used = show_counts.get(show_key, 0)
                    if used >= self.recently_added_episodes_per_show:
                        suppressed += 1
                        continue
                    show_counts[show_key] = used + 1

            seen.add(key)
            items.append(item)
            counts[category] += 1

            enabled_limits = {k: v for k, v in limits.items() if v > 0}
            if enabled_limits and all(counts[k] >= v for k, v in enabled_limits.items()):
                break

        self.logger.info(
            "Plex Showtime RECENTLY ADDED: Plex types=%s selected=%s pool=%d "
            "episode_shows=%d suppressed=%d",
            raw_types or "none",
            counts,
            len(items),
            len(show_counts),
            suppressed,
        )
        return items

    def get_info(self):
        info = super().get_info()
        info.update({
            "suppress_recent_episode_duplicates": self.suppress_recent_episode_duplicates,
            "recently_added_episodes_per_show": self.recently_added_episodes_per_show,
        })
        return info
