import argparse
import os
import re
import sys
import traceback

from environment import CondaEnvironment
from server import OmnisciServer
from utils import combinate_requirements, random_if_default, str_arg_to_bool


def main():
    omniscript_path = os.path.dirname(__file__)
    omnisci_server = None
    args = None

    parser = argparse.ArgumentParser(description="Run internal tests from ibis project")
    required = parser._action_groups.pop()
    optional = parser.add_argument_group("optional arguments")
    omnisci = parser.add_argument_group("omnisci")
    benchmark = parser.add_argument_group("benchmark")
    mysql = parser.add_argument_group("mysql")
    commits = parser.add_argument_group("commits")

    possible_tasks = ["build", "test", "benchmark"]
    benchmarks = ["ny_taxi", "santander", "census", "plasticc"]
    # Task
    required.add_argument(
        "-task",
        dest="task",
        required=True,
        help=f"Task for execute {possible_tasks}. Use , separator for multiple tasks",
    )

    # Environment
    required.add_argument("-en", "--env_name", dest="env_name", help="Conda env name.")
    optional.add_argument(
        "-ec",
        "--env_check",
        dest="env_check",
        default=False,
        type=str_arg_to_bool,
        help="Check if env exists. If it exists don't recreate.",
    )
    optional.add_argument(
        "-s",
        "--save_env",
        dest="save_env",
        default=False,
        type=str_arg_to_bool,
        help="Save conda env after executing.",
    )
    optional.add_argument(
        "-r",
        "--report_path",
        dest="report_path",
        default=os.path.join(omniscript_path, ".."),
        help="Path to report file.",
    )
    optional.add_argument(
        "-ci",
        "--ci_requirements",
        dest="ci_requirements",
        default=os.path.join(omniscript_path, "ci_requirements.yml"),
        help="File with ci requirements for conda env.",
    )
    optional.add_argument(
        "-py",
        "--python_version",
        dest="python_version",
        default="3.7",
        help="File with ci requirements for conda env.",
    )
    # Ibis
    required.add_argument(
        "-i",
        "--ibis_path",
        dest="ibis_path",
        required=True,
        help="Path to ibis directory.",
    )
    # Ibis tests
    optional.add_argument(
        "-expression",
        dest="expression",
        default=" ",
        help="Run tests which match the given substring test names and their parent "
        "classes. Example: 'test_other', while 'not test_method' matches those "
        "that don't contain 'test_method' in their names.",
    )
    # Omnisci server parameters
    omnisci.add_argument(
        "-executable",
        dest="executable",
        required=True,
        help="Path to omnisci_server executable.",
    )
    omnisci.add_argument(
        "--omnisci_cwd",
        dest="omnisci_cwd",
        help="Path to omnisci working directory. "
        "By default parent directory of executable location is used. "
        "Data directory is used in this location.",
    )
    omnisci.add_argument(
        "-port",
        dest="port",
        default=-1,
        type=int,
        help="TCP port number to run omnisci_server on.",
    )
    omnisci.add_argument(
        "-http-port",
        dest="http_port",
        default=-1,
        type=int,
        help="HTTP port number to run omnisci_server on.",
    )
    omnisci.add_argument(
        "-calcite-port",
        dest="calcite_port",
        default=-1,
        type=int,
        help="Calcite port number to run omnisci_server on.",
    )
    omnisci.add_argument(
        "-user",
        dest="user",
        default="admin",
        help="User name to use on omniscidb server.",
    )
    omnisci.add_argument(
        "-password",
        dest="password",
        default="HyperInteractive",
        help="User password to use on omniscidb server.",
    )
    omnisci.add_argument(
        "-database_name",
        dest="database_name",
        default="agent_test_ibis",
        help="Database name to use in omniscidb server.",
    )
    omnisci.add_argument(
        "-table",
        dest="table",
        default="benchmark_table",
        help="Table name name to use in omniscidb server.",
    )
    omnisci.add_argument(
        "-ipc_conn",
        dest="ipc_connection",
        default=True,
        type=str_arg_to_bool,
        help="Table name name to use in omniscidb server.",
    )
    # Benchmark parameters
    benchmark.add_argument(
        "-bench_name", dest="bench_name", choices=benchmarks, help="Benchmark name.",
    )
    benchmark.add_argument(
        "-data_file", dest="data_file", help="A datafile that should be loaded.",
    )
    benchmark.add_argument(
        "-dfiles_num",
        dest="dfiles_num",
        default=1,
        type=int,
        help="Number of datafiles to input into database for processing.",
    )
    benchmark.add_argument(
        "-iterations",
        dest="iterations",
        default=5,
        type=int,
        help="Number of iterations to run every query. Best result is selected.",
    )
    benchmark.add_argument(
        "-dnd", default=False, type=str_arg_to_bool, help="Do not delete old table."
    )
    benchmark.add_argument(
        "-dni",
        default=False,
        type=str_arg_to_bool,
        help="Do not create new table and import any data from CSV files.",
    )
    benchmark.add_argument(
        "-validation",
        dest="validation",
        default=False,
        type=str_arg_to_bool,
        help="validate queries results (by comparison with Pandas queries results).",
    )
    benchmark.add_argument(
        "-optimizer",
        choices=["intel", "stock"],
        dest="optimizer",
        default="intel",
        help="Which optimizer is used",
    )
    benchmark.add_argument(
        "-no_ibis",
        default=False,
        type=str_arg_to_bool,
        help="Do not run Ibis benchmark, run only Pandas (or Modin) version",
    )
    benchmark.add_argument(
        "-pandas_mode",
        choices=["Pandas", "Modin_on_ray", "Modin_on_dask"],
        default="Pandas",
        help="Specifies which version of Pandas to use: "
             "plain Pandas, Modin runing on Ray or on Dask",
    )
    benchmark.add_argument(
        "-ray_tmpdir",
        default="/tmp",
        help="Location where to keep Ray plasma store. "
             "It should have enough space to keep -ray_memory",
    )
    benchmark.add_argument(
        "-ray_memory",
        default=200 * 1024 * 1024 * 1024,
        help="Size of memory to allocate for Ray plasma store",
    )
    benchmark.add_argument(
        "-no_ml",
        default=False,
        type=str_arg_to_bool,
        help="Do not run machine learning benchmark, only ETL part",
    )
    optional.add_argument(
        "-gpu-memory",
        dest="gpu_memory",
        type=int,
        help="specify the memory of your gpu, default 16. "
             "(This controls the lines to be used. Also work for CPU version. )",
        default=16,
    )
    # MySQL database parameters
    mysql.add_argument(
        "-db-server",
        dest="db_server",
        default="localhost",
        help="Host name of MySQL server.",
    )
    mysql.add_argument(
        "-db-port",
        dest="db_port",
        default=3306,
        type=int,
        help="Port number of MySQL server.",
    )
    mysql.add_argument(
        "-db-user",
        dest="db_user",
        help="Username to use to connect to MySQL database. "
        "If user name is specified, script attempts to store results in MySQL "
        "database using other -db-* parameters.",
    )
    mysql.add_argument(
        "-db-pass",
        dest="db_pass",
        default="omniscidb",
        help="Password to use to connect to MySQL database.",
    )
    mysql.add_argument(
        "-db-name",
        dest="db_name",
        default="omniscidb",
        help="MySQL database to use to store benchmark results.",
    )
    mysql.add_argument(
        "-db-table",
        dest="db_table",
        help="Table to use to store results for this benchmark.",
    )
    # Additional information
    commits.add_argument(
        "-commit_omnisci",
        dest="commit_omnisci",
        default="1234567890123456789012345678901234567890",
        help="Omnisci commit hash to use for tests.",
    )
    commits.add_argument(
        "-commit_ibis",
        dest="commit_ibis",
        default="1234567890123456789012345678901234567890",
        help="Ibis commit hash to use for tests.",
    )

    try:
        args = parser.parse_args()

        os.environ["IBIS_TEST_OMNISCIDB_DATABASE"] = args.database_name
        os.environ["IBIS_TEST_DATA_DB"] = args.database_name
        os.environ["IBIS_TEST_OMNISCIDB_PORT"] = str(args.port)
        os.environ["PYTHONIOENCODING"] = "UTF-8"
        os.environ["PYTHONUNBUFFERED"] = "1"

        args.port = random_if_default(
            value=args.port, least=60000, greater=69999, default=-1
        )
        args.http_port = random_if_default(
            value=args.http_port, least=60000, greater=69999, default=-1
        )
        args.calcite_port = random_if_default(
            value=args.calcite_port, least=60000, greater=69999, default=-1
        )

        required_tasks = args.task.split(",")
        tasks = {}
        for task in possible_tasks:
            tasks[task] = True if task in required_tasks else False

        if True not in list(tasks.values()):
            print(
                f"Only {list(tasks.keys())} are supported, {required_tasks} cannot find possible tasks"
            )
            sys.exit(1)

        if args.python_version not in ["3.7", "3,6"]:
            print(
                f"Only 3.7 and 3.6 python versions are supported, {args.python_version} is not supported"
            )
            sys.exit(1)

        ibis_requirements = os.path.join(
            args.ibis_path, "ci", f"requirements-{args.python_version}-dev.yml"
        )
        requirements_file = "requirements.yml"

        conda_env = CondaEnvironment(args.env_name)

        print("PREPARING ENVIRONMENT")
        combinate_requirements(
            ibis_requirements, args.ci_requirements, requirements_file
        )
        conda_env.create(args.env_check, requirements_file=requirements_file)

        if tasks["build"]:
            install_ibis_cmdline = ["python3", os.path.join("setup.py"), "install"]

            print("IBIS INSTALLATION")
            conda_env.run(install_ibis_cmdline, cwd=args.ibis_path, print_output=False)

        if tasks["test"]:
            ibis_data_script = os.path.join(args.ibis_path, "ci", "datamgr.py")
            dataset_download_cmdline = ["python3", ibis_data_script, "download"]
            dataset_import_cmdline = [
                "python3",
                ibis_data_script,
                "omniscidb",
                "-P",
                str(args.port),
                "--database",
                args.database_name,
            ]
            report_file_name = (
                f"report-{args.commit_ibis[:8]}-{args.commit_omnisci[:8]}.html"
            )
            if not os.path.isdir(args.report_path):
                os.makedirs(args.report_path)
            report_file_path = os.path.join(args.report_path, report_file_name)

            ibis_tests_cmdline = [
                "pytest",
                "-m",
                "omniscidb",
                "--disable-pytest-warnings",
                "-k",
                args.expression,
                f"--html={report_file_path}",
            ]

            print("STARTING OMNISCI SERVER")
            omnisci_server = OmnisciServer(
                omnisci_executable=args.executable,
                omnisci_port=args.port,
                http_port=args.http_port,
                calcite_port=args.calcite_port,
                database_name=args.database_name,
                omnisci_cwd=args.omnisci_cwd,
                user=args.user,
                password=args.password,
            )
            omnisci_server.launch()

            print("PREPARING DATA")
            conda_env.run(dataset_download_cmdline)
            conda_env.run(dataset_import_cmdline)

            print("RUNNING TESTS")
            conda_env.run(ibis_tests_cmdline, cwd=args.ibis_path)

        if tasks["benchmark"]:
            # if not args.bench_name or args.bench_name not in benchmarks:
            #     print(
            #     f"Benchmark {args.bench_name} is not supported, only {benchmarks} are supported")
            # sys.exit(1)

            if not args.data_file:
                print(
                    f"Parameter --data_file was received empty, but it is required for benchmarks"
                )
                sys.exit(1)

            benchmark_script_path = os.path.join(
                omniscript_path, "run_ibis_benchmark.py"
            )

            benchmark_cmd = ["python3", benchmark_script_path]

            possible_benchmark_args = [
                "bench_name",
                "data_file",
                "dfiles_num",
                "iterations",
                "dnd",
                "dni",
                "validation",
                "optimizer",
                "no_ibis",
                "pandas_mode",
                "ray_tmpdir",
                "ray_memory",
                "no_ml",
                "gpu-memory",
                "db-server",
                "db-port",
                "db-user",
                "db-pass",
                "db-name",
                "db-table",
                "executable",
                "omnisci_cwd",
                "port",
                "http-port",
                "calcite-port",
                "user",
                "password",
                "ipc_connection",
                "database_name",
                "table",
                "commit_omnisci",
                "commit_ibis",
            ]
            args_dict = vars(args)
            args_dict["data_file"] = f"'{args_dict['data_file']}'"
            for arg_name in list(parser._option_string_actions.keys()):
                try:
                    pure_arg = re.sub(r"^--*", "", arg_name)
                    if pure_arg in possible_benchmark_args:
                        pure_arg = pure_arg.replace("-", "_")
                        arg_value = args_dict[pure_arg]
                        if arg_value:
                            benchmark_cmd.extend([arg_name, str(arg_value)])
                except KeyError:
                    pass

            print(benchmark_cmd)

            conda_env.run(benchmark_cmd)

    except Exception:
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)

    finally:
        if omnisci_server:
            omnisci_server.terminate()
        if args and args.save_env is False:
            conda_env.remove()


if __name__ == "__main__":
    main()
