# Pixel geometry (in the captured client-rect frame) of the player's board
# row: 10 fixed sockets (PlayerSocket_0..9) laid out left-to-right. The log
# only ever reports which socket an item *starts* in, never its size, so
# screenshot.crop_item_icon() infers the actual span from which other
# sockets are simultaneously occupied.
#
# This exact row is reused by the game in several contexts (confirmed
# against a real 1920x1057 capture, 2026-09-03): it's the player's own board
# during a fight, the shop/vendor stock display outside of one, and --
# except during combat, where it instead shows the *opponent's* board --
# also the stash. Only combat is unambiguous (nothing else can be drawn
# over it), which is why capture is triggered off CombatStarted.
BOARD_ROIS = {
    "1920x1057": {
        "row_left": 400,
        "row_top": 300,
        "row_bottom": 528,
        "cell_width": 112,
        "socket_count": 10,
    },
}
