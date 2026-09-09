"""Plex Showtime v1.5.3 for ChuckBuilds LEDMatrix.

Fixes Recently Added TV metadata by querying TV library sections directly for
real episode objects (type=4, sorted by addedAt desc) instead of trying to
resolve global Recently Added show/season containers. Episode objects carry the
series name in grandparentTitle and the episode name in title.
"""

from typing import List

from manager_v10 import PlexShowtimePlugin as PlexShowtimePluginV152


class PlexShowtimePlugin(PlexShowtimePluginV152):
    """Plex Showtime with direct TV episode retrieval for Recently Added."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self.logger.info("Plex Showtime v1.5.3 direct Recently Added TV episode queries enabled")

    def _tv_section_keys(self):
        root = self._request_xml("/library/sections")
        if root is None:
            return []

        keys = []
        for element in root.iter():
            section_type = (element.get("type") or "").lower()
            key = (element.get("key") or "").strip()
            if section_type == "show" and key:
                keys.append(key)

        self.logger.info("Plex Showtime TV library sections=%s", keys)
        return keys

    def _recent_tv_episode_items(self) -> List[object]:
        """Return newest real episode objects across all TV library sections."""
        requested = max(
            self.recently_added_tv_episodes_limit,
            self.recently_added_tv_shows_limit,
            self.recent_count,
            25,
        )
        per_section_size = min(200, max(25, requested * 4))

        candidates = []
        raw_count = 0

        for section_key in self._tv_section_keys():
            path = (
                f"/library/sections/{section_key}/all?type=4&sort=addedAt%3Adesc"
                f"&X-Plex-Container-Start=0&X-Plex-Container-Size={per_section_size}"
            )
            root = self._request_xml(path)
            if root is None:
                continue

            for element in root.iter():
                if (element.get("type") or "").lower() != "episode":
                    continue
                raw_count += 1
                item = self._to_item(element, "RECENTLY ADDED")
                if not item:
                    continue

                # Real episode objects should expose both of these. Keep a
                # diagnostic for any server/agent that omits them.
                if not item.grandparent_title or not item.title:
                    self.logger.warning(
                        "Plex Showtime TV episode missing display metadata: attrs=%s",
                        self._safe_tv_attrs(element),
                    )

                try:
                    added_at = int(element.get("addedAt") or 0)
                except (TypeError, ValueError):
                    added_at = 0
                candidates.append((added_at, item))

        candidates.sort(key=lambda pair: pair[0], reverse=True)

        items = []
        seen_items = set()
        show_counts = {}
        max_unique_shows = self.recently_added_tv_shows_limit
        max_episodes = self.recently_added_tv_episodes_limit

        for _, item in candidates:
            if max_episodes <= 0:
                break

            key = self._dedupe_key(item)
            if key in seen_items:
                continue

            show_key = self._show_identity(item) or (item.grandparent_title or "").strip().casefold()
            if not show_key:
                # Do not allow a season-only label back into the pool.
                continue

            if self.suppress_recent_episode_duplicates:
                used = show_counts.get(show_key, 0)
                if used >= self.recently_added_episodes_per_show:
                    continue

            if show_key not in show_counts and max_unique_shows > 0 and len(show_counts) >= max_unique_shows:
                continue

            seen_items.add(key)
            show_counts[show_key] = show_counts.get(show_key, 0) + 1
            items.append(item)

            if len(items) >= max_episodes:
                break

        self.logger.info(
            "Plex Showtime direct TV Recently Added: raw_episodes=%d pool=%d unique_shows=%d",
            raw_count,
            len(items),
            len(show_counts),
        )
        for item in items[:10]:
            self.logger.info(
                "Plex Showtime TV pool item -> show='%s' episode='%s' code=%s",
                item.grandparent_title or "<missing>",
                item.title or "<missing>",
                self._episode_code(item) or "<none>",
            )
        return items

    def _recently_added_items(self) -> List[object]:
        """Build Recently Added using direct episode queries for TV content."""
        if not self.show_recently_added:
            return []

        root = self._request_xml("/library/recentlyAdded")
        non_tv_items = []
        seen = set()
        counts = {"movie": 0, "music": 0}

        if root is not None:
            for element in root.iter():
                media_type = (element.get("type") or "").lower()
                if media_type == "movie":
                    if counts["movie"] >= self.recently_added_movies_limit:
                        continue
                    item = self._to_item(element, "RECENTLY ADDED")
                    if item:
                        key = self._dedupe_key(item)
                        if key not in seen:
                            seen.add(key)
                            non_tv_items.append(item)
                            counts["movie"] += 1
                elif media_type in ("artist", "album", "track"):
                    if counts["music"] >= self.recently_added_music_limit:
                        continue
                    item = self._to_item(element, "RECENTLY ADDED")
                    if item:
                        key = self._dedupe_key(item)
                        if key not in seen:
                            seen.add(key)
                            non_tv_items.append(item)
                            counts["music"] += 1

        tv_items = self._recent_tv_episode_items() if self.filter_tv else []
        combined = non_tv_items + tv_items

        self.logger.info(
            "Plex Showtime RECENTLY ADDED v1.5.3: movies=%d music=%d tv_episodes=%d total=%d",
            counts["movie"],
            counts["music"],
            len(tv_items),
            len(combined),
        )
        return combined

    def get_info(self):
        info = super().get_info()
        info.update({"tv_resolution_version": "1.5.3-direct-episode-query"})
        return info
