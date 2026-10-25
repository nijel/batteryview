import pytest

from pylontech_tools.errors import (
    CommandCancelled,
    CommandTimeout,
    ConnectionError,
    ProtocolError,
    UnsupportedCommand,
)
from pylontech_tools.protocol import CONTINUATION, Response


@pytest.mark.parametrize("chunk_size", [1, 2, 7, 65536])
@pytest.mark.parametrize("prompt", ["pylon>", "pylon_debug>"])
def test_fragmented_prompt_and_trailing_line_endings(replay, chunk_size, prompt):
    text = f"stat\n\r@\r\n\rSome data\r\n\r$$\r\n\r{prompt}\r\n"
    session, transport = replay([(b"stat\n", text)], chunk_size=chunk_size)
    assert session.exchange("stat").text == text
    assert session.synchronized
    assert not transport.pending


def test_pagination_and_crlf_continuation(replay):
    page = f"history\r\n\r{CONTINUATION}\r"
    end = "\r                       \rnext page\r\n\rpylon_debug>"
    session, transport = replay([(b"datalist history 0\n", page), (b"\r\n", end)], chunk_size=1)
    assert session.exchange("datalist history 0", paginated=True).boundary == "page"
    assert not session.synchronized
    assert session.exchange("", terminator=b"\r\n", paginated=True).text == end
    assert not transport.exchanges


def test_empty_and_regular_prompts_in_same_read(replay):
    session, _ = replay([(b"\n", "\n\rpylon>\n\rpylon_debug>")])
    assert session.resynchronize().text == "\n\rpylon>\n\rpylon_debug>"


def test_no_substring_prompt_match(replay):
    session, _ = replay([(b"info\n", "Device name: notpylon>suffix")], timeout=0.005)
    with pytest.raises(CommandTimeout):
        session.exchange("info")


def test_timeout_preserves_partial_and_does_not_retry_mutation(replay):
    session, transport = replay([(b"eepe 0\r", "eepe 0\n\r@partial")], timeout=0.005)
    with pytest.raises(CommandTimeout) as exc:
        session.exchange("eepe 0", terminator=b"\r")
    assert exc.value.response == "eepe 0\n\r@partial"
    assert transport.writes == [b"eepe 0\r"]
    assert not session.synchronized
    with pytest.raises(ProtocolError, match="resynchronize"):
        session.exchange("info")


def test_cancel_retains_partial_and_requires_resynchronization(replay):
    session, transport = replay([(b"stat\n", "partial")])
    read = transport.read

    def interrupt(size=65536):
        if transport.pending:
            return read(size)
        raise KeyboardInterrupt()

    transport.read = interrupt
    with pytest.raises(CommandCancelled) as error:
        session.exchange("stat")
    assert error.value.response == "partial"
    with pytest.raises(ProtocolError, match="resynchronize"):
        session.exchange("info")


def test_explicit_resynchronization_after_timeout(replay):
    session, _ = replay(
        [(b"stat\n", "partial"), (b"\n", "\rpylon_debug>"), (b"info\n", "\rpylon_debug>")],
        timeout=0.005,
    )
    with pytest.raises(CommandTimeout):
        session.exchange("stat")
    assert session.resynchronize().boundary == "prompt"
    assert session.exchange("info").boundary == "prompt"


def test_prompt_lookalike_at_start_of_line_is_not_a_boundary(replay):
    session, _ = replay([(b"info\n", "\rpylon>suffix")], timeout=0.005)
    with pytest.raises(CommandTimeout):
        session.exchange("info")


def test_unsupported_can_be_retained_by_reset_script(replay):
    text = "Invalid command or fail to excute.\r\n\rpylon_debug>"
    session, _ = replay([(b"datalist misc 0\n", text)] * 2)
    with pytest.raises(UnsupportedCommand) as exc:
        session.exchange("datalist misc 0")
    assert exc.value.response == text
    assert session.exchange("datalist misc 0", allow_unsupported=True).unsupported


@pytest.mark.parametrize(
    "text",
    [
        "Unknown command 'pwrsys' - try 'help'\r\npylon_debug>",
        "pwrsys\n\r@\r\r\nUnknown command 'pwrsys' - try 'help'\r\n\rpylon_debug>",
        "\r\n  UNKNOWN COMMAND: pwrsys\r\npylon_debug>",
    ],
)
def test_unknown_command_is_classified_as_unsupported(replay, text):
    session, _ = replay([(b"pwrsys\n", text)], chunk_size=1)
    with pytest.raises(UnsupportedCommand) as error:
        session.exchange("pwrsys")
    assert error.value.response == text
    assert session.synchronized


def test_unknown_command_words_in_a_field_are_not_an_error():
    assert not Response(
        "Description : Unknown command behavior\rpylon_debug>", "prompt"
    ).unsupported


def test_response_limit(replay):
    session, _ = replay([(b"stat\n", "x" * 100)])
    session.max_response_bytes = 10
    with pytest.raises(ProtocolError, match="exceeded"):
        session.exchange("stat")


def test_disconnect_retains_partial_response(replay):
    session, transport = replay([(b"stat\n", "partial")])
    read = transport.read

    def disconnect(size=65536):
        if transport.pending:
            return read(size)
        raise ConnectionError("unplugged")

    transport.read = disconnect
    with pytest.raises(ProtocolError) as exc:
        session.exchange("stat")
    assert exc.value.response == "partial"


def test_connection_handshake(replay, monkeypatch):
    from pylontech_tools.protocol import SHIFT_SEQUENCE

    monkeypatch.setattr("pylontech_tools.protocol.time.sleep", lambda _: None)
    session, transport = replay(
        [
            (SHIFT_SEQUENCE, ""),
            (b"\n", "\rpylon>"),
            (b"login debug\n", "\rpylon_debug>"),
        ]
    )
    session.settle_time = 0
    session.connect()
    assert transport.baudrate == 115200
    assert not transport.exchanges


@pytest.mark.parametrize(
    "initial,login_response,expected_error",
    [
        ("\rpylon_debug>", None, None),
        ("\rpylon>", "\rpylon_debug>", None),
        ("\rpylon>", "Invalid command\rpylon_debug>", None),
        ("\rpylon>", "Invalid command\rpylon>", UnsupportedCommand),
        ("\rpylon>", "\rpylon>", ProtocolError),
        ("\rpylon_debug>\rpylon>", "Invalid command\rpylon>", UnsupportedCommand),
        ("\rpylon>", "\rpylon_debug>\rpylon>", ProtocolError),
    ],
)
def test_connect_uses_final_prompt(replay, monkeypatch, initial, login_response, expected_error):
    monkeypatch.setattr("pylontech_tools.protocol.time.sleep", lambda _: None)
    exchanges = [(b"\n", initial)]
    if login_response is not None:
        exchanges.append((b"login debug\n", login_response))
    session, transport = replay(exchanges, chunk_size=65536)
    session.settle_time = 0
    if expected_error:
        with pytest.raises(expected_error):
            session.connect(shift=False)
    else:
        session.connect(shift=False)
        assert session.current_prompt == "pylon_debug>"
    assert not transport.exchanges
    if login_response is None:
        assert transport.writes == [b"\n"]


def test_reconnect_without_debug_keeps_script_login_explicit(replay, monkeypatch):
    monkeypatch.setattr("pylontech_tools.protocol.time.sleep", lambda _: None)
    session, transport = replay([(b"\n", "\rpylon>")])
    session.settle_time = 0
    session.connect(shift=False, enter_debug=False)
    assert session.current_prompt == "pylon>"
    assert transport.writes == [b"\n"]


def test_login_timeout_is_not_ignored(replay, monkeypatch):
    monkeypatch.setattr("pylontech_tools.protocol.time.sleep", lambda _: None)
    session, transport = replay([(b"\n", "\rpylon>"), (b"login debug\n", "partial")], timeout=0.005)
    session.settle_time = 0
    with pytest.raises(CommandTimeout):
        session.connect(shift=False)
    assert transport.writes.count(b"login debug\n") == 1


def test_response_prompt_does_not_accept_echoed_substrings():
    assert Response("Device name: notpylon_debug>", "prompt").prompt is None
    assert Response("\rpylon_debug>\r\npylon>", "prompt").prompt == "pylon>"
