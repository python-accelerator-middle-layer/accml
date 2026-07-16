import asyncio
import itertools
import json

import jsons

from accml.core.utils.basic_measurement_execution_engine import BasicMeasurementExecutionEngine
from accml.core.utils.simple_storage import SimpleDataStorage
from accml.custom.ophyd_async.ophyd_async_backend import OphydAsyncDeviceBackendRW
from accml.custom.ophyd_async.ophyd_async_delta_backend import OphydAsyncDeltaBackendRWProxy
from accml_lib.core.bl.delta_backend import StateCache

from dt4acc_lib.bl.command_rewritter import CommandRewriter
from dt4acc.custom_facility.als.gpt.dt4acc_bootstrap import load_managers
from dt4acc.custom_facility.als.ophyd_async_devices_setup import setup
from accml_lib.core.model import jsons_support
from dt4acc_lib.model.utils.command import ReadCommand, TransactionCommand, Command, BehaviourOnError

jsons_fork = jsons.fork()
jsons_support.register_serializers(jsons_fork)


async def main():
    yp, lm, ts, epics_vars = load_managers()
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
    storage = SimpleDataStorage()

    backend = OphydAsyncDeltaBackendRWProxy(
        backend=OphydAsyncDeviceBackendRW(devices=devices),
        cache=StateCache(name="ALS_OphydAsync_Dev_State_Cache"),
    )
    mexec = BasicMeasurementExecutionEngine(
        backend=backend,
        cmd_rewriter=CommandRewriter(liaison_manager=lm, translation_service=ts),
        storage=storage,
        expected_view_for_output="device",
        num_readings=1
    )

    # todo: need to improve setup of run:
    #  any write to this pv should trigger calculation of turn by turn data
    run_count = itertools.count()
    # advance it a bit ...
    [next(run_count) for i in range(100)]

    commands = [
        TransactionCommand(
            transaction=[
                # n turns only need to be set once
                Command(id="turn_by_turn", property="n_turns", value=200, behaviour_on_error=BehaviourOnError.stop),
                Command(id="turn_by_turn", property="start_vec", value=[1e-3, 0., 0, 1e-3, 0, 0],
                        behaviour_on_error=BehaviourOnError.stop),
                Command(id="turn_by_turn", property="run", value=next(run_count),
                        behaviour_on_error=BehaviourOnError.stop)
            ]
        ),
        TransactionCommand(
            transaction=[
                # n turns only need to be set once
                Command(id="turn_by_turn", property="start_vec", value=[0, 1e-3, 0, 0, 0, 0],
                        behaviour_on_error=BehaviourOnError.stop),
                Command(id="turn_by_turn", property="run", value=next(run_count),
                        behaviour_on_error=BehaviourOnError.stop)
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
        md=md,
    )
    print(f"Run created {uid=}")
    data = storage.get(uid)
    data = jsons.dump(data, fork_inst=jsons_fork)

    with open("turn_by_turn_data_for_different_vectors.json", "wt") as fp:
        json.dump(data, fp, indent=4)



if __name__ == "__main__":
    asyncio.run(main())