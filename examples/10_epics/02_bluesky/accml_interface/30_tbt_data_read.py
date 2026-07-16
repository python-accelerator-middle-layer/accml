import logging

from ophyd_async.core import soft_signal_rw

logging.basicConfig(level=logging.WARNING)

import asyncio
import itertools

import jsons
from bluesky import RunEngine

from accml.custom.bluesky.bluesky_measurement_execution_engine import BlueskyMeasurementExecutionEngine
from accml_lib.core.bl.delta_backend import StateCache

from dt4acc.custom_facility.als.gpt.dt4acc_bootstrap import load_managers
from dt4acc.custom_facility.als.ophyd_async_devices_setup import setup
from accml_lib.core.model import jsons_support
from dt4acc_lib.model.utils.command import ReadCommand, TransactionCommand, Command, BehaviourOnError

jsons_fork = jsons.fork()
jsons_support.register_serializers(jsons_fork)


async def main():
    yp, lm, ts, epics_vars = load_managers()
    devices=setup()
    # ON BESSY II machine
    # devices = setup(prefix="")
    # On Twin None ... means default
    devices = setup(prefix=None)
    tbt_bpms = devices.get("tbt_bpms")
    # Interface to configure how it runs
    turn_by_turn = devices.get("turn_by_turn")
    await turn_by_turn.connect()
    await asyncio.gather(*[bpm.connect() for bpm in tbt_bpms.values()])
    detectors =  [
        [ReadCommand(id, "x"), ReadCommand(id, "y"), ReadCommand(id, "sum")] for id in tbt_bpms.keys()
    ]
    detectors = list(itertools.chain.from_iterable(detectors))

    RE = RunEngine()
    state_cache = StateCache(name="ALS_OphydAsync_State_Cache")
    info_sigs = {
        name: soft_signal_rw(str, name=name) for name in ["device_name", "channel_name"]
    }
    info_sigs["channel_value"] = soft_signal_rw(
        float, name="channel_value", precision=10
    )

    mexec = BlueskyMeasurementExecutionEngine(
        run_engine=RE,
        devices=devices,
        info_signals=info_sigs,
        cache=state_cache
    )


    commands = [
        TransactionCommand(
            transaction=[
                Command(id="turn_by_turn", property="n_turns", value=10, behaviour_on_error=BehaviourOnError.stop),
                Command(id="turn_by_turn", property="run", value=1, behaviour_on_error=BehaviourOnError.stop)
            ]
        )
    ]
    md = {}
    uid = await mexec.execute(
        detectors=detectors,
        commands_collection=commands,
        # detectors=[tunes],
        # actuators=actuators,
        # info_signals=info_signals,
        n_readings=1,
        md=md,
    )
    print(f"Run created {uid=}")



if __name__ == "__main__":
    asyncio.run(main())