"""Create an empty database schema; never insert payroll examples."""
import argparse

from src.services.database_service import DatabaseService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/runtime/nominas.sqlite")
    args = parser.parse_args()
    DatabaseService(args.db).init_db()


if __name__ == "__main__":
    main()
