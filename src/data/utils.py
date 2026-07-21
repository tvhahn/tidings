import argparse
from pathlib import Path


def create_arg_parser():
    parser = argparse.ArgumentParser(description="Arguments for the creating the embeddings")

    parser.add_argument("-p", "--proj_dir", type=str, help="Location of project folder")

    parser.add_argument(
        "--path_data_dir",
        type=str,
        help="Location of the data folder, containing the raw, interim, and processed folders",
    )

    return parser


def set_directories(proj_dir: str | None = None, path_data_dir: str | None = None) -> tuple[Path, Path]:
    proj_path = Path(proj_dir) if proj_dir else Path().cwd()
    data_path = Path(path_data_dir) if path_data_dir else proj_path / "data"

    return proj_path, data_path


def load_and_prepare_environment():
    parser = create_arg_parser()
    args = parser.parse_args()
    return set_directories(
        proj_dir=args.proj_dir,
        path_data_dir=args.path_data_dir,
    )
