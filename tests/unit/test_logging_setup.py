from __future__ import annotations

import io
import logging

from fx_hybrid_engine.utils.logging import setup_logging


def test_setup_logging_rebinds_root_handlers_from_closed_stream():
    root = logging.getLogger()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root.handlers = [handler]
    stream.close()

    setup_logging()

    assert len(root.handlers) == 1
    assert root.handlers[0].stream is not stream
