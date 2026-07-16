"""
Todo:
    all the grouping code should not be here
    the bpm device should put data into a data model
    then here the data model would only be used ....
"""
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Sequence, Literal

import imageio.v2 as imageio
import matplotlib
import logging

from at.tracking import particles
from bluesky.protocols import Reading

logging.basicConfig(level=logging.WARNING)

import asyncio
import numpy as np

from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop

from dt4acc.custom_facility.als.gpt.dt4acc_bootstrap import load_managers
from dt4acc.custom_facility.als.ophyd_async_devices_setup import setup
from dt4acc_lib.model.output.track import ParticleState
from matplotlib import pyplot as plt
import at

# need to use 'macosx' on MAC
# matplotlib.use('qt5cairo')
matplotlib.use("QtAgg")
logger = logging.getLogger("accml_test")

app = QApplication([])

writer = imageio.get_writer("output.mp4", fps=30)

Branch = Literal["upper", "lower"]

@dataclass(frozen=True)
class TwissParametersForPlane:
    beta: float
    alpha: float


@dataclass(frozen=True)
class MomentumSpaceForPlane:
    twiss: TwissParametersForPlane
    emittance: float


@dataclass(frozen=True)
class MomentumSpace:
    x: MomentumSpaceForPlane
    y: MomentumSpaceForPlane

    def sigma_matrix(self):
        return at.sigma_matrix(
            betax=self.x.twiss.beta,
            alphax=self.x.twiss.alpha,
            emitx=self.x.emittance,
            betay=self.y.twiss.beta,
            alphay=self.y.twiss.alpha,
            emity = self.y.emittance,
        )

def get_branch_as_flag(branch: Branch) -> Literal[-1, 1]:
    if branch == "upper":
        return 1
    if branch == "lower":
        return -1
    raise ValueError(f"Invalid branch: {branch!r}")


# Todo: replace it with something realsitic for injection
space = MomentumSpace(
    x=MomentumSpaceForPlane(
        twiss=TwissParametersForPlane(
            beta=20.7125,
            alpha=-0.000443243,
        ),
        emittance=1e-5,
    ),
    y=MomentumSpaceForPlane(
        twiss=TwissParametersForPlane(
            beta=1.71272,
            alpha=-0.000503292,
        ),
        emittance=1e-5,
    ),
)
# BESSY II
space = MomentumSpace(
    x=MomentumSpaceForPlane(
        twiss=TwissParametersForPlane(
            beta=17.03,
            alpha=-0.04,
        ),
        emittance=6.5e-9,
    ),
    y=MomentumSpaceForPlane(
        twiss=TwissParametersForPlane(
            beta=4.16,
            alpha=-0.32,
        ),
        emittance=6.5e-10,
    ),
)



def create_start_vec(
    xm: float,
    space: MomentumSpace
) -> ParticleState:
    particles = at.beam(100, space.sigma_matrix())
    # only take the first 10 particles which are largely away
    r = []
    for data in particles.transpose():
        data[0] +=xm
        p = ParticleState.from_sequence(data)
        r.append(p)
        # if p.x > 10e-3:
        #     r.append(p)
        # if len(r) > 10:
        #     return r
    # else:
    #     raise ValueError("Did not find enough particles")
    return r


rng = np.random.default_rng()


def create_start_vector():
    sigma_x = sigma_y  = 1e-5

async def main():

    x_mean = np.linspace(16, 17.8, num=10) * 1e-3
    start_vecs = [create_start_vec(xm, space) for xm in x_mean]
    yp, lm, ts, epics_vars = load_managers()
    devices = setup()


    devices = setup(prefix=None)
    tbt_bpms = devices.get("tbt_bpms")
    # Need to find out why these don't have data
    excluded_bpms = [
        "SR01C:BPM2",
        "SR01C:BPM6",
        "SR03C:BPM2",
        "SR03C:BPM7",
        "SR04C:BPM1",
        "SR04C:BPM2",
        "SR04C:BPM7",
        "SR04C:BPM8",
        "SR06C:BPM1",
        "SR06C:BPM2",
        "SR06C:BPM7",
        "SR06C:BPM8",
        "SR07C:BPM1",
        "SR07C:BPM2",
        "SR07C:BPM7",
        "SR07C:BPM8",
        "SR11C:BPM1",
        "SR11C:BPM2",
        "SR11C:BPM7",
        "SR11C:BPM8",
    ]

    tbt_bpms = {
        bpm_name: dev
        for bpm_name, dev in tbt_bpms.items()
        if bpm_name not in excluded_bpms
    }
    # Interface to configure how it runs
    turn_by_turn = devices.get("turn_by_turn")
    await turn_by_turn.connect()

    await asyncio.gather(*[bpm.connect() for bpm in tbt_bpms.values()])

    # I should rather check if these are really triggerable
    triggerable_devices = list(tbt_bpms.values())
    all_devices = triggerable_devices + [turn_by_turn]
    d = await asyncio.gather(*[dev.describe() for dev in all_devices])
    r = await asyncio.gather(*[dev.read() for dev in all_devices])

    # NB:
    #   if you want to read back your data with bluesky databroker
    #   only change this value at the beginning!
    await turn_by_turn.n_turns.set(200)


    fig, axes = plt.subplots(3, 1, sharex=True)


    for run_id, vecs in enumerate(start_vecs):
        # Adhering to bluesky protocol: trigger shall be called if
        # one wants to "trigger" for new data (or wait for it)
        await turn_by_turn.start_vec.set(np.concatenate([v.as_array() for v in vecs]))
        # don't forget to trigger turn by turn data calculation
        # and integer should be good, better to use a meaningful one
        await turn_by_turn.run.set(run_id)
        # need to launch that already ... so it gets the data
        # when they arrive
        future_bpm_tbt_ready = asyncio.gather(*[dev.trigger() for dev in triggerable_devices])
        if run_id > 0:
            # some time for to inspect the data
            # wait here: the twin can calculate in parallel
            for i in range(30 * 5):
                # 30 frames per second ...
                await asyncio.sleep(1/30.)
                # so that one can see for a few seconds what's there
                frame = np.asarray(fig.canvas.buffer_rgba())
                writer.append_data(frame)
        await future_bpm_tbt_ready
        data = await asyncio.gather(*[dev.read() for dev in all_devices])
        data = all_data_in_one_dict(data)
        non_bpm_data, bpm_data = group_data(data)
        future = asyncio.get_running_loop().create_future()

        def on_draw(event):
            if not future.done():
                future.set_result(None)

        cid = fig.canvas.mpl_connect("draw_event", on_draw)

        print(f"Data for run_id {run_id}...", end="")
        await plot_bpm_data(fig, axes, f"x_m at {x_mean[run_id] * 1000:.3f} mm", bpm_data)
        fig.canvas.draw_idle()
        fig.canvas.flush_events()
        await future
        fig.canvas.mpl_disconnect(cid)
        print("done")


def all_data_in_one_dict(data: Sequence[Dict[str, Reading]]) -> Dict[str, Reading]:
    """
    Todo: does bluesky provide that ?
    """
    d = {}
    for elem in data:
        for key, value in elem.items():
            if d.get(key, None) is None:
                d[key] = value
            else:
                logger.warning(f"Duplicate key {key} in data, ignoring this occurence")
    return d


def group_data(
    data: Dict[str, Reading]
) -> (Dict[str, Reading], Dict[str, Dict[str, Reading]]):
    bpm_data = {}
    non_bpm_data = {}
    for k, v in data.items():
        if "BPM" in k:
            bpm_data[k] = v
        else:
            non_bpm_data[k] = v
    bpm_data = group_bpm_data(bpm_data)
    return non_bpm_data, bpm_data


def group_bpm_data(data: Sequence[Reading]) -> Dict[str, Dict[str, Reading]]:
    d = defaultdict(dict)
    for k, v in data.items():
        bpm_name, coor = map(str, k.split("-"))
        assert coor in ["x", "y", "sum"]
        d[bpm_name][coor] = v
    r = dict(d)
    for v in r.values():
        # check that these entries exist
        v["x"]
        v["y"]
        v["sum"]
    return r


async def plot_bpm_data(fig, axes, title, data):
    ax_x, ax_y, ax_sum = axes
    for ax in axes:
        ax.clear()
    for bpm_name, d_for_bpm in data.items():
        ax_x.set_title(title)
        turns = np.arange(len(d_for_bpm["x"]["value"]))
        ax_x.plot(turns, d_for_bpm["x"]["value"], label=bpm_name)
        ax_y.plot(turns, d_for_bpm["y"]["value"], label=bpm_name)
        ax_sum.plot(turns, d_for_bpm["sum"]["value"], label=bpm_name)
        # give everything else a chance to run
        fig.canvas.draw()
        frame = np.asarray(fig.canvas.buffer_rgba())
        writer.append_data(frame)
        await asyncio.sleep(0)
    ax_x, ax_y, ax_sum = axes
    ax_x.set_ylabel("x [m]")
    ax_y.set_ylabel("y [m]")
    ax_sum.set_ylabel("sum [rel]")
    ax_sum.set_xlabel("turn")
    del ax_x, ax_y, ax_sum
    # ax_x.legend()
    # ax_y.legend()
    # ax_sum.legend()


if __name__ == "__main__":
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    plt.ion()
    try:
        with loop:
            loop.run_until_complete(main())
        writer.close()
    except Exception as e:
        logger.error(f"Failed to run {__file__}.main: {e}")
        print("Close plot for full backtrace")
        plt.ioff()
        plt.show()
        raise e
    else:
        print("Close plot to stop program")
        plt.ioff()
        plt.show()
