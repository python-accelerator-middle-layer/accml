"""Demonstrator of a measurement execution engine

Todo:
    * implement full functionality

Missing features:

* handling behaviour_on_error
* how much of the accelerator access to wrap?
* hide devices behind a software multiplexer?
  In its current form quite some information will be stored
  in the databroker

"""
import asyncio
from typing import Sequence, Dict

from bluesky import RunEngine
from ophyd_async.core import Signal

from .plans import commands_execution_plan
from .utils import extract_device_identifiers, connect_to_devices
from accml_lib.core.bl.delta_backend import StateCache
from accml_lib.core.interfaces.utils.devices_facade import DevicesFacade
from accml_lib.core.interfaces.utils.measurement_execution_engine import (
    MeasurementExecutionEngine,
)
from dt4acc_lib.model.utils.command import Command, ReadCommand, TransactionCommand
from dt4acc_lib.model.output.result import ReadTogether


class BlueskyMeasurementExecutionEngine(MeasurementExecutionEngine):
    """Demonstrator of a measurement engine as a bluesky runengine"""

    def __init__(
        self,
        *,
        devices: DevicesFacade,
        run_engine: RunEngine,
        info_signals: Sequence[Signal],
        cache: StateCache,
    ):
        """

        Todo:
            Specify the device type
        """
        self.run_engine = run_engine
        self.devices = devices
        self.info_signals = info_signals
        self.cache = cache

    async def execute(
        self,
        commands_collection: Sequence[TransactionCommand],
        detectors: Sequence[ReadCommand],
        # actuators: Dict[str, Device],
        md: Dict[str, object],
        **kwargs,
    ) -> str:

        actuator_identifiers = extract_device_identifiers(commands_collection)

        def get_device(id_: str):
            dev = self.devices.get(id_)
            assert dev is not None, f"Failed to find a device assosiated for {id_}"
            return dev
        actuators = {id_: get_device(id_) for id_ in actuator_identifiers}
        dets = [get_device(det.id) for det in detectors]

        await connect_to_devices(list(actuators.values()) + dets)

        plan = commands_execution_plan(
            commands=commands_collection,
            detectors=dets,
            actuators=actuators,
            cache=self.cache,
            info_signals=self.info_signals,
            md=md,
            **kwargs,
        )
        (uid,) = self.run_engine(plan)
        return uid

    async def set(self, cmds: Sequence[Command]):
        raise NotImplementedError("needs to be implemented")

    async def trigger_read(self, cmds: Sequence[ReadCommand]) -> ReadTogether:
        # signals = [getattr(self.devices.get(cmd.id), cmd.property) for cmd in cmds]
        # devices = [self.devices.get(cmd.id) for cmd in cmds]
        raise NotImplementedError("needs to be implemented")
