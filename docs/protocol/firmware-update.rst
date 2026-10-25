Reset, shutdown and firmware updating
=====================================

.. _firmware-parameters-reset-shutdown-and-update:

Reset, shutdown and update
--------------------------

``trst``, ``shut`` and ``updata`` accept no operands and are available in user mode. They are
actions, not session-exit commands.

- ``trst``: E2 ``0x0802b024`` prepares state, masks faults and ultimately writes Cortex-M AIRCR
  with the key and SYSRESETREQ. It restarts the MCU; it does not itself mean “clear SOC” or
  “erase EEPROM.”
- ``shut``: E2 ``0x0800c498`` sets shutdown-related module flags; the master has a broadcast
  path and non-master handling differs. No “type twice to confirm” guard was found inside this
  handler. The supplement traces persistence/control steps and the
  ``Power Input OK, Cannot shut down!`` refusal path; power removal and wake sources depend on
  circuitry.
- ``updata``: writes boot marker ``0x55aa55aa`` at MCU flash ``0x0803f000``, checks status and
  resets. The receiver is in the missing bootloader region. The supplement now documents the PC
  sender’s handshake, 128-byte checksum frames, recovery flow and post-update operations;
  receiver validation/recovery guarantees remain unknown.

Do not automatically repeat state-changing commands after a timeout. For future implementation,
use the confirmed forms above, validate inputs more strictly than firmware, preserve specific
failure messages, and finish the explicitly unresolved handler/callback analysis before exposing
additional write operations.

.. _firmware-behavior-reset-shutdown-and-the-missing-update-receiver:

Reset, shutdown and the missing update receiver
-----------------------------------------------

E2 ``trst`` sets reset/system-event flags, creates a history record, persists both state blocks,
then reaches the Cortex-M reset request. Erase commands are not an implicit part of reset. This
explains why a software reset can save runtime changes before restarting.

E2 ``shut`` sets a shutdown flag. On module 1 it initiates broadcast address FF and sets manager
state 2 or 3 according to rack state; non-master execution calls ``0x08014ecc`` directly. That
sequence requests measurement/control operations, creates a history record, updates shutdown
statistics and persists state. It changes output/control flags, waits, and can return with
**``Power Input OK, Cannot shut down!``** (``0x0801507a``). The footer therefore does not prove
that power was removed. There is no two-command confirmation guard in the handler. Actual loss
of power and subsequent wake sources depend on external power and board circuitry; an unpowered
MCU cannot report its own wake logic through this application. Neither a reliable “off after N
seconds” guarantee nor a universal wake sequence follows from these application images alone.

E2 ``updata`` at ``0x08028d1e``:

1. Prints the version and restart notice and invokes module control operation ``0x13`` with
   zero.
2. Prepares MCU flash at **0x0803f000**, unlocks flash control and writes marker **0x55aa55aa**
   there.
3. Checks programming status **6**. Failure relocks and returns 1; success relocks, delays 1000
   helper units and requests system reset.

It does **not** receive a firmware image through this console handler. The reviewed images begin
at **0x08003800**; the preceding bootloader region ``0x08000000..0x080037ff`` is absent. The
marker page is also outside the E2 image payload. The application bytes cannot establish
receiver validation, flash-write ordering, power-failure recovery or update-mode timeout. The
archive also contains a PC updater; its sender protocol is now traced in
:ref:`the updater analysis below <firmware-behavior-pc-updater-transfer-protocol>`. That
establishes sender behavior, not the missing receiver implementation. No live update was
attempted.

.. _firmware-behavior-pc-updater-transfer-protocol:

PC updater transfer protocol
----------------------------

This section is based on **static managed-code inspection**, not a captured battery session. It
closes the sender-side portion of the bootloader gap using ``Update Tool.exe`` from the supplied
archive. SHA-256: ``dc78709db0c9694ae102e5415bece656b93e30dec27fc2b8722491e6050a5cfb``. The
accompanying ``UpdateConfig.xml`` has SHA-256
``d71a2249f8fd7be2296b5585a8650330450b5e7fa6135d50d761dbe4e2629777``. Neither file nor any
original log is copied into this repository.

.. _firmware-behavior-normal-update-handshake-and-framing:

Normal update handshake and framing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``MsgBackgroundWorker.OnUpdate`` (method RVA **``0xfe24``**) reads ``info``, prepares the
selected image and waits for **NAK ``0x15``** in the receive buffer. While waiting it sends
configured command **``updata``** every 10000 iterations of a loop that sleeps 1 ms, stopping
after more than 30000 iterations. These are iteration-based approximate timings, not a
bootloader timeout specification. After detecting the start marker it changes baud to configured
**115200** if needed, waits **1000 ms**, then transfers frames.

The active path calls **``XModemData.Fill``** (RVA **``0x113d4``**), not the method named
``Fill_Xmodem1k``. It constructs frames as follows:

============ =================================================================
Part         Bytes / rule
============ =================================================================
Start        **``01``**.
Block number ``(zero_based_frame_index + 1) mod 256``.
Complement   ``255 − block_number``.
Payload      **128 bytes**, sequential file bytes padded with **``1a``**.
Checksum     **One byte: sum(payload) & ff**; excludes the three header bytes.
============ =================================================================

For a synthetic one-byte input ``02``, the payload is ``02`` followed by 127 ``1a`` bytes and
the checksum is **``e8``**. This example uses invented bytes, not an original firmware payload
or battery log.

Each frame is therefore **132 bytes**. ``XmodemFrame.get_Frame`` (RVA **``0x10e38``**) assembles
this layout. The count is explicitly **``floor(file_length / 128) + 1``**, so an exactly aligned
file gets a whole extra padding frame. That is observed sender behavior, not a requirement
proven from the receiver. A future implementation must make the compatibility choice explicit
rather than accidentally changing the trailing-frame behavior.

``TransBinFile`` (RVA **``0x10534``**) sleeps **10 ms** between frames by the compiled default.
The first attempt for frame zero waits **10 seconds**; later attempts use configured **2
seconds**. ``SendPackage`` (RVA **``0x107b0``**) calls the raw byte-array send overload at RVA
**``0xae90``**: it writes the entire frame without an appended CR/newline and converts its
timeout argument to milliseconds. Thus a generic text-command sender would be incorrect here.

.. _firmware-behavior-replies-retries-and-completion:

Replies, retries and completion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+-----------------------------------------------+-----------------------------------------------+
| Value / text                                  | Sender interpretation                         |
+===============================================+===============================================+
| **``06`` ACK**                                | Accept frame and advance.                     |
+-----------------------------------------------+-----------------------------------------------+
| **``15`` NAK**                                | Retry the same frame. The ordinary response   |
|                                               | check tests NAK before ACK, so NAK wins if    |
|                                               | both occur in the response.                   |
+-----------------------------------------------+-----------------------------------------------+
| **``18`` CAN**                                | Has a cancellation-result branch in           |
|                                               | ``SendPackage``; see the event-matching       |
|                                               | limitation below.                             |
+-----------------------------------------------+-----------------------------------------------+
| Three consecutive NAKs or ``updata again``    | Classified by the timeout/error path as an    |
|                                               | update/restart condition, rather than an      |
|                                               | ordinary single-frame NAK.                    |
+-----------------------------------------------+-----------------------------------------------+
| ``back to``                                   | Classified by that path as return to the      |
|                                               | application.                                  |
+-----------------------------------------------+-----------------------------------------------+
| **``04`` EOT**                                | Sent once as a raw byte after the frames;     |
|                                               | this path does not wait for an EOT ACK.       |
+-----------------------------------------------+-----------------------------------------------+

The retry loop resends the **same buffered frame**, with compiled/configured
``ResendCount = 20``. It performs one initial send, then retries and increments its counter
**before checking whether that retry succeeded**. With repeated ordinary NAKs/timeouts it can
therefore attempt **22 writes**, not 20: one initial attempt and 21 retries, with retry 21
rejected by the ``counter > 20`` check. Even an ACK on that final retry is rejected by this
ordering. Earlier terminal results can stop sooner. A new implementation should define an exact
attempt budget and accept a valid ACK before deciding to retry; this is a sender off-by-one bug,
not an inferred receiver requirement.

The completion event matcher for packets is registered as pattern **8**, with ACK and NAK
regular expressions only (``PylonSerialPort.InitialPatternDict``, RVA **``0x9efc``**). Although
``SendPackage`` checks CAN in a completed response, this does not establish immediate handling
of a **CAN-only** response. The actual pattern-8 predicate in ``isReceivedInvalid`` (RVA
**``0x9ffc``**) explicitly tests only ACK/NAK. Furthermore, ``TransBinFile`` does not terminate
on cancellation result 2: that result falls through to its retry logic. Do not copy either
omission or present this as complete cancellation support.

After normal transfer, ``OnUpdate`` reconnects through ``DoUpdataFinish`` (RVA **``0x109b4``**)
without waiting for the configured completion text. The recovery path below instead waits for
the finish pattern, compiled as case-insensitive **``ok``**, for the configured **5 seconds**.
These two success paths differ. Neither proves that the receiver validates the full image before
executing it.

.. _firmware-behavior-recovery-and-post-update-operations:

Recovery and post-update operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``OnReUpdate`` (RVA **``0x101b8``**) prompts for a power cycle, repeatedly sends text
**``pylon``** with a **50 ms** sleep, and looks for **``BootLoader version``**. The loop stops
after its counter exceeds 600. It then clears receive state and waits for NAK using another 1
ms/30000-iteration loop, waits 100 ms, and uses the same 128-byte transfer routine. This is
evidence for the PC tool’s boot-entry handshake, not an application console command or a general
console recovery sequence. ``StartByteFlag = 43,15,15`` exists in the configuration loader, but
these reviewed update paths do not send that configured byte array.

Post-transfer work is separate from image transfer:

- Conditional EEPROM clearing uses configured **``eepe 0``**, checks the success text, sends
  **``trst``**, and reconnects. The branch is controlled by ``WillClrEEprom``; a configuration
  flag alone does not prove that branch runs.
- Conditional barcode restoration uses the saved pre-update identity, or asks for one if
  unavailable. The supplied configuration enables this and names **``tmbar``**, which is **not
  registered in either reviewed application image**. Do not silently treat it as an alias of
  ``tbar`` or carry this configuration into the Python client.
- The tool finally rereads battery information. Transfer completion, reconnect, optional
  clearing and identity restoration have separate outcomes; a single UI completion event is not
  evidence that all succeeded.

The image loader also distinguishes inputs: ZIP selection invokes board/device and version
checks (``UpdateInfo.VerifyBinFile``, RVA **``0x6360``**), using version at file offset
**``0x400``** and an 11-byte board field at **``0x418``**. The raw-bin branch of ``Fill`` opens
the file directly and bypasses that ZIP-selection check. These are PC checks, not proof of
receiver-side authentication or validation.

The unused ``Fill_Xmodem1k`` method builds 1024-byte payloads with a two-byte CRC, but the frame
assembler still hardcodes start byte ``01``. It is not evidence that the battery accepts
standard 1K/CRC mode. No active update path inspected here calls it. An implementation should
follow the verified active framing, not choose a protocol variant from this method’s name.

Receiver flash ranges, image-integrity checks, duplicate-block handling, cancellation behavior,
restart limits, and power-failure guarantees still need the matching bootloader or a validated
protocol experiment. The findings above are a sender contract only; no firmware update was
executed.
