import logging
logging.basicConfig(level=logging.WARNING)

import asyncio
import numpy as np

from bluesky import RunEngine
import bluesky.plans as bp
from databroker import catalog

from dt4acc.custom_facility.als.gpt.dt4acc_bootstrap import load_managers
from dt4acc.custom_facility.als.ophyd_async_devices_setup import setup



async def main():
    yp, lm, ts, epics_vars = load_managers()
    devices=setup()
    # ON BESSY II machine
    # devices = setup(prefix="")
    # On Twin None ... means default

    db = catalog["heavy_local"]

    devices = setup(prefix=None)
    tbt_bpms = devices.get("tbt_bpms")
    # Need to find out why these don't have data
    excluded_bpms = ['SR01C:BPM2', 'SR01C:BPM6', 'SR03C:BPM2', 'SR03C:BPM7', 'SR04C:BPM1', 'SR04C:BPM2', 'SR04C:BPM7',
     'SR04C:BPM8', 'SR06C:BPM1', 'SR06C:BPM2', 'SR06C:BPM7', 'SR06C:BPM8', 'SR07C:BPM1', 'SR07C:BPM2',
     'SR07C:BPM7', 'SR07C:BPM8', 'SR11C:BPM1', 'SR11C:BPM2', 'SR11C:BPM7', 'SR11C:BPM8']

    tbt_bpms = {bpm_name : dev for bpm_name, dev in tbt_bpms.items() if bpm_name not in excluded_bpms}
    # Interface to configure how it runs
    turn_by_turn = devices.get("turn_by_turn")
    await turn_by_turn.connect()

    tbt_d = await turn_by_turn.describe()
    tbt_r = await turn_by_turn.read()

    await asyncio.gather(*[bpm.connect() for bpm in tbt_bpms.values()])

    all_devices = list(tbt_bpms.values()) + [turn_by_turn]
    d = await asyncio.gather(*[dev.describe() for dev in all_devices])
    r = await asyncio.gather(*[dev.read() for dev in all_devices])

    # NB:
    #   if you want to read back your data with bluesky databroker
    #   only change this value at the beginning!
    await turn_by_turn.n_turns.set(20)

    # could use the particle state here too
    vecs = [
        [0] * 6,
        [1e-4, 0, 0, 0, 0, 0],
        [1e-3, 0, 0, 0, 0, 0],
    ]
    RE = RunEngine({})
    RE.subscribe(db.v1.insert)
    uid, = RE(bp.list_scan(
        all_devices,
        turn_by_turn.run, np.arange(len(vecs)),
        turn_by_turn.start_vec, vecs
    ))

    print(f"scan {uid=} ")


if __name__ == "__main__":
    asyncio.run(main())