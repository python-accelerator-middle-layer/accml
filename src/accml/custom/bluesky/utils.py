import asyncio
import itertools
from typing import Sequence, Union

from accml_lib.core.model.utils.tango_resource_locator import TangoResourceLocator
from dt4acc_lib.model.utils.command import TransactionCommand


def extract_device_identifiers(commands_collection: Sequence[TransactionCommand]) -> Sequence[str]:
    return list(itertools.chain(*[[cmd.id for cmd in tc.transaction] for tc in commands_collection]))


async def connect_to_devices(devices, timeout=5.0):
    """
    """
    for dev in devices:
        assert dev is not None, "Sanity check, all devices must not be None"

    return await asyncio.gather(
        *[dev.connect(timeout=timeout) for dev in devices]
    )


def as_json_compatible_device_id(id_: Union[str, TangoResourceLocator]) -> str:
    """
    Return a JSON-compatible identifier.

    - If `id_` is a string, it is assumed to already be JSON-compatible
      and is returned unchanged.
    - If `id_` is a TangoResourceLocator, its `json_compatible()` form
      is returned.

    Any other type is considered a programming error.
    """
    if isinstance(id_, str):
        return id_
    if isinstance(id_, TangoResourceLocator):
        return id_.json_compatible()
    raise TypeError(
        f"Expected str or TangoResourceLocator, got {type(id_).__name__}"
    )
