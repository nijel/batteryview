import codecs

import pytest

from pylontech_tools import BatteryClient, CommandTimeout, ConnectionError, ProtocolError
from pylontech_tools.diagnostics import configure_logging


@pytest.mark.parametrize(
    "text",
    ["cmdquit", "cmdquit\n\r", "cmdquit\n\rpylon>", "Invalid command: cmdquit\rpylon_debug>"],
)
@pytest.mark.parametrize("chunk_size", [1, 65536])
def test_disconnect_matches_command_echo_without_requiring_prompt(replay, text, chunk_size):
    session, transport = replay([(b"cmdquit\n", text)], chunk_size=chunk_size)
    session.disconnect()
    assert transport.closed
    assert transport.writes == [b"cmdquit\n"]
    assert not transport.pending
    assert session.current_prompt is None and not session.synchronized


def test_disconnect_timeout_uses_five_seconds_and_always_closes(replay, monkeypatch, capsys):
    session, transport = replay([(b"cmdquit\n", "")], timeout=0.001)

    def timeout(command, *, paginated, timeout, disconnect):
        assert command == "cmdquit" and timeout == 5
        assert disconnect and not paginated
        raise CommandTimeout("no echo")

    monkeypatch.setattr(session, "_receive", timeout)
    with configure_logging(debug=True):
        session.disconnect()
    assert transport.closed
    assert transport.writes == [b"cmdquit\n"]
    assert "Disconnect failed error=CommandTimeout" in capsys.readouterr().err


def test_rejected_cmdquit_is_logged_without_changing_echo_matching_or_cleanup(replay, capsys):
    session, transport = replay(
        [
            (
                b"cmdquit\n",
                "cmdquit\n\r@\r\r\nUnknown command 'cmdquit' - try 'help'\r\n\rpylon_debug>",
            ),
        ],
        chunk_size=1,
    )
    with configure_logging(debug=True):
        session.disconnect()
    output = capsys.readouterr()
    assert "Disconnect command=cmdquit rejected by firmware; closing port anyway" in output.err
    assert "Disconnect response matched" not in output.err
    assert "Unknown command" not in output.err
    assert transport.closed and transport.writes == [b"cmdquit\n"]
    assert not output.out


def test_disconnect_prompt_alone_does_not_acknowledge_cmdquit(replay, monkeypatch, capsys):
    session, transport = replay([(b"cmdquit\n", "\rpylon>")])
    # Exercise the actual reader with an accelerated monotonic clock. The
    # five-second protocol wait must expire despite receiving a regular prompt.
    tick = iter(range(100))
    monkeypatch.setattr("pylontech_tools.protocol.time.monotonic", lambda: next(tick))
    with configure_logging(debug=True):
        session.disconnect()
    assert transport.closed
    assert "Disconnect failed error=CommandTimeout" in capsys.readouterr().err


@pytest.mark.parametrize("failure", [ConnectionError("unplugged"), OSError("unplugged")])
def test_disconnect_write_failure_still_closes(replay, monkeypatch, failure):
    session, transport = replay([])

    def write(data):
        assert data == b"cmdquit\n"
        raise failure

    monkeypatch.setattr(transport, "write", write)
    session.disconnect()
    assert transport.closed


def test_close_failure_does_not_mask_operation_failure(replay, monkeypatch):
    session, transport = replay([(b"cmdquit\n", "cmdquit")])

    def close():
        transport.closed = True
        raise OSError("close failed")

    monkeypatch.setattr(transport, "close", close)
    with pytest.raises(ProtocolError, match="original error"):
        with BatteryClient(session=session):
            raise ProtocolError("original error")
    assert transport.closed


def test_disconnect_after_timeout_sends_only_cmdquit_not_failed_command(replay):
    session, transport = replay(
        [(b"eepe 0\r", "partial"), (b"cmdquit\n", "cmdquit")], timeout=0.005
    )
    with pytest.raises(CommandTimeout):
        session.exchange("eepe 0", terminator=b"\r")
    session.disconnect()
    assert transport.writes == [b"eepe 0\r", b"cmdquit\n"]
    assert transport.closed


def test_client_context_exit_disconnects_once_and_rejects_later_commands(replay):
    session, transport = replay([(b"cmdquit\n", "cmdquit")])
    client = BatteryClient(session=session)
    with client:
        pass
    client.close()
    session.disconnect()
    session.close()
    assert transport.writes == [b"cmdquit\n"]
    with pytest.raises(ConnectionError, match="closed"):
        session.exchange("info")


def test_failed_operation_is_preserved_during_disconnect_timeout(replay, monkeypatch):
    session, transport = replay([(b"cmdquit\n", "")])
    monkeypatch.setattr(
        session,
        "_receive",
        lambda *args, **kwargs: (_ for _ in ()).throw(CommandTimeout("disconnect timeout")),
    )
    with pytest.raises(ValueError, match="original error"):
        with BatteryClient(session=session):
            raise ValueError("original error")
    assert transport.closed


def test_report_is_complete_before_disconnect_and_excludes_cmdquit(replay, tmp_path):
    info = "Device name : SYNTHETIC_MODEL\rpylon_debug>"
    stat = "Data Items : 0\rpylon_debug>"
    event = "data event\n\rpylon_debug>"
    session, transport = replay(
        [
            (b"info\n", info),
            (b"stat\n", stat),
            (b"data event\n", event),
            (b"cmdquit\n", "cmdquit\n\r"),
        ]
    )
    path = tmp_path / "event.txt"
    with BatteryClient(session=session) as client:
        client.export_events(path)
        before = path.read_bytes()
    expected = codecs.BOM_UTF16_LE + "".join(s + "\r\n" for s in [info, stat, event]).encode(
        "utf-16-le"
    )
    assert path.read_bytes() == before == expected
    assert transport.closed and transport.writes[-1] == b"cmdquit\n"


def test_low_level_close_is_immediate_without_protocol_commands(replay):
    session, transport = replay([])
    session.close()
    assert transport.closed and not transport.writes


def test_failed_setup_closes_port_and_preserves_original_error(monkeypatch):
    class FailedSession:
        def __init__(self, *args, **kwargs):
            pass

        def connect(self, **kwargs):
            raise ProtocolError("login failed")

        def close(self):
            raise OSError("close failed")

    monkeypatch.setattr("pylontech_tools.client.SerialTransport", lambda *args: object())
    monkeypatch.setattr("pylontech_tools.client.ConsoleSession", FailedSession)
    with pytest.raises(ProtocolError, match="login failed"):
        BatteryClient("SYNTHETIC_PORT").connect()
