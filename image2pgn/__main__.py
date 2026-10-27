import sys

if len(sys.argv) == 1:
    from .launcher import main
else:
    from .cli import main

if __name__ == "__main__":
    main()
