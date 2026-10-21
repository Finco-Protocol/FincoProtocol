"""Environment equivalence is reported item by item and the admission condition stays closed while anything differs."""
from tools.ci_v3_environment import compare, control_packages, image_packages

INSTALL = "Requirement already satisfied: pip in /opt/hostedtoolcache/Python/3.12.15/x64/lib\nSuccessfully installed numpy-1.26.4 python-docx-1.2.0 pip-26.2.2\n"
JOB = "Image: ubuntu-24.04\nVersion: 20261018.339.1\n"
FREEZE = "numpy==1.26.4\npython-docx==1.2.0\npip==25.0.1\n"
SYSTEM = "libc6=2.36-9\n"
OSREL = 'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\n'


def run(freeze=FREEZE, accepted=()):
    return compare(INSTALL, JOB, freeze, SYSTEM, "3.12.15 (main)", "v18.20.4\nOpenSSH_9.2", OSREL, accepted)


def by_name(result):
    return {i["item"]: i for i in result["items"]}


def test_normalization_and_ignored_packages():
    assert control_packages(INSTALL) == {"numpy": "1.26.4", "python-docx": "1.2.0", "pip": "26.2.2"}
    assert image_packages(FREEZE)["python-docx"] == "1.2.0"
    assert by_name(run())["python-packages-direct-and-transitive"]["status"] == "equal"      # pip version ignored


def test_version_drift_is_reported_and_never_equal():
    items = by_name(run("numpy==1.26.5\npython-docx==1.2.0\n"))
    assert items["python-packages-direct-and-transitive"]["status"] == "different" and items["native-numerical-libraries"]["status"] == "different"


def test_admission_stays_closed_until_every_difference_is_accepted():
    result = run()
    assert result["fully_equivalent"] is False and result["admission_condition"] == "closed"
    everything = tuple(result["unaccepted_differences"])
    assert run(accepted=everything)["admission_condition"] == "open"
    assert run(accepted=everything[:-1])["admission_condition"] == "closed"


def test_python_and_os_are_read_from_control_artifacts():
    items = by_name(run())
    assert items["python-version"]["status"] == "equal" and items["operating-system"]["control"] == "ubuntu-24.04 20261018.339.1"
