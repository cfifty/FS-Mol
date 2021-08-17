import argparse
import csv
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Iterable, Tuple

from dpu_utils.utils.richpath import RichPath

from metamol.data.metamol_dataset import DataFold, MetamolDataset
from metamol.utils.cli_utils import set_seed
from metamol.utils.logging import set_up_logging
from metamol.utils.metrics import BinaryEvalMetrics


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetamolTaskSampleEvalResults(BinaryEvalMetrics):
    task_name: str
    seed: int
    num_train: int
    num_test: int
    fraction_pos_train: float
    fraction_pos_test: float


def add_data_cli_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "DATA_PATH",
        type=str,
        nargs="+",
        help=(
            "File(s) containing the test data."
            " If this is a directory, --task-file-list is required to define the test tasks."
            " Otherwise, it is the data file(s) on which testing is done."
        ),
    )

    parser.add_argument(
        "--task-file-list",
        type=str,
        default=None,
        help="JSON dictionary file with lists of train/test/valid tasks.",
    )


def add_eval_cli_args(parser: argparse.ArgumentParser) -> None:
    add_data_cli_args(parser)

    parser.add_argument(
        "--save-dir",
        type=str,
        default="outputs",
        help="Path in which to store the test results and log of their computation.",
    )

    parser.add_argument(
        "--num-runs",
        type=int,
        default=5,
        help="Number of runs with different data splits to do.",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Random seed to use.",
    )

    parser.add_argument(
        "--train-sizes",
        type=json.loads,
        default=[16, 32, 64, 128, 256],
        help="JSON list of number of training points to sample.",
    )

    parser.add_argument(
        "--test-size",
        type=int,
        default=None,
        help="Number of test samples to take, default is take all remaining after splitting out train.",
    )


def set_up_dataset(args: argparse.Namespace, **kwargs):
    # Handle the different task entry methods.
    if args.task_file_list is not None:
        assert (
            len(args.DATA_PATH) == 1
        ), "DATA_PATH argument should be directory only if task_file_list arg is passed."
        return MetamolDataset.from_task_split_file(args.DATA_PATH[0], args.task_file_list, **kwargs)
    else:
        return MetamolDataset(
            test_data_paths=[RichPath.create(p) for p in args.DATA_PATH], **kwargs
        )


def set_up_test_run(
    model_name: str, args: argparse.Namespace, torch: bool = False, tf: bool = False
) -> Tuple[str, MetamolDataset]:
    set_seed(args.seed, torch=torch, tf=tf)
    run_name = f"Metamol_Eval_{model_name}_{time.strftime('%Y-%m-%d_%H-%M-%S')}"
    out_dir = os.path.join(args.save_dir, run_name)
    os.makedirs(out_dir, exist_ok=True)
    set_up_logging(os.path.join(out_dir, f"{run_name}.log"))

    dataset = set_up_dataset(args)
    logger.info(
        f"Starting test run {run_name} on {len(dataset.get_task_names(DataFold.TEST))} assays"
    )
    logger.info(f"\tArguments: {args}")
    logger.info(f"\tOutput dir: {out_dir}")

    return out_dir, dataset


def write_csv_summary(output_csv_file: str, test_results: Iterable[MetamolTaskSampleEvalResults]):
    with open(output_csv_file, "w", newline="") as csv_file:
        fieldnames = [
            "num_train_requested",
            "num_train",
            "fraction_positive_train",
            "num_test",
            "fraction_positive_test",
            "seed",
            "valid_score",
            "average_precision_score",
            "roc_auc",
            "acc",
            "balanced_acc",
            "precision",
            "recall",
            "f1_score",
            "delta_auprc",
        ]
        csv_writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        csv_writer.writeheader()

        for test_result in test_results:
            csv_writer.writerow(
                {
                    "num_train_requested": test_result.num_train,
                    "num_train": test_result.num_train,
                    "num_test": test_result.num_test,
                    "fraction_positive_train": test_result.fraction_pos_train,
                    "fraction_positive_test": test_result.fraction_pos_test,
                    "seed": test_result.seed,
                    "average_precision_score": test_result.avg_precision,
                    "roc_auc": test_result.roc_auc,
                    "acc": test_result.acc,
                    "balanced_acc": test_result.balanced_acc,
                    "precision": test_result.prec,
                    "recall": test_result.recall,
                    "f1_score": test_result.f1,
                    "delta_auprc": test_result.avg_precision - test_result.fraction_pos_test,
                }
            )
