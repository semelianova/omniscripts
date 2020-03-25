import argparse
import glob
import os
import random
import re
import subprocess
from datetime import datetime

import hiyapyco
from braceexpand import braceexpand


def str_arg_to_bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "True", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "False", "f", "n", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError("Cannot recognize boolean value.")


def combinate_requirements(ibis, ci, res):
    merged_yaml = hiyapyco.load([ibis, ci], method=hiyapyco.METHOD_MERGE)
    with open(res, "w") as f_res:
        hiyapyco.dump(merged_yaml, stream=f_res)


def execute_process(cmdline, cwd=None, shell=False, daemon=False, print_output=True):
    "Execute cmdline in user-defined directory by creating separated process"
    try:
        print("CMD: ", " ".join(cmdline))
        output = ""
        process = subprocess.Popen(
            cmdline,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=shell,
        )
        if not daemon:
            output = process.communicate()[0].strip().decode()
            if re.findall(r"\d fail", output) or re.findall(r"[e,E]rror", output):
                process.returncode = 1
            elif print_output:
                print(output)
        if process.returncode != 0 and process.returncode is not None:
            raise Exception(f"Command returned {process.returncode}. \n{output}")
        return process, output
    except OSError as err:
        print("Failed to start", cmdline, err)


def convert_type_ibis2pandas(types):
    types = ["string_" if (x == "string") else x for x in types]
    return types


def import_pandas_into_module_namespace(
    namespace, mode, ray_tmpdir=None, ray_memory=None
):
    if mode == "Pandas":
        print("Running on Pandas")
        import pandas as pd
    else:
        if mode == "Modin_on_ray":
            import ray

            if not ray_tmpdir:
                ray_tmpdir = "/tmp"
            if not ray_memory:
                ray_memory = 200 * 1024 * 1024 * 1024
            ray.init(
                huge_pages=False,
                plasma_directory=ray_tmpdir,
                memory=ray_memory,
                object_store_memory=ray_memory,
            )
            os.environ["MODIN_ENGINE"] = "ray"
            print(
                "Running on Ray on Pandas with tmp directory",
                ray_tmpdir,
                "and memory",
                ray_memory,
            )
        elif mode == "Modin_on_dask":
            os.environ["MODIN_ENGINE"] = "dask"
            print("Running on Dask")
        else:
            raise ValueError(f"Unknown pandas mode {mode}")
        import modin.pandas as pd
    namespace["pd"] = pd


def equal_dfs(ibis_dfs, pandas_dfs):
    for ibis_df, pandas_df in zip(ibis_dfs, pandas_dfs):
        if not ibis_df.equals(pandas_df):
            return False
    return True


def get_percentage(error_message):
    # parsing message like: lalalalal values are different (xxxxx%) lalalalal
    return float(error_message.split("values are different ")[1].split("%)")[0][1:])


def compare_dataframes(ibis_dfs, pandas_dfs):
    import pandas as pd

    prepared_dfs = []
    # in percentage - 0.05 %
    max_error = 0.05

    assert len(ibis_dfs) == len(pandas_dfs)

    # preparing step
    for idx in range(len(ibis_dfs)):
        # prepare ibis part
        ibis_dfs[idx].sort_values(by="id", axis=0, inplace=True)
        ibis_dfs[idx].reset_index(drop=True, inplace=True)
        ibis_dfs[idx].drop(["id"], axis=1, inplace=True)
        # prepare pandas part
        pandas_dfs[idx].reset_index(drop=True, inplace=True)

    # fast check
    if equal_dfs(ibis_dfs, pandas_dfs):
        print("dataframes are equal")
        return

    # comparing step
    for ibis_df, pandas_df in zip(ibis_dfs, pandas_dfs):
        assert ibis_df.shape == pandas_df.shape
        for column_name in ibis_df.columns:
            try:
                pd.testing.assert_frame_equal(
                    ibis_df[[column_name]],
                    pandas_df[[column_name]],
                    check_less_precise=2,
                    check_dtype=False,
                )
            except AssertionError as assert_err:
                if str(ibis_df.dtypes[column_name]).startswith("float"):
                    try:
                        current_error = get_percentage(str(assert_err))
                        if current_error > max_error:
                            print(
                                f"Max acceptable difference: {max_error}%; current difference: {current_error}%"
                            )
                            raise assert_err
                    # for catch exceptions from `get_percentage`
                    except Exception:
                        raise assert_err
                else:
                    raise assert_err

    print("dataframes are equal")


def load_data_pandas(
    filename,
    columns_names=None,
    columns_types=None,
    header=None,
    nrows=None,
    use_gzip=False,
    parse_dates=None,
    pd=None,
):
    if not pd:
        import_pandas_into_module_namespace(namespace=main.__globals__, mode="Pandas")
    types = None
    if columns_types:
        types = {columns_names[i]: columns_types[i] for i in range(len(columns_names))}
    return pd.read_csv(
        filename,
        names=columns_names,
        nrows=nrows,
        header=header,
        dtype=types,
        compression="gzip" if use_gzip else None,
        parse_dates=parse_dates,
    )


def files_names_from_pattern(filename):
    data_files_names = list(braceexpand(filename))
    data_files_names = sorted([x for f in data_files_names for x in glob.glob(f)])
    return data_files_names


def print_times(times, backend=None):
    if backend:
        print(f"{backend} times:")
    for time_name, time in times.items():
        print("{} = {:.5f} s".format(time_name, time))


def int_random(least, greatest, seed=True):
    if seed:
        random.seed(datetime.now())
    return random.randint(least, greatest)


def random_if_default(value, least, greater, default=-1):
    if value == default:
        return int_random(least, greater)
    return value

def mse(y_test, y_pred):
    return ((y_test - y_pred) ** 2).mean()


def cod(y_test, y_pred):
    y_bar = y_test.mean()
    total = ((y_test - y_bar) ** 2).sum()
    residuals = ((y_test - y_pred) ** 2).sum()
    return 1 - (residuals / total)
