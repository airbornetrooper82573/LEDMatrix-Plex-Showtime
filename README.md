# LEDMatrix Plex Showtime

Native Plex media display plugin for [ChuckBuilds/LEDMatrix](https://github.com/ChuckBuilds/LEDMatrix), inspired by Tronbyt's Plex Showtime app.

## Features

- Full horizontal scrolling for long movie, series, and TV episode text instead of ellipses (active v1.9.1 renderer)
- Uses the hardware-tested scrolling approach that does not activate LEDMatrix's special scrolling-state mode

- Now Playing from `/status/sessions`
- Recently Added from `/library/recentlyAdded`
- Recently Played from Plex history
- Random movie, TV episode, or music item from Plex libraries
- Uses Plex-hosted artwork directly; no Home Assistant, TMDB, or Fanart.tv required
- Active playback is preferred when available
- Movie, TV, and music filters
- Auto, artwork+info, and full-artwork layouts
- Optional heading, year/episode info, and summary
- Adapts to the LEDMatrix display width and height

## Installation

Install this repository as a third-party LEDMatrix plugin using the LEDMatrix Plugin Manager, or place it in the appropriate LEDMatrix plugin repository directory for your installation.

Repository:

```text
https://github.com/airbornetrooper82573/LEDMatrix-Plex-Showtime
```

## Configuration

Example:

```json
{
  "plex-showtime": {
    "enabled": true,
    "display_duration": 20,
    "plex_url": "http://192.168.1.50:32400",
    "plex_token": "YOUR_PLEX_TOKEN",
    "show_playing": true,
    "show_recently_added": true,
    "show_recently_played": true,
    "show_library": true,
    "filter_movies": true,
    "filter_tv": true,
    "filter_music": false,
    "show_heading": true,
    "show_year": true,
    "show_summary": false,
    "layout": "auto",
    "artwork_mode": "auto",
    "recent_count": 20,
    "live_priority": false
  }
}
```

## Content Selection

When the plugin updates:

1. If `show_playing` is enabled and Plex has an active session, an active session is selected.
2. Otherwise the plugin randomly tries enabled sources among Recently Added, Recently Played, and Library.
3. A random eligible media item is selected from the chosen source.

## Layouts

### `auto`

Uses artwork + information on wide displays and full artwork on more compact displays.

### `artwork_info`

Shows cropped Plex artwork on the left and metadata on the remaining display area.

### `full_artwork`

Fills the display with Plex artwork and overlays the source and title.

## Artwork Modes

- `auto` — background art normally, poster/thumb when summaries are enabled
- `poster` — prefer Plex thumb/poster art
- `background` — prefer Plex background art

## Plex Token

You need the `X-Plex-Token` for your Plex account/server. Do not commit your real token to this repository. Enter it only in your local LEDMatrix configuration or Plugin Manager.

## Requirements

- LEDMatrix 2.0.0 or newer
- A reachable Plex Media Server
- Plex token
- Pillow

## Change notes

### 1.9.1 — 2026-10-31
- Active entry point changed to `manager_v18.py` (the older `manager.py` is legacy and truncates text).
- Preserve existing full scrolling for long movie/show titles and independent TV episode-name scrolling using the persistent v1.7 session lifecycle.
- Avoid enabling LEDMatrix core scrolling-state mode, which caused text corruption on the user's five-panel P5 setup in the Home Assistant plugin; keep Plex's native time-based pixel offsets.
- Preserve v1.9.0 balanced rotation, artwork preferences, Now Playing user filtering, and display configuration.
- Physical playback test is required; the old `manager.py` is not the active runtime entry point.

## Initial Release Notes

Version `1.0.0` is the first working implementation. It intentionally uses only Plex APIs and Plex artwork so there are no additional media metadata services to configure.

## Credits

Inspired by:

- ChuckBuilds LEDMatrix
- Tronbyt Plex Showtime
- Existing LEDMatrix Plex Marquee plugin patterns

## License

Intended for use with the LEDMatrix ecosystem. Add the license you prefer for redistribution before publishing broadly.
