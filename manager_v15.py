"""Plex Showtime v1.7.0 for ChuckBuilds LEDMatrix.

Fixes the scrolling lifecycle for LEDMatrix's repeated display() dispatch model.
LEDMatrix calls display() many times while a mode is active; earlier releases
repainted offset 0 and restarted the worker on every dispatch, continually
canceling the visible marquee. This release starts one scroll session per item
and lets that worker own the framebuffer until the display slot expires.
"""

from __future__ import annotations

import threading
import time

from manager_v14 import PlexShowtimePlugin as PlexShowtimePluginV162


class PlexShowtimePlugin(PlexShowtimePluginV162):
    """Plex Showtime with persistent per-item scroll sessions."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self._session_lock = threading.Lock()
        self._active_scroll_item = None
        self._active_scroll_thread = None
        self._active_scroll_deadline = 0.0
        self._active_scroll_generation = 0

        self.logger.info(
            "Plex Showtime v1.7.0 persistent scroll sessions enabled: duration=%.1fs",
            float(self.config.get("display_duration", 20)),
        )

    def _stop_scroll_session(self):
        """Cancel any active worker and release LEDMatrix scrolling state."""
        with self._scroll_lock:
            self._scroll_generation += 1

        with self._session_lock:
            self._active_scroll_item = None
            self._active_scroll_thread = None
            self._active_scroll_deadline = 0.0
            self._active_scroll_generation = self._scroll_generation

        if hasattr(self.display_manager, "set_scrolling_state"):
            try:
                self.display_manager.set_scrolling_state(False)
            except Exception as exc:
                self.logger.debug("Could not release scroll state: %s", exc)

    def _scroll_session_worker(self, generation, item, duration):
        """Delegate frame animation to the existing movie/TV marquee worker."""
        try:
            self._scroll_worker(generation, item, duration)
        except Exception as exc:
            self.logger.error("Plex Showtime scroll session failed: %s", exc, exc_info=True)
        finally:
            # Keep the item/deadline marker until the slot expires. The core may
            # call display() again during the final fraction of a second after
            # the worker exits; clearing it here would start a second marquee.
            with self._session_lock:
                if self._active_scroll_generation == generation:
                    self._active_scroll_thread = None

    def _scroll_session_is_current(self, item, now):
        """True while this exact item owns the current LEDMatrix display slot."""
        with self._session_lock:
            return bool(
                self._active_scroll_item is item
                and now < self._active_scroll_deadline
            )

    def _start_scroll_session(self, item, duration):
        """Draw the initial frame once, then start one worker for this item."""
        # Cancel a worker from a previous item/session before assigning a new one.
        self._stop_scroll_session()

        frame = self._render_with_title_offset(item, 0)
        self.display_manager.image.paste(frame, (0, 0))
        self.display_manager.update_display()

        with self._scroll_lock:
            self._scroll_generation += 1
            generation = self._scroll_generation

        now = time.monotonic()
        deadline = now + duration
        thread = threading.Thread(
            target=self._scroll_session_worker,
            args=(generation, item, duration),
            daemon=True,
            name="plex-showtime-scroll-session",
        )

        with self._session_lock:
            self._active_scroll_item = item
            self._active_scroll_thread = thread
            self._active_scroll_deadline = deadline
            self._active_scroll_generation = generation

        self.logger.info(
            "Plex Showtime scroll SESSION START: type=%s title='%s' duration=%.1fs",
            getattr(item, "media_type", "unknown"),
            self._title_for_item(item),
            duration,
        )
        thread.start()

    def display(self, force_clear=False):
        """Render once, then preserve an active scroll across repeated dispatches."""
        try:
            if self.current_item is None:
                self.update()

            item = self.current_item
            if item is None:
                self._stop_scroll_session()
                if force_clear:
                    self.display_manager.clear()
                self.display_manager.image.paste(self._render(), (0, 0))
                self.display_manager.update_display()
                return True

            now = time.monotonic()
            needs_scroll = self._title_needs_scroll(item)

            if needs_scroll:
                # This is the critical v1.7 behavior: LEDMatrix calls display()
                # repeatedly during one mode slot. Once the worker owns this item,
                # DO NOT redraw the zero-offset frame or create another worker.
                if self._scroll_session_is_current(item, now):
                    return True

                duration = max(0.5, float(self.config.get("display_duration", 20)))
                self._start_scroll_session(item, duration)
                return True

            # Static content: cancel a stale marquee and render normally.
            self._stop_scroll_session()
            if force_clear:
                self.display_manager.clear()
            frame = self._render_with_title_offset(item, 0)
            self.display_manager.image.paste(frame, (0, 0))
            self.display_manager.update_display()
            return True

        except Exception as exc:
            self.logger.error("Display failed: %s", exc, exc_info=True)
            return False

    def cleanup(self):
        self._stop_scroll_session()
        try:
            return super().cleanup()
        except AttributeError:
            return None

    def get_info(self):
        info = super().get_info()
        with self._session_lock:
            active = bool(
                self._active_scroll_item is not None
                and time.monotonic() < self._active_scroll_deadline
            )
        info.update({
            "scroll_lifecycle_version": "1.7.0-persistent-session",
            "scroll_session_active": active,
        })
        return info
