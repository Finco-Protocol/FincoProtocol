"""Fail-closed readiness and an actual cancellation-regression mutation control."""
import asyncio
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

import p0_exec_helpers as helpers


def test_missing_start_acknowledgement_fails_instead_of_skipping():
    reader, writer = multiprocessing.get_context("spawn").Pipe(duplex=False)
    try:
        with pytest.raises(AssertionError, match="did not acknowledge"):
            asyncio.run(helpers.wait_for_worker_start(reader, timeout=0.01))
    finally:
        reader.close(); writer.close()


@pytest.mark.parametrize('message', [0, -1, 'ready', True, os.getpid()],
                         ids=['zero', 'negative', 'text', 'bool', 'parent'])
def test_invalid_or_parent_start_acknowledgement_is_rejected(message):
    reader, writer = multiprocessing.get_context("spawn").Pipe(duplex=False)
    try:
        writer.send(message)
        with pytest.raises(AssertionError, match="invalid spawned-worker"):
            asyncio.run(helpers.wait_for_worker_start(reader))
    finally:
        reader.close(); writer.close()


def test_closed_readiness_channel_is_failure():
    reader, writer = multiprocessing.get_context("spawn").Pipe(duplex=False)
    writer.close()
    try:
        with pytest.raises(EOFError):
            asyncio.run(helpers.wait_for_worker_start(reader))
    finally:
        reader.close()


