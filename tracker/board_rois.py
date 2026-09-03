# Pixel geometry (in the captured client-rect frame) of the player's board
# row: 10 fixed sockets (PlayerSocket_0..9) laid out left-to-right. The log
# only ever reports which socket an item *starts* in, never its size, so
# screenshot.crop_item_icon() infers the actual span from which other
# sockets are simultaneously occupied.
#
# During combat the screen shows BOTH boards stacked vertically: the
# opponent's row up top (right under their own health bar) and the
# player's own row lower down (right above their own health bar/portrait).
# This is the *lower* row -- confirmed against three real 1920x1057 combat
# captures on 2026-09-03, cross-checked by hero portrait (the player's own
# hero, "Jules" in every run so far, is always the bottom portrait). An
# earlier calibration used the *upper* row by mistake, captured off a
# vendor-encounter screenshot rather than an actual fight -- that row
# belongs to the opponent, not the player.
BOARD_ROIS = {
    "1920x1057": {
        "row_left": 400,
        "row_top": 525,
        "row_bottom": 755,
        "cell_width": 112,
        "socket_count": 10,
    },
}
