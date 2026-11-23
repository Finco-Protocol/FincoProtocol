"""Print the node ids listed in tests/known_defects.txt, one per line (``--deselect`` prefixes them for pytest).

Format of the list: ``<pytest node id>  # <diagnosis>``; node ids may contain spaces (parametrized ids).
``--file PATH`` reads another list in the same format (e.g. tests/full_regression_nodes.txt, the exact nodes deferred
from the standard groups to the FULL regression job)."""
import sys


def node_ids(path="tests/known_defects.txt"):
    out = []
    for line in open(path, encoding="utf-8"):
        node = line.split("#", 1)[0].strip()
        if node:
            out.append(node)
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    path = args[args.index("--file") + 1] if "--file" in args else "tests/known_defects.txt"
    prefix = "--deselect=" if "--deselect" in args else ""
    for node in node_ids(path):
        print(prefix + node)
