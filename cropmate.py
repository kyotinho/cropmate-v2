import sys
import os
import json
import time
import random
import threading

from minescript import (
    echo,
    execute,
    player,
    player_press_left,
    player_press_right,
    player_press_forward,
    player_press_attack,
    EventQueue,
    EventType,
)

REWARPS_FILE      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cropmate_rewarps.json")
POLL_INTERVAL     = 0.05   # position check frequency (seconds)

# ---------------------------------------------------------------------------
# Rewarp detection — improved: uses closest-point distance (Euclidean XZ + Y)
# ---------------------------------------------------------------------------
XZ_TOLERANCE      = 1.5    # tolerance in blocks for X and Z axes
Y_TOLERANCE       = 0.6    # tolerance in blocks for Y axis

# ---------------------------------------------------------------------------
# Warp settings
# ---------------------------------------------------------------------------
WARP_AFTER_ROWS   = 10     # warp to garden every N completed row pairs (modes 1/2)
WARP_Y            = 67     # only warp if player is at this Y (+-Y_TOLERANCE)
WARP_Y_TOLERANCE  = 0.6
WARP_DELAY_MIN    = 2.5    # min seconds before warping
WARP_DELAY_MAX    = 5.0    # max seconds before warping
WARP_LOAD_MIN     = 3.0    # min seconds waiting for teleport to load
WARP_LOAD_MAX     = 5.5    # max seconds waiting for teleport to load

# ---------------------------------------------------------------------------
# Row timing
# ---------------------------------------------------------------------------
WAIT_ROW_MIN      = 0.8    # min pause between rows
WAIT_ROW_MAX      = 1.6    # max pause between rows

ROW_TIMEOUT       = 90.0   # safety timeout per row (seconds)

# ---------------------------------------------------------------------------
# Stuck detection (modes 1/2 — vertical farm)
# ---------------------------------------------------------------------------
JUMP_STUCK_MIN    = 2.0    # min seconds without XZ advance before reversing
JUMP_STUCK_MAX    = 4.5    # max seconds (randomized each check)
JUMP_XZ_ADVANCE   = 0.4    # min XZ movement to not be considered stuck

# ---------------------------------------------------------------------------
# Horizontal snake mode (modes 3/4 — melons, pumpkins, sugar cane, flowers)
# Faster stuck check since rows are flat and short
# ---------------------------------------------------------------------------
HSNAKE_STUCK_MIN  = 0.8    # min seconds without advance before triggering W step
HSNAKE_STUCK_MAX  = 1.8    # max seconds
HSNAKE_XZ_ADVANCE = 0.3    # min XZ movement to not be considered stuck
HSNAKE_W_DURATION = 0.4    # how long to hold W when stepping to the next row (seconds)
HSNAKE_W_MIN      = 0.3    # random variance min for W hold
HSNAKE_W_MAX      = 0.6    # random variance max for W hold

# ---------------------------------------------------------------------------
# Fullauto — random breaks between farm sessions
# ---------------------------------------------------------------------------
FULLAUTO_MIN      = 180.0  # 3 minutes
FULLAUTO_MAX      = 360.0  # 6 minutes

KEY_GRAVE = 96
KEY_Q     = 81
MOD_CTRL  = 2

_paused  = threading.Event()
_quit    = threading.Event()
_restart = threading.Event()


def release_all():
    player_press_left(False)
    player_press_right(False)
    player_press_forward(False)
    player_press_attack(False)


# ---------------------------------------------------------------------------
# Rewarp points
# ---------------------------------------------------------------------------

def load_rewarps():
    if not os.path.exists(REWARPS_FILE):
        return []
    try:
        with open(REWARPS_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_rewarps(points):
    with open(REWARPS_FILE, "w") as f:
        json.dump(points, f, indent=2)


def add_rewarp_point():
    pos = player().position
    px, py, pz = round(pos[0], 2), round(pos[1], 2), round(pos[2], 2)
    points = load_rewarps()
    label = f"Point {len(points) + 1}"
    points.append({"x": px, "y": py, "z": pz, "label": label})
    save_rewarps(points)
    echo(f"§a[CropMate] Point saved: {label} at X:{px} Y:{py} Z:{pz}")


def clear_rewarps():
    save_rewarps([])
    echo("§c[CropMate] All points cleared.")


def near_any_point(px, py, pz):
    """
    Improved check: uses true Euclidean distance on XZ and a separate Y gate.
    More reliable than separate axis checks — avoids triggering on corners.
    """
    for p in load_rewarps():
        xz_dist = ((px - p["x"]) ** 2 + (pz - p["z"]) ** 2) ** 0.5
        y_dist   = abs(py - p["y"])
        if xz_dist <= XZ_TOLERANCE and y_dist <= Y_TOLERANCE:
            return True
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sleep_random(min_s, max_s):
    deadline = time.monotonic() + random.uniform(min_s, max_s)
    while time.monotonic() < deadline:
        if _quit.is_set() or _restart.is_set():
            return True
        time.sleep(POLL_INTERVAL)
    return False


def do_warp():
    release_all()
    if sleep_random(WARP_DELAY_MIN, WARP_DELAY_MAX):
        return
    current_y = player().position[1]
    if abs(current_y - WARP_Y) > WARP_Y_TOLERANCE:
        echo(f"§e[CropMate] Warp skipped — current Y ({current_y:.1f}) != {WARP_Y}")
        player_press_attack(True)
        return
    echo("§b[CropMate] Warping to garden...")
    execute("warp garden")
    sleep_random(WARP_LOAD_MIN, WARP_LOAD_MAX)
    player_press_attack(True)


# ---------------------------------------------------------------------------
# Modes 1/2 — vertical farm row traversal
# ---------------------------------------------------------------------------

def wait_for_row_end(press_current, press_opposite):
    """
    Moves in the current direction until reaching a saved point.
    If no XZ advance is detected after a random interval, reverses direction.
    Returns True if interrupted, False if reached the point.
    """
    deadline      = time.monotonic() + ROW_TIMEOUT
    current_press = press_current

    check_interval = random.uniform(JUMP_STUCK_MIN, JUMP_STUCK_MAX)
    next_check     = time.monotonic() + check_interval
    ref_x          = None
    ref_z          = None

    while True:
        if _quit.is_set() or _restart.is_set():
            return True

        if time.monotonic() > deadline:
            echo("§e[CropMate] Row timeout — restarting!")
            _restart.set()
            return True

        if _paused.is_set():
            release_all()
            pause_start = time.monotonic()
            while _paused.is_set():
                if _quit.is_set() or _restart.is_set():
                    return True
                time.sleep(POLL_INTERVAL)
            deadline   += time.monotonic() - pause_start
            next_check  = time.monotonic() + check_interval
            current_press(True)
            continue

        try:
            pos = player().position
        except Exception:
            time.sleep(POLL_INTERVAL)
            continue

        px, py, pz = pos[0], pos[1], pos[2]

        if ref_x is None:
            ref_x, ref_z = px, pz

        if near_any_point(px, py, pz):
            return False

        if time.monotonic() >= next_check:
            xz_advance = abs(px - ref_x) + abs(pz - ref_z)
            if xz_advance < JUMP_XZ_ADVANCE:
                echo("§e[CropMate] No advance detected — reversing direction!")
                current_press(False)
                current_press = press_opposite if current_press is press_current else press_current
                current_press(True)
            ref_x, ref_z   = px, pz
            check_interval = random.uniform(JUMP_STUCK_MIN, JUMP_STUCK_MAX)
            next_check     = time.monotonic() + check_interval

        time.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Modes 3/4 — horizontal snake farm (melons, pumpkins, sugar cane, flowers)
# Pattern: press A/D → reach end → tap W → press D/A → repeat
# ---------------------------------------------------------------------------

def hsnake_step_forward():
    """Taps W for a randomized short duration to move to the next row."""
    player_press_forward(True)
    sleep_random(HSNAKE_W_MIN, HSNAKE_W_MAX)
    player_press_forward(False)


def hsnake_wait_for_row_end(press_current, press_opposite):
    """
    Faster stuck detection for flat horizontal farms.
    When stuck (no XZ advance), taps W to step to the next row,
    then reverses the horizontal direction.
    Returns True if interrupted, False if reached a rewarp point.
    """
    deadline      = time.monotonic() + ROW_TIMEOUT
    current_press = press_current

    check_interval = random.uniform(HSNAKE_STUCK_MIN, HSNAKE_STUCK_MAX)
    next_check     = time.monotonic() + check_interval
    ref_x          = None
    ref_z          = None

    while True:
        if _quit.is_set() or _restart.is_set():
            return True

        if time.monotonic() > deadline:
            echo("§e[CropMate] Row timeout — restarting!")
            _restart.set()
            return True

        if _paused.is_set():
            release_all()
            pause_start = time.monotonic()
            while _paused.is_set():
                if _quit.is_set() or _restart.is_set():
                    return True
                time.sleep(POLL_INTERVAL)
            deadline   += time.monotonic() - pause_start
            next_check  = time.monotonic() + check_interval
            current_press(True)
            continue

        try:
            pos = player().position
        except Exception:
            time.sleep(POLL_INTERVAL)
            continue

        px, py, pz = pos[0], pos[1], pos[2]

        if ref_x is None:
            ref_x, ref_z = px, pz

        # If we reached a rewarp point we're done with this pass
        if near_any_point(px, py, pz):
            return False

        if time.monotonic() >= next_check:
            xz_advance = abs(px - ref_x) + abs(pz - ref_z)
            if xz_advance < HSNAKE_XZ_ADVANCE:
                # End of row — step forward (W) then reverse horizontal direction
                echo("§7[CropMate] End of row — stepping forward and reversing.")
                current_press(False)
                hsnake_step_forward()
                if _quit.is_set() or _restart.is_set():
                    return True
                current_press = press_opposite if current_press is press_current else press_current
                current_press(True)
            ref_x, ref_z   = px, pz
            check_interval = random.uniform(HSNAKE_STUCK_MIN, HSNAKE_STUCK_MAX)
            next_check     = time.monotonic() + check_interval

        time.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Fullauto — random breaks between farm sessions
# ---------------------------------------------------------------------------

def fullauto_thread(macro_num):
    while not _quit.is_set():
        wait = random.uniform(FULLAUTO_MIN, FULLAUTO_MAX)
        mins = int(wait // 60)
        secs = int(wait % 60)
        echo(f"§d[CropMate] Fullauto: next break in {mins}m{secs:02d}s")
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if _quit.is_set():
                return
            time.sleep(POLL_INTERVAL)
        if _quit.is_set():
            return
        _paused.set()
        pause_dur = random.uniform(FULLAUTO_MIN, FULLAUTO_MAX)
        pmins = int(pause_dur // 60)
        psecs = int(pause_dur % 60)
        echo(f"§d[CropMate] Fullauto: pausing for {pmins}m{psecs:02d}s...")
        release_all()
        deadline2 = time.monotonic() + pause_dur
        while time.monotonic() < deadline2:
            if _quit.is_set():
                return
            time.sleep(POLL_INTERVAL)
        _paused.clear()
        echo("§d[CropMate] Fullauto: resuming!")


# ---------------------------------------------------------------------------
# Key listener
# ---------------------------------------------------------------------------

def key_listener_thread():
    with EventQueue() as eq:
        eq.register_key_listener()
        while not _quit.is_set():
            try:
                event = eq.get(timeout=0.2)
            except Exception:
                continue
            if event is None or event.type != EventType.KEY or event.action != 1:
                continue
            if event.key == KEY_GRAVE:
                if _paused.is_set():
                    _paused.clear()
                    echo("§a[CropMate] Resumed")
                else:
                    _paused.set()
                    echo("§e[CropMate] Paused")
            elif event.key == KEY_Q and (event.modifiers & MOD_CTRL):
                _quit.set()


# ---------------------------------------------------------------------------
# Macro loop — modes 1/2 (vertical, layered farm)
# ---------------------------------------------------------------------------

def run_macro(macro_num, fullauto=False):
    if not load_rewarps():
        echo("§c[CropMate] No points saved! Use \\cropmate addrewarp at both ends of your farm.")
        return

    if macro_num == 1:
        def press_first(on):  player_press_left(on);  player_press_right(not on)
        def press_second(on): player_press_right(on); player_press_left(not on)
        label = "A→D"
    else:
        def press_first(on):  player_press_right(on); player_press_left(not on)
        def press_second(on): player_press_left(on);  player_press_right(not on)
        label = "D→A"

    fa_label = "  §dFULLAUTO ON§a" if fullauto else ""
    echo(f"§a[CropMate] Started ({label}){fa_label}  ` = pause  Ctrl+Q = quit")

    row_count = 0
    player_press_attack(True)

    while not _quit.is_set():

        if _restart.is_set():
            release_all()
            echo("§6[CropMate] Restarting — warping to garden...")
            execute("warp garden")
            sleep_random(WARP_LOAD_MIN, WARP_LOAD_MAX)
            if _quit.is_set():
                break
            player_press_attack(True)
            row_count = 0
            _restart.clear()
            continue

        if _paused.is_set():
            time.sleep(POLL_INTERVAL)
            continue

        press_first(True)
        if wait_for_row_end(press_first, press_second):
            press_first(False)
            continue
        press_first(False)
        if sleep_random(WAIT_ROW_MIN, WAIT_ROW_MAX):
            continue

        press_second(True)
        if wait_for_row_end(press_second, press_first):
            press_second(False)
            continue
        press_second(False)
        if sleep_random(WAIT_ROW_MIN, WAIT_ROW_MAX):
            continue

        row_count += 1
        if row_count >= WARP_AFTER_ROWS:
            do_warp()
            if _quit.is_set():
                break
            row_count = 0


# ---------------------------------------------------------------------------
# Macro loop — modes 3/4 (horizontal snake, flat farm)
# ---------------------------------------------------------------------------

def run_hsnake(macro_num, fullauto=False):
    if not load_rewarps():
        echo("§c[CropMate] No points saved! Use \\cropmate addrewarp at the end of your farm.")
        return

    if macro_num == 3:
        def press_first(on):  player_press_left(on);  player_press_right(not on)
        def press_second(on): player_press_right(on); player_press_left(not on)
        label = "A→W→D (melon/pumpkin)"
    else:
        def press_first(on):  player_press_right(on); player_press_left(not on)
        def press_second(on): player_press_left(on);  player_press_right(not on)
        label = "D→W→A (melon/pumpkin)"

    fa_label = "  §dFULLAUTO ON§a" if fullauto else ""
    echo(f"§a[CropMate] Started ({label}){fa_label}  ` = pause  Ctrl+Q = quit")

    row_count = 0
    player_press_attack(True)

    while not _quit.is_set():

        if _restart.is_set():
            release_all()
            echo("§6[CropMate] Restarting — warping to garden...")
            execute("warp garden")
            sleep_random(WARP_LOAD_MIN, WARP_LOAD_MAX)
            if _quit.is_set():
                break
            player_press_attack(True)
            row_count = 0
            _restart.clear()
            continue

        if _paused.is_set():
            time.sleep(POLL_INTERVAL)
            continue

        # Snake pass — hsnake_wait_for_row_end handles W steps internally
        press_first(True)
        if hsnake_wait_for_row_end(press_first, press_second):
            press_first(False)
            continue
        # Reached rewarp point — warp back
        press_first(False)
        do_warp()
        if _quit.is_set():
            break
        row_count = 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    if not args:
        return

    cmd = args[0].lower()

    if cmd == "addrewarp":   add_rewarp_point(); return
    if cmd == "clearrewarp": clear_rewarps();    return

    fullauto = False
    if cmd == "fullauto":
        if len(args) < 2 or args[1] not in ("1", "2", "3", "4"):
            echo("§c[CropMate] Usage: \\cropmate fullauto 1/2/3/4")
            return
        fullauto = True
        cmd = args[1]

    if cmd not in ("1", "2", "3", "4"):
        return

    listener = threading.Thread(target=key_listener_thread, daemon=True)
    listener.start()

    if fullauto:
        fa_thread = threading.Thread(target=fullauto_thread, args=(int(cmd),), daemon=True)
        fa_thread.start()

    try:
        macro_num = int(cmd)
        if macro_num in (1, 2):
            run_macro(macro_num, fullauto=fullauto)
        else:
            run_hsnake(macro_num, fullauto=fullauto)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        _quit.set()
        release_all()
        echo("§c[CropMate] Stopped.")
        listener.join(timeout=1.0)


main()
