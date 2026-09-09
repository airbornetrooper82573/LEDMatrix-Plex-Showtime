"""Plex Showtime v1.4.2 for ChuckBuilds LEDMatrix.

Resolves Recently Added TV show/season containers to their newest episode so
marquee output can reliably show both the series name and episode title.
"""

from typing import List, Optional

from manager_v6 import PlexShowtimePlugin as PlexShowtimePluginV141


class PlexShowtimePlugin(PlexShowtimePluginV141):
    """Plex Showtime with reliable show + episode names for Recently Added TV."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self.resolve_recent_tv_to_episode = bool(
            config.get("resolve_recent_tv_to_episode", True)
        )
        self.logger.info(
            "Plex Showtime v1.4.2 TV container resolution enabled=%s",
            self.resolve_recent_tv_to_episode,
        )

    def _latest_episode_for_element(self, element) -> Optional[object]:
        """Resolve a Plex show/season XML element to its newest episode item."""
        media_type = (element.get("type") or "").lower()
        key = (element.get("key") or "").strip()
        if media_type not in ("show", "season") or not key:
            return None

        # Plex Show.episodes() uses <show key>/allLeaves while Season.episodes()
        # uses <season key>/children. Ask Plex for newest-added first and only
        # a small page because we only need a representative episode.
        if media_type == "show":
            path = f"{key}/allLeaves?sort=addedAt%3Adesc&X-Plex-Container-Start=0&X-Plex-Container-Size=5"
        else:
            path = f"{key}/children?sort=addedAt%3Adesc&X-Plex-Container-Start=0&X-Plex-Container-Size=5"

        root = self._request_xml(path)
        if root is None:
            return None

        for child in root.iter():
            if (child.get("type") or "").lower() not in ("episode", "clip"):
                continue
            item = self._to_item(child, "RECENTLY ADDED")
            if item:
                return item
        return None

    def _recently_added_items(self) -> List[object]:
        """Build Recently Added pool, resolving TV containers to episodes."""
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
        items = []
        seen = set()
        show_counts = {}
        raw_types = {}
        suppressed = 0
        resolved_tv = 0
        failed_resolutions = 0

        for element in root.iter():
            media_type = (element.get("type") or "").lower()
            if media_type:
                raw_types[media_type] = raw_types.get(media_type, 0) + 1

            original_category = self._added_category(media_type)
            if original_category not in limits:
                continue
            original_limit = limits[original_category]
            if original_limit <= 0 or counts[original_category] >= original_limit:
                continue

            item = self._to_item(element, "RECENTLY ADDED")
            if not item:
                continue

            # Recently Added often returns a show or season container rather
            # than an episode. Resolve that container so the display has both
            # grandparentTitle (series) and title (episode).
            if (
                self.resolve_recent_tv_to_episode
                and media_type in ("show", "season")
            ):
                resolved = self._latest_episode_for_element(element)
                if resolved:
                    item = resolved
                    resolved_tv += 1
                else:
                    failed_resolutions += 1

            key = self._dedupe_key(item)
            if key in seen:
                continue

            # Preserve v1.4 duplicate suppression even when a show/season was
            # resolved into an episode.
            if (
                self.suppress_recent_episode_duplicates
                and item.media_type in ("episode", "clip")
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
            counts[original_category] += 1

            enabled_limits = {k: v for k, v in limits.items() if v > 0}
            if enabled_limits and all(counts[k] >= v for k, v in enabled_limits.items()):
                break

        self.logger.info(
            "Plex Showtime RECENTLY ADDED v1.4.2: Plex types=%s selected=%s "
            "pool=%d resolved_tv=%d failed_resolutions=%d suppressed=%d",
            raw_types or "none",
            counts,
            len(items),
            resolved_tv,
            failed_resolutions,
            suppressed,
        )
        return items

    def get_info(self):
        info = super().get_info()
        info.update({"resolve_recent_tv_to_episode": self.resolve_recent_tv_to_episode})
        return info
