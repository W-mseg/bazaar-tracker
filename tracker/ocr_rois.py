# coords are (x, y, w, h) in pixels
# Ported from the Bazaar Chronicle project (MIT licensed) -- this part of
# their pipeline is independent of the broken log parsing and still works.
ROIS = {
    "1920x1080": {
          "wins": [840, 176, 120, 104],
          "max_health": [612, 828, 288, 43],
          "prestige": [917, 828, 214, 46],
          "level": [1161, 828, 204, 43],
          "income": [1399, 828, 182, 44],
          "gold": [1627, 828, 173, 43]
        },

    # Captured via the game window's client rect rather than the full
    # monitor (see screenshot.py) -- on a 1920x1080 display that comes out
    # ~23px shorter, and the bottom stat bar sits noticeably higher as a
    # result. Calibrated against a real end-of-run screenshot (French UI,
    # v1.0.12222) where wins=7/max_health=5550/prestige=0/level=13/income=8
    # all read back correctly; gold is a known miss on that particular
    # screenshot due to a low-contrast decorative overlay behind the digits,
    # not a miscalibration -- see extract_run_metrics' fallback passes.
    "1920x1057": {
        "wins": [840, 176, 120, 104],
        "max_health": [612, 810, 288, 50],
        "prestige": [917, 810, 214, 50],
        "level": [1161, 810, 204, 50],
        "income": [1399, 810, 182, 50],
        "gold": [1630, 810, 180, 50],
    },

    "2879x1799": {
      "wins": [1263, 356, 167, 146],
      "max_health": [943, 1332, 327, 61],
      "prestige": [1414, 1332, 250, 64],
      "level": [1774, 1332, 225, 64],
      "income": [2139, 1332, 231, 68],
      "gold": [2440, 1332, 207, 63]
    },
}
