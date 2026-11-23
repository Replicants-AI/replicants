import re

import pytest

from replicants.utils import stack_stop


@pytest.mark.parametrize(
    "cmd,expect",
    [
        (r"python -m replicants.main run canary", True),
        (r"C:\py\python.exe -m replicants.main worker x", True),
        (r"python -m replicants.main api --host 0.0.0.0", True),
        (r"python -m replicants.main talk canary", True),
        (r"python -m replicants.main stop", False),
        (r"python -m replicants.main setup", False),
        (r"python -m replicants.inference_gateway", True),
        (r"py -m replicants.inference_gateway", True),
        (r"pytest tests/", False),
    ],
)
def test_stack_cmdline_patterns(cmd: str, expect: bool) -> None:
    m1 = stack_stop._MAIN_SUBCOMMANDS.search(cmd)
    m2 = stack_stop._GATEWAY_MOD.search(cmd)
    assert bool(m1 or m2) is expect


def test_stack_cmdline_does_not_match_substring_false_positive() -> None:
    assert stack_stop._MAIN_SUBCOMMANDS.search("replicants.main runner") is None
