import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from level7.ui.app import main
    sys.exit(main())
