# Third-party notices

AI Cycling Coach is MIT licensed (see `LICENSE`). It talks to Bluetooth devices using protocols that other open
source projects documented. Protocol facts (message layouts, constants, the table of Zwift's 24 gears) are not
copied code, but we credit every project we learned from.

## Code adapted from other projects (license text below)

| Project | License | What |
|---|---|---|
| [chrisperkles/serpentine](https://github.com/chrisperkles/serpentine) @e4f2126 | MIT | Zwift protocol message layout, scaling and handshake, ported to Python in `trainer-adapter/coach/devices/zwift_hub.py`; virtual-shifting timings (80 ms merge, 10 s grade refresh); route grade method (3 passes of a ±30 m mean, grade over ±20 m, `src/geo/route.ts`) re-implemented in `trainer-adapter/coach/session/route.py` |
| [incyclist/devices](https://github.com/incyclist/devices) @07e0035 | MIT | cross-check of the same protocol; HubRequest 512; Zwift type bytes and FTMS priority in discovery; cross-check of the speed-from-power model (`src/utils/calculations.ts`) |
| [jat255/zwift_click_handling](https://github.com/jat255/zwift_click_handling) @7cf896d | MIT | Zwift Click handshake and battery field (`trainer-adapter/tools/zwift_click_v36.py`) |

## Projects used as references only (no code taken)

| Project | License | What we learned |
|---|---|---|
| [dadepro/zwift-virtual-shifting](https://github.com/dadepro/zwift-virtual-shifting) | MIT | a Python/Bleak reference for virtual shifting |
| [OpenBikeControl/openbikecontrol-protocol](https://github.com/OpenBikeControl/openbikecontrol-protocol) | MIT | button protocol, for the future |
| [OpenBikeControl/bikecontrol](https://github.com/OpenBikeControl/bikecontrol) | non-commercial (GPL-3.0 before tag `gpl3`) | ideas only: classification order, button bit table |
| [cagnulein/qdomyos-zwift](https://github.com/cagnulein/qdomyos-zwift) | GPL-3.0 | ideas only |
| [JuergenLeber/SHIFTR](https://github.com/JuergenLeber/SHIFTR) | GPL-3.0 | ideas only (same gear table) |
| [ajchellew/zwiftplay](https://github.com/ajchellew/zwiftplay) | no license | ideas only: protocol documentation |
| [tkrajina/gpxpy](https://github.com/tkrajina/gpxpy) @056cdfc | Apache-2.0 | compared only: elevation gain with light smoothing |
| [GoldenCheetah/GoldenCheetah](https://github.com/GoldenCheetah/GoldenCheetah) @0cf3acc | GPL-2.0 | compared only (idea): elevation gain with a 3 m hysteresis |

---

## License of serpentine

```
MIT License

Copyright (c) 2026 Chris Perkles

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## License of incyclist/devices

```
MIT License

Copyright (c) 2021 Incyclist

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## License of zwift_click_handling

```
MIT License

Copyright (c) 2024 Joshua Taillon

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.```
