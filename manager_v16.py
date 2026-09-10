"""Plex Showtime v1.8.0 for ChuckBuilds LEDMatrix.

Adds an optional Now Playing user allowlist. When configured, active Plex
sessions are eligible only when their nested <User> metadata matches one of
the configured display names/usernames or Plex user IDs. Recently Added,
Recently Played, and Library sources are unaffected.
"""

from __future__ import annotations

from manager_v15 import PlexShowtimePlugin as PlexShowtimePluginV170


class PlexShowtimePlugin(PlexShowtimePluginV170):
    """Plex Showtime with per-user filtering for active playback sessions."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        raw_users = config.get("now_playing_users", []) or []
        self.now_playing_users = [
            str(value).strip() for value in raw_users if str(value).strip()
        ]
        self._now_playing_user_keys = {
            value.casefold() for value in self.now_playing_users
        }

        self.logger.info(
            "Plex Showtime v1.8.0 Now Playing user filter: %s",
            self.now_playing_users if self.now_playing_users else "ALL USERS",
        )

    @staticmethod
    def _session_user_fields(element):
        """Return useful identity fields from a Plex session's nested User node."""
        user = element.find("User")
        if user is None:
            # Be tolerant of wrappers/agent differences.
            user = element.find(".//User")
        if user is None:
            return []

        values = []
        for attr in ("title", "username", "name", "id"):
            value = (user.get(attr) or "").strip()
            if value:
                values.append(value)
        return values

    def _session_user_allowed(self, element):
        """Return (allowed, display_user, all_identity_fields)."""
        identities = self._session_user_fields(element)
        display_user = identities[0] if identities else "<unknown>"

        if not self._now_playing_user_keys:
            return True, display_user, identities

        normalized = {value.casefold() for value in identities}
        allowed = bool(normalized & self._now_playing_user_keys)
        return allowed, display_user, identities

    def _playing_items(self):
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

        # Each active session's media node (Video/Track/etc.) owns its nested
        # User node. Filtering the media node before _to_item keeps the user
        # association intact; flattening root.iter() first would lose it.
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
            "Plex Showtime Now Playing user filter result: accepted=%d rejected=%d "
            "missing_user=%d allowlist=%s",
            accepted,
            rejected,
            missing_user,
            self.now_playing_users if self.now_playing_users else "ALL USERS",
        )
        return items

    def get_info(self):
        info = super().get_info()
        info.update({
            "now_playing_users": list(self.now_playing_users),
            "now_playing_user_filter_enabled": bool(self.now_playing_users),
        })
        return info
