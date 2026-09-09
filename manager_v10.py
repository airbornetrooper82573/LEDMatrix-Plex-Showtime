"""Plex Showtime v1.5.2 for ChuckBuilds LEDMatrix.

Makes Recently Added TV resolution deterministic by using Plex ratingKey-based
metadata endpoints with fallbacks, and never allows an unresolved show/season
container (for example "Season 2") into the rotation when episode resolution
is enabled.
"""

from typing import List, Optional

from manager_v9 import PlexShowtimePlugin as PlexShowtimePluginV151


class PlexShowtimePlugin(PlexShowtimePluginV151):
    """Plex Showtime with robust Recently Added TV episode resolution."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self.logger.info("Plex Showtime v1.5.2 strict TV episode resolution enabled")

    @staticmethod
    def _canonical_metadata_base(element) -> str:
        """Prefer ratingKey, which is the canonical Plex metadata identifier."""
        rating_key = (element.get("ratingKey") or "").strip()
        if rating_key:
            return f"/library/metadata/{rating_key}"

        key = (element.get("key") or "").strip().rstrip("/")
        for suffix in ("/children", "/allLeaves"):
            if key.endswith(suffix):
                key = key[: -len(suffix)]
                break
        return key.rstrip("/")

    @staticmethod
    def _safe_tv_attrs(element):
        """Return useful non-secret Plex metadata fields for diagnostics."""
        names = (
            "type", "ratingKey", "key", "title", "parentTitle",
            "grandparentTitle", "index", "parentIndex", "addedAt",
        )
        return {name: element.get(name) for name in names if element.get(name) is not None}

    def _episode_candidates_from_path(self, path: str, show_name: str):
        root = self._request_xml(path)
        if root is None:
            return []

        candidates = []
        for child in root.iter():
            if (child.get("type") or "").lower() not in ("episode", "clip"):
                continue
            item = self._to_item(child, "RECENTLY ADDED")
            if not item:
                continue

            # Always prefer the known container show name if Plex omitted the
            # grandparent field or substituted a season label.
            current_show = (item.grandparent_title or "").strip()
            if show_name and (
                not current_show
                or current_show.lower().startswith("season ")
            ):
                item.grandparent_title = show_name

            try:
                added_at = int(child.get("addedAt") or 0)
            except (TypeError, ValueError):
                added_at = 0
            candidates.append((added_at, item))

        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return candidates

    def _latest_episode_for_element(self, element) -> Optional[object]:
        media_type = (element.get("type") or "").lower()
        if media_type not in ("show", "season"):
            return None

        base = self._canonical_metadata_base(element)
        show_name = self._container_show_name(element)
        if not base:
            self.logger.warning(
                "Plex Showtime TV container has no usable metadata key: %s",
                self._safe_tv_attrs(element),
            )
            return None

        # Plex installations/versions can expose leaves slightly differently.
        # Try the canonical endpoints in the most useful order. allLeaves is
        # especially helpful because it guarantees episode objects for a show.
        if media_type == "show":
            endpoints = (
                f"{base}/allLeaves?sort=addedAt%3Adesc&X-Plex-Container-Start=0&X-Plex-Container-Size=25",
                f"{base}/children?sort=addedAt%3Adesc&X-Plex-Container-Start=0&X-Plex-Container-Size=25",
            )
        else:
            endpoints = (
                f"{base}/children?sort=addedAt%3Adesc&X-Plex-Container-Start=0&X-Plex-Container-Size=25",
                f"{base}/allLeaves?sort=addedAt%3Adesc&X-Plex-Container-Start=0&X-Plex-Container-Size=25",
            )

        self.logger.info(
            "Plex Showtime resolving TV container attrs=%s base=%s",
            self._safe_tv_attrs(element),
            base,
        )

        for path in endpoints:
            candidates = self._episode_candidates_from_path(path, show_name)
            if not candidates:
                self.logger.info("Plex Showtime TV resolver found no episodes at %s", path)
                continue

            item = candidates[0][1]
            self.logger.info(
                "Plex Showtime resolved TV -> show='%s' episode='%s' code=%s via=%s",
                item.grandparent_title or show_name or "<unknown>",
                item.title or "<unknown>",
                self._episode_code(item) or "<none>",
                path.split("?", 1)[0],
            )
            return item

        self.logger.warning(
            "Plex Showtime failed to resolve Recently Added TV container: %s",
            self._safe_tv_attrs(element),
        )
        return None

    def _recently_added_items(self) -> List[object]:
        """Build Recently Added pool and never display unresolved TV containers."""
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
        skipped_unresolved_tv = 0

        for element in root.iter():
            media_type = (element.get("type") or "").lower()
            if media_type:
                raw_types[media_type] = raw_types.get(media_type, 0) + 1

            original_category = self._added_category(media_type)
            if original_category not in limits:
                continue
            limit = limits[original_category]
            if limit <= 0 or counts[original_category] >= limit:
                continue

            item = self._to_item(element, "RECENTLY ADDED")
            if not item:
                continue

            if self.resolve_recent_tv_to_episode and media_type in ("show", "season"):
                resolved = self._latest_episode_for_element(element)
                if not resolved:
                    # Critical v1.5.2 behavior: do not fall back to "Season N".
                    skipped_unresolved_tv += 1
                    continue
                item = resolved
                resolved_tv += 1

            key = self._dedupe_key(item)
            if key in seen:
                continue

            if self.suppress_recent_episode_duplicates and item.media_type in ("episode", "clip"):
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

        self.logger.info(
            "Plex Showtime RECENTLY ADDED v1.5.2: Plex types=%s selected=%s pool=%d "
            "resolved_tv=%d skipped_unresolved_tv=%d suppressed=%d",
            raw_types or "none",
            counts,
            len(items),
            resolved_tv,
            skipped_unresolved_tv,
            suppressed,
        )
        return items

    def get_info(self):
        info = super().get_info()
        info.update({"tv_resolution_version": "1.5.2"})
        return info
