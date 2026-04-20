# CropMate
A Minescript-based farming tool for Hypixel Skyblock.

Supports layered vertical farms (nether wart, carrots, potatoes, wheat) and flat horizontal farms (melons, pumpkins, sugar cane, flowers), with coordinate-based row detection, automatic warping, and human-like randomized timing.

---

## Requirements

- [Minescript](https://minescript.net/) mod installed (Fabric or Forge)
- Python script placed at `.minecraft/minescript/cropmate.py`

---

## Setup

Before running any macro, save your row-end points with `\cropmate addrewarp`:

- **Modes 1 & 2** — stand at each end of your farm and run `addrewarp` at both. The script uses X, Y, and Z to detect when you've reached the boundary.
- **Modes 3 & 4** — run `addrewarp` only at the far end of the farm. Row transitions are handled automatically via W steps.

---

## Commands

| Command | Description |
|---|---|
| `\cropmate 1` | Start vertical macro — A → D |
| `\cropmate 2` | Start vertical macro — D → A |
| `\cropmate 3` | Start horizontal snake macro — A → W → D (melons, pumpkins, cane, flowers) |
| `\cropmate 4` | Start horizontal snake macro — D → W → A |
| `\cropmate fullauto 1/2/3/4` | Start any mode with automatic random breaks (3–6 min) |
| `\cropmate addrewarp` | Save current position as a row-end point |
| `\cropmate clearrewarp` | Delete all saved points |

---

## Controls

| Key | Action |
|---|---|
| `` ` `` (grave) | Pause / Resume |
| `Ctrl + Q` | Stop macro |

---

## Features

- **Coordinate-based row detection** — uses Euclidean XZ distance + Y gate for accurate, corner-safe boundary detection
- **Stuck detection** — if no XZ advance is detected within a randomized window, automatically reverses direction (modes 1/2) or steps to the next row with W (modes 3/4)
- **Y-gated warp** — only executes `warp garden` if the player is at Y=67 (±0.6), preventing warps from wrong positions
- **Periodic warp** — warps back to garden every 10 completed row pairs
- **Fullauto mode** — randomly pauses the macro for 3–6 minutes every 3–6 minutes of farming, then resumes automatically
- **Randomized timing throughout** — row pauses, warp delays, load waits, stuck check intervals, and W step durations are all randomized ranges so behavior never repeats exactly

---

## Roadmap

- [✔️] Sugar cane / flower / rose / sunflower macro polish
- [ ] Pest detection failsafe
- [ ] Configurable warp command and Y target via arguments

---

## Disclaimer

This project is intended for use while you are present at your computer and actively monitoring the screen.

CropMate does **not** guarantee protection from anti-cheat detection. **You can and likely will be banned if you go AFK and get macro-checked.** Use at your own risk.

This project is not affiliated with Microsoft, Mojang, or Hypixel.

Credits to https://github.com/bkgrnd for developing the first and original concept of the script, you can check it you [here](https://github.com/bkgrnd/cropmate)
