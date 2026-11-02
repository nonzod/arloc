import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        from arloc.app import run
        return run()
    from arloc.cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
