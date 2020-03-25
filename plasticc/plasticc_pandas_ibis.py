import os
import sys
import traceback
import warnings
from collections import OrderedDict
from functools import partial
from timeit import default_timer as timer

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
import xgboost as xgb

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from utils import (
    compare_dataframes,
    import_pandas_into_module_namespace,
    print_times,
)


def ravel_column_names(cols):
    d0 = cols.get_level_values(0)
    d1 = cols.get_level_values(1)
    return ["%s_%s" % (i, j) for i, j in zip(d0, d1)]


def skew_workaround(table):
    n = table["flux_count"]
    m = table["flux_mean"]
    s1 = table["flux_sum1"]
    s2 = table["flux_sum2"]
    s3 = table["flux_sum3"]

    # change column name: 'skew' -> 'flux_skew'
    skew = (
        n
        * (n - 1).sqrt()
        / (n - 2)
        * (s3 - 3 * m * s2 + 2 * m * m * s1)
        / (s2 - m * s1).pow(1.5)
    ).name("flux_skew")
    table = table.mutate(skew)

    return table


def etl_cpu_ibis(table, table_meta, etl_times):
    t_etl_start = timer()

    t0 = timer()
    table = table.mutate(flux_ratio_sq=(table["flux"] / table["flux_err"]) ** 2)
    table = table.mutate(flux_by_flux_ratio_sq=table["flux"] * table["flux_ratio_sq"])
    etl_times["t_arithm"] += timer() - t0

    aggs = [
        table.passband.mean().name("passband_mean"),
        table.flux.min().name("flux_min"),
        table.flux.max().name("flux_max"),
        table.flux.mean().name("flux_mean"),
        table.flux_err.min().name("flux_err_min"),
        table.flux_err.max().name("flux_err_max"),
        table.flux_err.mean().name("flux_err_mean"),
        table.detected.mean().name("detected_mean"),
        table.mjd.min().name("mjd_min"),
        table.mjd.max().name("mjd_max"),
        table.flux_ratio_sq.sum().name("flux_ratio_sq_sum"),
        table.flux_by_flux_ratio_sq.sum().name("flux_by_flux_ratio_sq_sum"),
        # for skew computation - should be dropped after
        table.flux.count().name("flux_count"),
        table.flux.sum().name("flux_sum1"),
        (table["flux"] ** 2).sum().name("flux_sum2"),
        (table["flux"] ** 3).sum().name("flux_sum3"),
    ]

    t0 = timer()
    table = table.groupby("object_id").aggregate(aggs)
    etl_times["t_groupby_agg"] += timer() - t0

    t0 = timer()
    table = table.mutate(flux_diff=table["flux_max"] - table["flux_min"])
    table = table.mutate(flux_dif2=table["flux_diff"] / table["flux_mean"])
    table = table.mutate(
        flux_w_mean=table["flux_by_flux_ratio_sq_sum"] / table["flux_ratio_sq_sum"]
    )
    table = table.mutate(flux_dif3=table["flux_diff"] / table["flux_w_mean"])
    table = table.mutate(mjd_diff=table["mjd_max"] - table["mjd_min"])
    # skew compute
    table = skew_workaround(table)
    etl_times["t_arithm"] += timer() - t0

    t0 = timer()
    table = table.drop(
        ["mjd_max", "mjd_min", "flux_count", "flux_sum1", "flux_sum2", "flux_sum3"]
    )
    etl_times["t_drop"] += timer() - t0

    t0 = timer()
    table_meta = table_meta.drop(["ra", "decl", "gal_l", "gal_b"])
    etl_times["t_drop"] += timer() - t0

    t0 = timer()
    # df_meta = df_meta.merge(agg_df, on="object_id", how="left")
    # try to workaround
    table_meta = table_meta.join(table, ["object_id"], how="left")[
        table_meta,
        table.passband_mean,
        table.flux_min,
        table.flux_max,
        table.flux_mean,
        table.flux_skew,
        table.flux_err_min,
        table.flux_err_max,
        table.flux_err_mean,
        table.detected_mean,
        table.flux_ratio_sq_sum,
        table.flux_by_flux_ratio_sq_sum,
        table.flux_diff,
        table.flux_dif2,
        table.flux_w_mean,
        table.flux_dif3,
        table.mjd_diff,
    ]
    etl_times["t_merge"] += timer() - t0

    df = table_meta.execute()

    etl_times["t_etl"] += timer() - t_etl_start

    return df


def etl_cpu_pandas(df, df_meta, etl_times):
    t_etl_start = timer()

    t0 = timer()
    df["flux_ratio_sq"] = np.power(df["flux"] / df["flux_err"], 2.0)
    df["flux_by_flux_ratio_sq"] = df["flux"] * df["flux_ratio_sq"]
    etl_times["t_arithm"] += timer() - t0

    aggs = {
        "passband": ["mean"],
        "flux": ["min", "max", "mean", "skew"],
        "flux_err": ["min", "max", "mean"],
        "detected": ["mean"],
        "mjd": ["max", "min"],
        "flux_ratio_sq": ["sum"],
        "flux_by_flux_ratio_sq": ["sum"],
    }
    t0 = timer()
    agg_df = df.groupby("object_id").agg(aggs)
    etl_times["t_groupby_agg"] += timer() - t0

    agg_df.columns = ravel_column_names(agg_df.columns)

    t0 = timer()
    agg_df["flux_diff"] = agg_df["flux_max"] - agg_df["flux_min"]
    agg_df["flux_dif2"] = agg_df["flux_diff"] / agg_df["flux_mean"]
    agg_df["flux_w_mean"] = (
        agg_df["flux_by_flux_ratio_sq_sum"] / agg_df["flux_ratio_sq_sum"]
    )
    agg_df["flux_dif3"] = agg_df["flux_diff"] / agg_df["flux_w_mean"]
    agg_df["mjd_diff"] = agg_df["mjd_max"] - agg_df["mjd_min"]
    etl_times["t_arithm"] += timer() - t0

    t0 = timer()
    agg_df = agg_df.drop(["mjd_max", "mjd_min"], axis=1)
    etl_times["t_drop"] += timer() - t0

    agg_df = agg_df.reset_index()

    t0 = timer()
    df_meta = df_meta.drop(["ra", "decl", "gal_l", "gal_b"], axis=1)
    etl_times["t_drop"] += timer() - t0

    t0 = timer()
    df_meta = df_meta.merge(agg_df, on="object_id", how="left")
    etl_times["t_merge"] += timer() - t0

    etl_times["t_etl"] += timer() - t_etl_start

    return df_meta


def load_data_ibis(
    dataset_path,
    database_name,
    omnisci_server_worker,
    delete_old_database,
    create_new_table,
    connection_func,
    skip_rows,
    validation,
    dtypes,
    meta_dtypes,
):
    connection_func()
    omnisci_server_worker.create_database(
        database_name, delete_if_exists=delete_old_database
    )
    connection_func()

    t_import_pandas, t_import_ibis = 0.0, 0.0

    # Create tables and import data
    if create_new_table:
        # create table #1
        training_file = "%s/training_set.csv" % dataset_path
        t_import_pandas_1, t_import_ibis_1 = omnisci_server_worker.import_data_by_ibis(
            table_name="training",
            data_files_names=training_file,
            files_limit=1,
            columns_names=list(dtypes.keys()),
            columns_types=list(dtypes.values()),
            header=0,
            nrows=None,
            compression_type=None,
            validation=validation,
        )

        # create table #2
        test_file = "%s/test_set.csv" % dataset_path
        t_import_pandas_2, t_import_ibis_2 = omnisci_server_worker.import_data_by_ibis(
            table_name="test",
            data_files_names=test_file,
            files_limit=1,
            columns_names=list(dtypes.keys()),
            columns_types=list(dtypes.values()),
            header=0,
            nrows=None,
            compression_type=None,
            skiprows=skip_rows,
            validation=validation,
        )

        # create table #3
        training_meta_file = "%s/training_set_metadata.csv" % dataset_path
        t_import_pandas_3, t_import_ibis_3 = omnisci_server_worker.import_data_by_ibis(
            table_name="training_meta",
            data_files_names=training_meta_file,
            files_limit=1,
            columns_names=list(meta_dtypes.keys()),
            columns_types=list(meta_dtypes.values()),
            header=0,
            nrows=None,
            compression_type=None,
            validation=validation,
        )

        target = meta_dtypes.pop("target")

        # create table #4
        test_meta_file = "%s/test_set_metadata.csv" % dataset_path
        t_import_pandas_4, t_import_ibis_4 = omnisci_server_worker.import_data_by_ibis(
            table_name="test_meta",
            data_files_names=test_meta_file,
            files_limit=1,
            columns_names=list(meta_dtypes.keys()),
            columns_types=list(meta_dtypes.values()),
            header=0,
            nrows=None,
            compression_type=None,
            validation=validation,
        )
        meta_dtypes["target"] = target

        t_import_pandas = (
            t_import_pandas_1
            + t_import_pandas_2
            + t_import_pandas_3
            + t_import_pandas_4
        )
        t_import_ibis = (
            t_import_ibis_1 + t_import_ibis_2 + t_import_ibis_3 + t_import_ibis_4
        )
        print(f"import times: pandas - {t_import_pandas}s, ibis - {t_import_ibis}s")

    # Second connection - this is ibis's ipc connection for DML
    conn = connection_func()
    db = conn.database(database_name)

    training_table = db.table("training")
    test_table = db.table("test")

    training_meta_table = db.table("training_meta")
    test_meta_table = db.table("test_meta")

    return (
        training_table,
        training_meta_table,
        test_table,
        test_meta_table,
        t_import_pandas + t_import_ibis,
    )


def load_data_pandas(dataset_path, skip_rows, dtypes, meta_dtypes):
    train = pd.read_csv("%s/training_set.csv" % dataset_path, dtype=dtypes)
    test = pd.read_csv(
        # this should be replaced on test_set_skiprows.csv
        "%s/test_set.csv" % dataset_path,
        names=list(dtypes.keys()),
        dtype=dtypes,
        skiprows=skip_rows,
    )

    train_meta = pd.read_csv(
        "%s/training_set_metadata.csv" % dataset_path, dtype=meta_dtypes
    )
    target = meta_dtypes.pop("target")
    test_meta = pd.read_csv("%s/test_set_metadata.csv" % dataset_path, dtype=meta_dtypes)
    meta_dtypes["target"] = target

    return train, train_meta, test, test_meta


def split_step(train_final, test_final, etl_times):
    t_etl_start = timer()

    t0 = timer()
    X = train_final.drop(["object_id", "target"], axis=1).values
    Xt = test_final.drop(["object_id"], axis=1).values
    etl_times["t_drop"] += timer() - t0

    y = train_final["target"]
    assert X.shape[1] == Xt.shape[1]
    classes = sorted(y.unique())

    class_weights = {c: 1 for c in classes}
    class_weights.update({c: 2 for c in [64, 15]})

    lbl = LabelEncoder()
    y = lbl.fit_transform(y)
    # print(lbl.classes_)

    t0 = timer()
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.1, stratify=y, random_state=126
    )
    etl_times["t_train_test_split"] += timer() - t0

    etl_times["t_etl"] += timer() - t_etl_start

    return (X_train, y_train, X_test, y_test, Xt, classes, class_weights), etl_times


def etl_all_ibis(
    dataset_path,
    database_name,
    omnisci_server_worker,
    delete_old_database,
    create_new_table,
    connection_func,
    skip_rows,
    validation,
    dtypes,
    meta_dtypes,
):
    print("ibis version")
    etl_times = {
        "t_readcsv": 0.0,
        "t_groupby_agg": 0.0,
        "t_merge": 0.0,
        "t_arithm": 0.0,
        "t_drop": 0.0,
        "t_train_test_split": 0.0,
        "t_etl": 0.0,
    }

    train, train_meta, test, test_meta, etl_times["t_readcsv"] = load_data_ibis(
        dataset_path=dataset_path,
        database_name=database_name,
        omnisci_server_worker=omnisci_server_worker,
        delete_old_database=delete_old_database,
        create_new_table=create_new_table,
        connection_func=connection_func,
        skip_rows=skip_rows,
        validation=validation,
        dtypes=dtypes,
        meta_dtypes=meta_dtypes,
    )

    # update etl_times
    train_final = etl_cpu_ibis(train, train_meta, etl_times)
    test_final = etl_cpu_ibis(test, test_meta, etl_times)

    return train_final, test_final, etl_times


def etl_all_pandas(dataset_path, skip_rows, dtypes, meta_dtypes):
    print("pandas version")
    etl_times = {
        "t_readcsv": 0.0,
        "t_groupby_agg": 0.0,
        "t_merge": 0.0,
        "t_arithm": 0.0,
        "t_drop": 0.0,
        "t_train_test_split": 0.0,
        "t_etl": 0.0,
    }

    t0 = timer()
    train, train_meta, test, test_meta = load_data_pandas(
        dataset_path=dataset_path,
        skip_rows=skip_rows,
        dtypes=dtypes,
        meta_dtypes=meta_dtypes,
    )
    etl_times["t_readcsv"] += timer() - t0

    # update etl_times
    train_final = etl_cpu_pandas(train, train_meta, etl_times)
    test_final = etl_cpu_pandas(test, test_meta, etl_times)

    return train_final, test_final, etl_times


def multi_weighted_logloss(y_true, y_preds, classes, class_weights):
    """
    refactor from
    @author olivier https://www.kaggle.com/ogrellier
    multi logloss for PLAsTiCC challenge
    """
    y_p = y_preds.reshape(y_true.shape[0], len(classes), order="F")
    y_ohe = pd.get_dummies(y_true)
    y_p = np.clip(a=y_p, a_min=1e-15, a_max=1 - 1e-15)
    y_p_log = np.log(y_p)
    y_log_ones = np.sum(y_ohe.values * y_p_log, axis=0)
    nb_pos = y_ohe.sum(axis=0).values.astype(float)
    class_arr = np.array([class_weights[k] for k in sorted(class_weights.keys())])
    y_w = y_log_ones * class_arr / nb_pos

    loss = -np.sum(y_w) / np.sum(class_arr)
    return loss


def xgb_multi_weighted_logloss(y_predicted, y_true, classes, class_weights):
    loss = multi_weighted_logloss(
        y_true.get_label(), y_predicted, classes, class_weights
    )
    return "wloss", loss


def ml(ml_data):
    # unpacking
    X_train, y_train, X_test, y_test, Xt, classes, class_weights = ml_data

    ml_times = {
        "t_dmatrix": 0.0,
        "t_training": 0.0,
        "t_infer": 0.0,
        "t_ml": 0.0,
    }

    cpu_params = {
        "objective": "multi:softprob",
        "tree_method": "hist",
        "nthread": 16,
        "num_class": 14,
        "max_depth": 7,
        "silent": 1,
        "subsample": 0.7,
        "colsample_bytree": 0.7,
    }

    func_loss = partial(
        xgb_multi_weighted_logloss, classes=classes, class_weights=class_weights
    )

    t_ml_start = timer()
    dtrain = xgb.DMatrix(data=X_train, label=y_train)
    dvalid = xgb.DMatrix(data=X_test, label=y_test)
    dtest = xgb.DMatrix(data=Xt)
    ml_times["t_dmatrix"] += timer() - t_ml_start

    watchlist = [(dvalid, "eval"), (dtrain, "train")]

    t0 = timer()
    clf = xgb.train(
        cpu_params,
        dtrain=dtrain,
        num_boost_round=60,
        evals=watchlist,
        feval=func_loss,
        early_stopping_rounds=10,
        verbose_eval=1000,
    )
    ml_times["t_training"] += timer() - t0

    t0 = timer()
    yp = clf.predict(dvalid)
    ml_times["t_infer"] += timer() - t0

    cpu_loss = multi_weighted_logloss(y_test, yp, classes, class_weights)

    t0 = timer()
    ysub = clf.predict(dtest)
    ml_times["t_infer"] += timer() - t0

    ml_times["t_ml"] = timer() - t_ml_start

    print("validation cpu_loss:", cpu_loss)

    return ml_times


def compute_skip_rows(gpu_memory):
    # count rows inside test_set.csv
    test_rows = 453653104

    # if you want to use ibis' read_csv then you need to manually create
    # test_set_skiprows.csv (for example, via next command:
    # `head -n 189022128 test_set.csv > test_set_skiprows.csv`)
    #
    # for gpu_memory=16 - skip_rows=189022127 (+1 for header)

    overhead = 1.2
    skip_rows = int((1 - gpu_memory / (32.0 * overhead)) * test_rows)
    return skip_rows


def run_benchmark(parameters):
    ignored_parameters = {
        "dfiles_num": parameters["dfiles_num"],
    }
    warnings.warn(f"Parameters {ignored_parameters} are irnored", RuntimeWarning)

    parameters["data_file"] = parameters["data_file"].replace("'", "")
    skip_rows = compute_skip_rows(parameters["gpu_memory"])

    dtypes = OrderedDict(
        [
            ("object_id", "int32"),
            ("mjd", "float32"),
            ("passband", "int32"),
            ("flux", "float32"),
            ("flux_err", "float32"),
            ("detected", "int32"),
        ]
    )

    # load metadata
    columns_names = [
        "object_id",
        "ra",
        "decl",
        "gal_l",
        "gal_b",
        "ddf",
        "hostgal_specz",
        "hostgal_photoz",
        "hostgal_photoz_err",
        "distmod",
        "mwebv",
        "target",
    ]
    meta_dtypes = ["int32"] + ["float32"] * 4 + ["int32"] + ["float32"] * 5 + ["int32"]
    meta_dtypes = OrderedDict(
        [(columns_names[i], meta_dtypes[i]) for i in range(len(meta_dtypes))]
    )

    try:

        import_pandas_into_module_namespace(
            namespace=run_benchmark.__globals__,
            mode=parameters["pandas_mode"],
            ray_tmpdir=parameters["ray_tmpdir"],
            ray_memory=parameters["ray_memory"],
        )

        etl_times_ibis = None
        ml_times_ibis = None
        if not parameters["no_ibis"]:
            train_final_ibis, test_final_ibis, etl_times_ibis = etl_all_ibis(
                dataset_path=parameters["data_file"],
                database_name=parameters["database_name"],
                omnisci_server_worker=parameters["omnisci_server_worker"],
                delete_old_database=not parameters["dnd"],
                create_new_table=not parameters["dni"],
                connection_func=parameters["connect_to_sever"],
                skip_rows=skip_rows,
                validation=parameters["validation"],
                dtypes=dtypes,
                meta_dtypes=meta_dtypes,
            )

            ml_data_ibis, etl_times_ibis = split_step(
                train_final_ibis, test_final_ibis, etl_times_ibis
            )
            print_times(etl_times=etl_times_ibis, backend="Ibis")
            etl_times_ibis["Backend"] = "Ibis"

            if not parameters["no_ml"]:
                print("using ml with dataframes from Ibis")
                ml_times_ibis = ml(ml_data_ibis)
                print_times(etl_times=ml_times_ibis, backend="Ibis")
                ml_times_ibis["Backend"] = "Ibis"

        train_final, test_final, etl_times = etl_all_pandas(
            dataset_path=parameters["data_file"],
            skip_rows=skip_rows,
            dtypes=dtypes,
            meta_dtypes=meta_dtypes,
        )

        ml_data, etl_times = split_step(train_final, test_final, etl_times)
        print_times(etl_times=etl_times, backend=parameters["pandas_mode"])
        etl_times["Backend"] = parameters["pandas_mode"]

        if not parameters["no_ml"]:
            print("using ml with dataframes from Pandas")
            ml_times = ml(ml_data)
            print_times(etl_times=ml_times, backend=parameters["pandas_mode"])
            ml_times["Backend"] = parameters["pandas_mode"]

        if parameters["validation"]:
            pass

        return {"ETL": [etl_times_ibis, etl_times], "ML": [ml_times_ibis, ml_times]}
    except Exception:
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)
