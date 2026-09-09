"""Plex Showtime v1.5.1 for ChuckBuilds LEDMatrix.

Fixes Recently Added TV resolution when Plex returns show/season keys that
already end in /children. Resolved episodes explicitly retain the series name
so the marquee can reliably show both show and episode titles.
"""

from typing import Optional

from manager_v8 import PlexShowtimePlugin as PlexShowtimePluginV150


class PlexShowtimePlugin(PlexShowtimePluginV150):
    """Plex Showtime with corrected TV container-to-episode resolution."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self.logger.info("Plex Showtime v1.5.1 corrected TV metadata resolution enabled")

    @staticmethod
    def _metadata_base_key(key: str) -> str:
        """Normalize Plex metadata keys before appending child endpoints.

        Plex commonly returns keys such as:
            /library/metadata/123/children
        while the endpoints we need are based on:
            /library/metadata/123
        """
        key = (key or "").strip().rstrip("/")
        for suffix in ("/children", "/allLeaves"):
            if key.endswith(suffix):
                key = key[: -len(suffix)]
                break
        return key.rstrip("/")

    @staticmethod
    def _container_show_name(element) -> str:
        media_type = (element.get("type") or "").lower()
        title = (element.get("title") or "").strip()
        parent = (element.get("parentTitle") or "").strip()
        grandparent = (element.get("grandparentTitle") or "").strip()

        if media_type == "show":
            return title or parent or grandparent
        if media_type == "season":
            return parent or grandparent or title
        return grandparent or parent or title

    def _latest_episode_for_element(self, element) -> Optional[object]:
        """Resolve a Recently Added show/season container to a real episode."""
        media_type = (element.get("type") or "").lower()
        raw_key = (element.get("key") or "").strip()
        base_key = self._metadata_base_key(raw_key)

        if media_type not in ("show", "season") or not base_key:
            return None

        show_name = self._container_show_name(element)

        if media_type == "show":
            path = (
                f"{base_key}/allLeaves?sort=addedAt%3Adesc"
                "&X-Plex-Container-Start=0&X-Plex-Container-Size=10"
            )
        else:
            path = (
                f"{base_key}/children?sort=addedAt%3Adesc"
                "&X-Plex-Container-Start=0&X-Plex-Container-Size=10"
            )

        self.logger.debug(
            "Resolving Recently Added TV container type=%s key=%s normalized=%s path=%s",
            media_type,
            raw_key,
            base_key,
            path,
        )

        root = self._request_xml(path)
        if root is None:
            return None

        candidates = []
        for child in root.iter():
            if (child.get("type") or "").lower() not in ("episode", "clip"):
                continue
            item = self._to_item(child, "RECENTLY ADDED")
            if not item:
                continue

            # Some Plex responses omit grandparentTitle on children reached
            # through a show/season endpoint. Preserve it from the container.
            if not item.grandparent_title and show_name:
                item.grandparent_title = show_name

            # A season endpoint may return parentTitle as the season label.
            # The show name belongs in grandparent_title for our renderer.
            if show_name and (
                not item.grandparent_title
                or item.grandparent_title.lower().startswith("season ")
            ):
                item.grandparent_title = show_name

            candidates.append((child, item))

        if not candidates:
            self.logger.warning(
                "Plex Showtime could not find an episode beneath TV %s '%s' (%s)",
                media_type,
                show_name or "<unknown>",
                base_key,
            )
            return None

        # Plex should honor addedAt:desc, but sort locally too when timestamps
        # are present so we consistently select the newest episode.
        def added_at(pair):
            raw = pair[0].get("addedAt") or "0"
            try:
                return int(raw)
            except (TypeError, ValueError):
                return 0

        candidates.sort(key=added_at, reverse=True)
        item = candidates[0][1]

        self.logger.info(
            "Plex Showtime resolved Recently Added TV: show='%s' episode='%s' code=%s",
            item.grandparent_title or show_name or "<unknown>",
            item.title or "<unknown>",
            self._episode_code(item) or "<none>",
        )
        return item

    def get_info(self):
        info = super().get_info()
        info.update({"tv_resolution_version": "1.5.1"})
        return info
