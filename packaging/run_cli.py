import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == "inspect":
        from level7.diagnostics.inspector import main
        sys.exit(main(sys.argv[2:]))
    from level7.cli import main
    sys.exit(main())
