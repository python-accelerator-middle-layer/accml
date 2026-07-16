import functools
import itertools
from dataclasses import asdict
from typing import Sequence, Dict, Union

from bluesky import plan_stubs as bps, preprocessors as bpp
from ophyd_async.core import Device, Signal

from accml.custom.bluesky.utils import as_json_compatible_device_id
from accml_lib.core.bl.delta_backend import delta_property, StateCache
from dt4acc_lib.model.utils.command import TransactionCommand, Command, ReadCommand


def transactional_commands_sequence_execution_plan(
    *,
    transactional_commands: Sequence[TransactionCommand],
    detectors: Sequence[Device],
    actuators: Dict[str, Device],
    cache: StateCache,
    md: Dict,
    **kwargs,
):
    """Excute transactional commands using bluesky plan stubs"""
    _md = md or dict()
    # CommandSequence nor Commands is json seriazable ....
    _md.update(dict(commands=[asdict(cmd) for cmd in transactional_commands]))

    @bpp.stage_decorator(list(detectors) + list(actuators.values()))
    @bpp.run_decorator(md=_md)
    def inner():
        r = yield from transactional_actuator_commands_plan(
            transactional_commands=transactional_commands,
            detectors=detectors,
            actuators=actuators,
            cache=cache,
            **kwargs,
        )
        return r

    r = yield from inner()
    return r


def prepare_transactional_move(
    actuators: Dict[str, Device], transactional_command: Sequence[Command]
):
    r = []
    for cmd in transactional_command:
        t_device = actuators[cmd.id]
        channel = getattr(t_device, cmd.property)
        r.extend([channel, cmd.value])
    return r


def transactional_actuator_commands_plan(
    *,
    transactional_commands: Sequence[TransactionCommand],
    detectors: Sequence[Device],
    actuators: Dict[str, Device],
    cache: StateCache,
    num_readings: int,
    wait_before_read: float = 0,
):
    """

    Inner plan for :func:`transactional_commands_sequence_execution_plan`

    Todo:
        Implement stop, ignore, rollback etc
        Device replace by ophyd_async.Settable
        info_signals as dataclass?
    """

    assert (
        wait_before_read >= 0e0
    ), f"wait before read must be >=0 but was {wait_before_read}"
    all_dev = list(detectors) + list(actuators.values())

    for t_cmds in transactional_commands:
        # first select the device
        # then apply it to all
        cmds = rework_delta_commands(commands=t_cmds.transaction, cache=cache)
        yield from bps.mv(*prepare_transactional_move(actuators, cmds))
        # TODO: revisit how to address reading detectors
        #       also in the command language
        # read all devices
        yield from bps.wait()  # << required
        # optional: give hardware / twin time
        yield from bps.sleep(wait_before_read)
        #: todo: check behaviour if num_readings = 0
        yield from bps.repeat(
            functools.partial(bps.trigger_and_read, all_dev), num=num_readings
        )


def simple_command_sequence_execution_plan(
    *,
    commands: Sequence[Command],
    detectors: Sequence[Device],
    actuators: Dict[str, Device],
    info_signals: Dict[str, Signal],
    md: Dict,
    **kwargs,
):
    """Translate simple commands (i.e. only one device at a time) using bluesky plan stubs"""
    _md = md or dict()
    # CommandSequence nor Commands is json seriazable ....
    _md.update(dict(commands=[asdict(cmd) for cmd in commands]))

    @bpp.stage_decorator(list(detectors) + list(actuators.values()))
    @bpp.run_decorator(md=_md)
    def inner():
        r = yield from single_actuator_commands_plan(
            commands=commands,
            detectors=detectors,
            actuators=actuators,
            info_signals=info_signals,
            **kwargs,
        )
        return r

    r = yield from inner()
    return r


def single_actuator_commands_plan(
    *,
    commands: Sequence[Command],
    detectors: Sequence[Device],
    actuators: Dict[str, Device],
    info_signals: Dict[str, Signal],
    num_readings: int,
    wait_before_read: float = 0,
):
    """

    Inner plan for :func:`commands_execution_plan`

    Todo:
        Implement stop, ignore, rollback etc
        Device replace by ophyd_async.Settable
        info_signals as dataclass?
    """
    assert (
        wait_before_read >= 0e0
    ), f"wait before read must be >=0 but was {wait_before_read}"

    all_dev = list(info_signals.values()) + list(detectors) + list(actuators.values())
    dev_name = info_signals["device_name"]
    ch_name = info_signals["channel_name"]
    ch_val = info_signals["channel_value"]
    for command in commands:
        # first select the device
        t_device = actuators[command.id]
        channel = getattr(t_device, command.property)
        # then apply it to all
        yield from bps.mv(
            dev_name,
            str(command.id),
            ch_name,
            str(command.property),
            ch_val,
            command.value,
            channel,
            command.value,
        )
        # TODO: revisit how to address reading detectors
        #       also in the command language
        # read all devices
        yield from bps.wait()  # << required
        # optional: give hardware / twin time
        if wait_before_read > 0:
            yield from bps.sleep(wait_before_read)
        yield from bps.repeat(
            functools.partial(bps.trigger_and_read, all_dev), num=num_readings
        )


def extract_current_state_probe_commands(
    commands: Sequence[ReadCommand],
) -> Sequence[ReadCommand]:
    def extract_if_needed(cmd: ReadCommand) -> Union[ReadCommand, None]:
        flag, prop = delta_property(cmd.property)
        if flag:
            return ReadCommand(id=cmd.id, property=prop)

    tmp = [extract_if_needed(cmd) for cmd in commands]
    return [t for t in tmp if t is not None]


def rework_delta_commands(
    *,
    commands: Sequence[Command],
    cache: StateCache,
) -> Sequence[Command]:
    def convert(cmd: Command) -> Command:
        flag, prop = delta_property(cmd.property)
        if not flag:
            return cmd
        ref = cache.get(ReadCommand(id=cmd.id, property=prop))
        assert ref is not None
        ncmd = Command(
            id=cmd.id,
            property=prop,
            value=cmd.value + ref,
            behaviour_on_error=cmd.behaviour_on_error,
        )
        return ncmd

    return [convert(cmd) for cmd in commands]


def retrieve_reference_state_plan(
    commands: Sequence[ReadCommand],
    detectors: Sequence[Device],
    actuators: Dict[str, Device],
    cache: StateCache,
):
    # filter out only the required detectors ...
    # Todo: reference also needed for the detectors?
    all_dev = [getattr(actuators[rcmd.id], rcmd.property) for rcmd in commands]
    ref_stream = "reference-state"
    # how to handle that some data need an extra read ?
    ref_data = yield from bps.trigger_and_read(all_dev, name=ref_stream)
    for rcmd in commands:
        # Todo: current approach to be json compatible
        needed_data_tag = f"{as_json_compatible_device_id(rcmd.id)}-{rcmd.property}"
        data_for_dev = ref_data.get(needed_data_tag)
        assert data_for_dev is not None, f"Could not find data {needed_data_tag}, only know {list(ref_data)}"
        value = data_for_dev.get("value")
        cache.set(rcmd, value)


def commands_plan(
    commands: Sequence[TransactionCommand],
    detectors: Sequence[Device],
    actuators: Dict[str, Device],
    info_signals: Dict[str, Signal],
    cache: StateCache,
    n_readings: int,
    wait_after_set: float,
    wait_between_samples: float,
):
    """

    Inner plan for :func:`commands_execution_plan`

    Todo:
        Implement stop, ignore, rollback etc
        Device replace by ophyd_async.Settable
        info_signals as dataclass?
    """
    all_dev = list(info_signals.values()) + list(detectors) + list(actuators.values())
    dev_name = info_signals["device_name"]
    ch_name = info_signals["channel_name"]
    ch_val = info_signals["channel_value"]
    # make cache read all commands

    for tc in commands:
        # only prepared for a single device currently
        (command,) = tc.transaction
        flag, prop = delta_property(command.property)
        if flag:
            rcmd = ReadCommand(id=command.id, property=prop)
            ref = cache.get(rcmd)
            keys = cache.keys()
            assert ref is not None, f"No reference value for {rcmd}: known keys {keys}"
            value = command.value + ref
        else:
            value = command.value
        # first select the device
        t_device = actuators[command.id]
        channel = getattr(t_device, prop)
        # then apply it to all
        yield from bps.mv(
            dev_name,
            str(command.id),
            ch_name,
            str(command.property),
            ch_val,
            command.value,
            channel,
            value,
        )
        # TODO: revisit how to address reading detectors
        #       also in the command language
        # read all devices
        yield from bps.wait()
        # optional: give hardware / twin time
        yield from bps.sleep(wait_after_set)
        yield from bps.repeat(
            functools.partial(bps.trigger_and_read, all_dev),
            num=n_readings,
            delay=wait_between_samples
        )


def commands_execution_plan(
    *,
    commands: Sequence[TransactionCommand],
    detectors: Sequence[Device],
    actuators: Dict[str, Device],
    info_signals: Dict[str, Signal],
    cache: StateCache,
    wait_after_set: float = 1.0,
    wait_between_samples: float = 1.0,
    n_readings: int,
    retrieve_reference: bool = False,
    md: None,
):
    """Translate commands to bluesky run-engine messages"""
    _md = md or dict()
    # CommandSequence nor Commands is json seriazable ....
    _md.update(dict(commands=[asdict(cmd) for cmd in commands]))

    @bpp.stage_decorator(list(detectors) + list(actuators.values()))
    @bpp.run_decorator(md=_md)
    def inner():
        # first ... load cache with reference state
        if retrieve_reference:
            yield from retrieve_reference_state_plan(
                commands=list(
                    set(
                        extract_current_state_probe_commands(
                            itertools.chain(*[tc.transaction for tc in commands])
                        )
                    )
                ),
                detectors=detectors,
                actuators=actuators,
                cache=cache,
            )
        r = yield from commands_plan(
            commands=commands,
            detectors=detectors,
            actuators=actuators,
            info_signals=info_signals,
            n_readings=n_readings,
            wait_after_set = wait_after_set,
            wait_between_samples = wait_between_samples,
            cache=cache,
        )
        return r

    r = yield from inner()
    return r


__all__ = [
    "simple_command_sequence_execution_plan",
    "transactional_commands_sequence_execution_plan",
    "transactional_actuator_commands_plan",
]
