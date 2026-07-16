import pprint

import numpy as np
from databroker import catalog
import xarray as xr


def rename_added_dimension_to_turn_by_turn(data: xr.DataArray, turn_by_turn_coordinate) -> xr.DataArray:
    time_dim, second_dim = data.dims
    assert time_dim == "time"
    # databroker load uses to give this name to the variable
    assert second_dim.startswith("dim_")
    ndata = data.rename({second_dim: "turn"}).assign_coords(dict(turn=turn_by_turn_coordinate))
    return ndata


def convert_start_vec(data: xr.DataArray) -> xr.DataArray:
    time_dim, second_dim = data.dims
    assert time_dim == "time"
    assert second_dim.startswith("dim_")
    n_sample, n_elems = data.shape
    assert n_elems % 6 == 0
    n_particles = n_elems // 6
    reshaped = xr.DataArray(
        data.data.reshape(n_sample, n_particles, 6),
        dims=("time", "particles", "state"),
        coords=dict(
            time=data.time,
            particles=np.arange(n_particles),
            state=["x", "px", "y", "py", "delta", "ct"],
        )
    )
    return reshaped


def treat_dims_for_turn_by_turn(data: xr.Dataset, token: str) -> xr.Dataset:
    """uses just heuristics

    Todo:
        review if data should be better provided in a data model
    """
    var_names = [var_name for var_name in data.variables.keys() if token in var_name]
    # I assume that all bpms recorded the same number of turn by turns
    # for missing turns I assume that nan was posted
    ref_shape = data[var_names[0]].shape
    assert all([data[var_name].shape == ref_shape for var_name in var_names[1:]]) == True

    _, n_turns = ref_shape
    t_turn = np.arange(n_turns)
    reworked_vars = {
        name:
        rename_added_dimension_to_turn_by_turn(data[name], t_turn)
        for name in var_names
    }

    not_transformed_variables = set(data.variables.keys()).difference(var_names)
    ndata = xr.Dataset(
        {
            **{name: data[name] for name in not_transformed_variables},
            **reworked_vars
        }
    )
    return ndata



def main():
    db = catalog["heavy_local"]
    data = db['bb9047c1-185f-4a52-b752-b05ac9b83cb1']
    data = db['b1257d75-cc59-4d9a-a531-822017ff629c']
    data = db['9680171c-fa21-4b7c-8314-32ea39764f67']
    data = db['d4d9ebfc-40ed-4f29-96e6-355497c4b526']
    r = data.primary.read()
    nr = treat_dims_for_turn_by_turn(r, "BPM")
    nr["tbt-start_vec-reshaped"] = convert_start_vec(r["tbt-start_vec"])
    pprint.pprint(nr, compact=True)
    pass

if __name__ == "__main__":
    main()