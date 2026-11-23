"""Print the node ids listed in tests/known_defects.txt, one per line (``--deselect`` prefixes them for pytest).

Format of the list: ``<pytest node id>  # <diagnosis>``; node ids may contain spaces (parametrized ids)."""
import sys


def node_ids(path="tests/known_defects.txt"):
    out = []
    for line in open(path, encoding="utf-8"):
        node = line.split("#", 1)[0].strip()
        if node:
            out.append(node)
    return out


if __name__ == "__main__":
    prefix = "--deselect=" if "--deselect" in sys.argv[1:] else ""
    for node in node_ids():
        print(prefix + node)
