import codecs
import json
import re
from datetime import datetime
from pathlib import Path

import pytest
from conftest import ScriptedSession

from pylontech_tools import BatteryClient, CommandTimeout, ProtocolError, ResetRecoveryError
from pylontech_tools.protocol import CONTINUATION, Response
from pylontech_tools.transcript import TranscriptWriter, report_filename

INFO = (
    "info\n\r@\r\n\rDevice address      : 1\r\n\rDevice name         : SYNTHETIC_MODEL"
    "\r\n\rBarcode             : TEST123\r\n\rCell Number         : 2"
    "\r\n\rCommand completed successfully\r\n\r$$\r\n\rpylon_debug>"
)


def reply(text="", *, page=False):
    return Response(text or "\rpylon_debug>", "page" if page else "prompt")


def stat(count=0, events=0):
    return reply(f"stat\n\r@\r\r\nHisData Items : {count}\r\r\nData Items : {events}\rpylon_debug>")


def test_empty_event_exact_bytes_and_no_pagination(tmp_path, replay):
    exchanges = [
        (b"info\n", INFO),
        (b"stat\n", stat().text),
        (b"data event\n", "data event\n\r@\r\n\r$$\r\n\rpylon_debug>"),
    ]
    session, transport = replay(exchanges)
    path = tmp_path / "event.txt.txt"
    result = BatteryClient(session=session).export_events(path)
    expected = codecs.BOM_UTF16_LE + "".join(text + "\r\n" for _, text in exchanges).encode(
        "utf-16-le"
    )
    assert path.read_bytes() == expected
    assert result.records == 0 and result.responses == 3 and result.complete
    assert not transport.exchanges


@pytest.mark.parametrize("kind", ["history", "event"])
def test_detailed_report_final_partial_block_and_exit_sequence(tmp_path, replay, kind):
    exchanges = [
        (b"info\n", INFO),
        (b"stat\n", stat(16, 16).text),
        (f"data {kind}\n".encode(), "\rpylon_debug>"),
    ]
    exchanges += [
        (
            f"datalist {kind} dtls 0\n".encode(),
            "\r".join(f"{i} 00-01-01 00:00:00 50000" for i in range(15)) + f"\r{CONTINUATION}\r",
        ),
        (b"\n", "\r                          \r\rpylon_debug>"),
        (f"datalist {kind} dtls 15\n".encode(), "15 00-01-01 00:00:00 50000\rpylon_debug>"),
        (b"\n", "\n\rpylon_debug>"),
    ]
    session, transport = replay(exchanges)
    client = BatteryClient(session=session)
    progress = []
    method = client.export_history if kind == "history" else client.export_events
    result = method(tmp_path / "report.txt", progress=lambda *args: progress.append(args))
    assert result.records == 16
    assert result.path.read_bytes() == codecs.BOM_UTF16_LE + "".join(
        text + "\r\n" for _, text in exchanges
    ).encode("utf-16-le")
    assert progress == [(kind, 15, 16), (kind, 16, 16)]
    assert not transport.exchanges


def test_failed_report_keeps_partial_response(tmp_path):
    session = ScriptedSession(
        [
            ("info", reply(INFO)),
            ("stat", CommandTimeout("timeout", response="stat\n\r@partial")),
        ]
    )
    path = tmp_path / "report.txt"
    with pytest.raises(CommandTimeout):
        BatteryClient(session=session).export_history(path)
    assert path.read_bytes().decode("utf-16") == INFO + "\r\nstat\n\r@partial\r\n"


def test_invalid_count_is_not_an_empty_success(tmp_path):
    session = ScriptedSession(
        [("info", reply(INFO)), ("stat", reply("HisData Items : ???")), ("data history", reply())]
    )
    with pytest.raises(ProtocolError, match="count"):
        BatteryClient(session=session).export_history(tmp_path / "report.txt")


def reset_exchanges(*, barcode="TEST123"):
    identity = INFO.replace("TEST123", barcode)
    return [
        ("stat", stat()),
        ("datalist event 0", reply("Invalid command or fail to excute.\rpylon_debug>")),
        ("", reply()),
        ("datalist misc 0", reply()),
        ("", reply()),
        ("datalist history 0", reply(CONTINUATION, page=True)),
        ("", reply(CONTINUATION, page=True)),
        ("", reply()),
        ("info", reply(identity)),
        ("setlowcfg", reply("ShutSoc = 3 %\rpylon_debug>")),
        ("eepe 0", reply("Command completed successfully\rpylon_debug>")),
        ("trst", reply("trst\n\r@pylon>")),
        ("login debug", reply()),
        (f"tbar {barcode}", reply("Test result:pass\rpylon_debug>")),
        ("info", reply(identity.replace(": 1\r", ": 2\r"))),
        ("setlowcfg", reply()),
    ]


def test_reset_preserves_identity_and_records_exact_script_order(tmp_path):
    exchanges = reset_exchanges()
    session = ScriptedSession(exchanges)
    path = tmp_path / "reset.txt"
    result = BatteryClient(session=session).reset_soc(path)
    assert not session.exchanges
    assert session.reconnects == [{"baudrate": 115200, "shift": True, "enter_debug": False}]
    assert path.read_bytes().decode("utf-16") == "".join(r.text + "\r\n" for _, r in exchanges)
    recovery = json.loads(result.recovery_path.read_text())
    assert recovery["status"] == "complete"
    assert recovery["barcode"] == "TEST123"
    assert recovery["identity_after"]["address"] == 2
    for command, kwargs in session.calls:
        if command.startswith("datalist"):
            assert kwargs["allow_unsupported"]
        elif command == "":
            assert kwargs["terminator"] == b"\r\n"
        else:
            assert kwargs["terminator"] == b"\r"


@pytest.mark.parametrize("step", ["eepe 0", "trst", "tbar TEST123"])
def test_reset_failure_is_durable_and_never_retried(tmp_path, step):
    exchanges = reset_exchanges()
    position = next(i for i, (cmd, _) in enumerate(exchanges) if cmd == step)
    exchanges[position] = (step, CommandTimeout("unplugged", response="partial"))
    session = ScriptedSession(exchanges)
    path = tmp_path / "reset.txt"
    with pytest.raises(ResetRecoveryError) as error:
        BatteryClient(session=session).reset_soc(path)
    state = json.loads(Path(error.value.recovery_path).read_text())
    assert state["status"] == "interrupted"
    assert state["barcode"] == "TEST123"
    assert [cmd for cmd, _ in session.calls].count(step) == 1
    assert path.read_bytes().decode("utf-16").endswith("partial\r\n")


def test_reset_durable_identity_exists_before_eeprom_write(tmp_path):
    session = ScriptedSession(reset_exchanges())
    original = session.exchange
    path = tmp_path / "reset.txt"

    def exchange(command, **kwargs):
        if command == "eepe 0":
            state = json.loads(path.with_name(path.name + ".recovery.json").read_text())
            assert state["barcode"] == "TEST123" and state["step"] == "eepe 0"
            assert path.read_bytes().decode("utf-16").endswith("ShutSoc = 3 %\rpylon_debug>\r\n")
        return original(command, **kwargs)

    session.exchange = exchange
    BatteryClient(session=session).reset_soc(path)


def test_reset_aborts_before_eeprom_without_barcode(tmp_path):
    session = ScriptedSession(reset_exchanges(barcode=""))
    with pytest.raises(ResetRecoveryError, match="barcode"):
        BatteryClient(session=session).reset_soc(tmp_path / "reset.txt")
    assert not any(cmd == "eepe 0" for cmd, _ in session.calls)


def test_reset_verifies_restored_barcode(tmp_path):
    exchanges = reset_exchanges()
    exchanges[-2] = ("info", reply(INFO.replace("TEST123", "DIFFERENT")))
    session = ScriptedSession(exchanges)
    with pytest.raises(ResetRecoveryError, match="identity"):
        BatteryClient(session=session).reset_soc(tmp_path / "reset.txt")
    assert len(session.exchanges) == 1


def test_reset_reconnect_failure_does_not_repeat_clear(tmp_path):
    session = ScriptedSession(reset_exchanges())

    def disconnect(**kwargs):
        raise CommandTimeout("no prompt")

    session.connect = disconnect
    with pytest.raises(ResetRecoveryError, match="reconnect"):
        BatteryClient(session=session).reset_soc(tmp_path / "reset.txt")
    assert [cmd for cmd, _ in session.calls].count("eepe 0") == 1


def test_interrupt_before_mutation_retains_report_and_recovery(tmp_path):
    session = ScriptedSession([("stat", KeyboardInterrupt())])
    with pytest.raises(ResetRecoveryError):
        BatteryClient(session=session).reset_soc(tmp_path / "reset.txt")
    state = json.loads((tmp_path / "reset.txt.recovery.json").read_text())
    assert state["status"] == "interrupted"
    assert len(session.calls) == 1


def test_writer_never_overwrites(tmp_path):
    path = tmp_path / "report.txt"
    path.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        TranscriptWriter(path)
    assert path.read_bytes() == b"original"


def test_vendor_filename_quirks():
    now = datetime(2000, 1, 2, 3, 4, 5)
    assert report_filename("TEST123", "event", now=now) == "TEST123_event_20000102030405.txt.txt"
    assert report_filename("TEST123", "resetsoc", now=now) == "TEST123_resetsoc _20000102030405.txt"
    assert report_filename(None, "resetsoc", now=now) == "UnknownSN_resetsoc_20000102030405.txt"


def split_reference_frames(text):
    """Remove only the writer's CRLF at known recorded response boundaries.

    Boundary locations come from the vendor samples, not from our framing code.
    Script continuation responses may contain two prompts with no writer CRLF
    between them; only the final prompt matches this delimiter.
    """
    pattern = re.compile(r"(?:pylon(?:_debug)?>|" + re.escape(CONTINUATION) + r"\r)\r\n")
    frames = []
    offset = 0
    for match in pattern.finditer(text):
        frames.append(text[offset : match.end() - 2])
        offset = match.end()
    if offset != len(text):
        raise ValueError("Unrecognized private recording boundary")
    return frames


@pytest.mark.parametrize("kind", ["history", "event", "resetsoc"])
def test_supplied_vendor_recordings_byte_for_byte(tmp_path, replay, kind, request):
    private_logs = request.config.getoption("--private-logs")
    if private_logs is None:
        pytest.skip("Private replay is opt-in: --private-logs=/path/to/local/recordings")
    # Do not let a replay failure print private payloads in test logs or CI output.
    try:
        _check_private_recording(tmp_path, replay, kind, Path(private_logs))
    except Exception:
        pytest.fail(
            "Private recording replay failed; inspect it locally. Payload omitted.", pytrace=False
        )


def _check_private_recording(tmp_path, replay, kind, fixtures):
    files = list(fixtures.glob(f"*_{kind}*.txt*"))
    if not files:
        raise ValueError("Requested private recording is missing")
    reference = files[0].read_bytes()
    text = reference.decode("utf-16")
    frames = split_reference_frames(text)
    if kind == "resetsoc":
        exchanges = []
        for frame in frames:
            match = re.match(r"([^\r\n]+)\n\r@", frame)
            command = match[1] if match else ""
            exchanges.append((command, reply(frame, page=CONTINUATION in frame)))
        session = ScriptedSession(exchanges)
        result = BatteryClient(session=session).reset_soc(tmp_path / "reset.txt")
        assert not session.exchanges
    else:
        exchanges = []
        for frame in frames:
            match = re.match(r"([^\r\n]+)\n\r@", frame)
            command = match[1] if match else ""
            exchanges.append((command.encode("ascii") + b"\n", frame))
        session, transport = replay(exchanges, chunk_size=1024)
        client = BatteryClient(session=session)
        method = client.export_history if kind == "history" else client.export_events
        if kind == "history":
            from pylontech_tools.parsers import record_indices

            latest = record_indices(frames[2], detailed=True)
            expected_count = latest[-1] + 1
            observed = {
                i for frame in frames if frame.startswith("datalist") for i in record_indices(frame)
            }
            if set(range(expected_count)) - observed:
                # A damaged original capture must no longer pass completeness checks.
                with pytest.raises(ProtocolError, match="missing, repeated or unexpected"):
                    method(tmp_path / "report.txt")
                partial = (tmp_path / "report.txt").read_bytes()
                assert reference.startswith(partial)
                return
        result = method(tmp_path / "report.txt")
        assert not transport.exchanges
        if kind == "history":
            offsets = [int(cmd.split()[-1]) for cmd, _ in exchanges if cmd.startswith(b"datalist")]
            # Expected count comes from the private input at runtime, never a
            # device-specific counter embedded in the public test fixture.
            count_match = re.search(r"HisData Items\s*:\s*(\d+)", text)
            count = int(count_match[1])
            assert offsets == list(range(0, count, 15))
            assert result.records == count
    assert result.path.read_bytes() == reference
