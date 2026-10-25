Console sessions, framing and addressing
========================================

.. _protocol-connection-and-framing:

Connection and framing
----------------------

``ConnConfig.xml`` enables console-mode switching at 1200 baud using these bytes:

.. code:: text

   7E 32 30 30 31 34 36 38 32 43 30 30 34 38 35 32 30 46 43 43 33 0D

``ShifttoConsole`` waits 500 ms after sending the frame, restores the selected console baud
rate, waits another 500 ms, then sends an empty command to find a ``pylon`` prompt. The UI
defaults to 115200 baud. Serial settings include 8 data bits and one stop bit. Vendor
initialization sends ``login debug``, then ``info``. The Python client skips that login when
synchronization already ends at ``pylon_debug>``, since redundant login can be rejected. From
the base prompt it sends login once and checks the last complete prompt, accepting a rejected
login only if the final prompt confirms debug mode. The reset script’s explicit
post-reconnection login remains part of its saved transcript.

Regular response patterns recognize ``pylon>`` and ``$$`` followed by a ``pylon_debug>`` prompt.
History mode additionally recognizes:

.. code:: text

   Press [Enter] to be continued,other key to exit

The Python framer recognizes both prompt variants and buffers fragmented reads. It collects
trailing bytes until a short quiet interval after a terminator, preserving CR/LF even when a
serial read splits the prompt from its terminator. As in the original console, only one command
may be outstanding.

Regular ``SerialPort.WriteLine`` calls send LF. The script overload with its final boolean
enabled uses ``Write(command)`` followed by a single CR. Pagination sends the string CR through
``WriteLine``, producing CR+LF. These are different console actions and must not be normalized
to the host OS’s default newline.

After a timeout, the session requires explicit prompt resynchronization before another nonempty
command. It does not automatically repeat a command whose outcome is unknown.

.. _protocol-disconnect-button:

Disconnect button
-----------------

Both the menu and toolbar Disconnect buttons queue a message handled by
``MsgBackgroundWorker.OnDisconnectBatMangeSystems``. It disables scan scheduling, waits up to
ten seconds for pending scan rows to be saved when its queue is nonempty, clears pending
messages, and stops application logging.

With ``IsNeedCmdQuit="true"`` (the bundled connection setting), it then invokes
``Send("cmdquit", ResponsePattern.Disconnect, 5)``. That overload sends LF through
``SerialPort.WriteLine`` and waits up to five seconds. The disconnect regex is just ``cmdquit``,
so an echo suffices; it does not verify a new prompt or operating mode. The port is
closed/disposed in a finally block even after a command error or timeout. The separate shutdown
operation sends ``shut`` twice; disconnect sends no shutdown, reset, or EEPROM command.

Some firmware responds with ``Unknown command`` when sent ``cmdquit``. The Python client
classifies that response as a rejection and logs it explicitly, while retaining the original
echo-based wait and unconditional port cleanup. A received echo therefore does not establish
that console mode actually ended.

The Python client performs this command and wait on ``BatteryClient.close()`` and
context-manager exit, using a separate disconnect boundary that does not require a prompt. It
sends ``cmdquit`` once even if the previous command left framing unsynchronized, without
repeating the previous command or adding synchronization traffic. Disconnect/port-close errors
are logged without masking an earlier failure, and repeated closes are idempotent. Failed
connection setup uses the low-level ``ConsoleSession.close()`` to release the port immediately.

Python operations already share a synchronous session lock, and report writes are flushed before
their methods return. There is no background scan queue requiring an additional ten-second drain
wait. Disconnect responses are not vendor report content; they are visible in explicitly enabled
serial tracing.

.. _protocol-monitoring:

Monitoring
----------

``OnGetpwrs`` uses ``getpwr`` for a single module, or ``getpwr N`` for addressed reads, plus
``pwr`` for the module table. Extended queries include ``pwr N``, ``pwrsys N``, and system
``pwrsys``; some are optional or disabled by configuration. Module authorization for
parameter/protection operations uses ``login N debug``, while identity and monitoring reads
include their addresses explicitly.

The Python ``pwr`` parser accepts both tables and labeled summaries headed by ``Power N``. The
latter identifies the connected module’s reported address, not an installation size. Labels
include ``Voltage``, ``Current``, ``Temperature``, ``Coulomb``, ``Total Coulomb``, and status
fields. Voltages, currents, temperatures, and capacities are divided by 1000; percent SOC is
unscaled. Status labels are normalized to the existing state keys, while original fields,
protection labels, and event masks remain in ``raw``. A labeled block requires a numeric address
and recognizable voltage; optional missing fields remain absent. Its event masks are not assumed
to share the hash-format error-code bit mapping.

Python’s default auto mode acquires local ``getpwr`` first, then discovers modules with ``pwr``.
Single mode uses the local reading and profile-enabled extensions; parallel mode starts with the
table and addressed detail reads. Explicit ``--module`` reads use ``info N``, ``getpwr N`` and
profile-enabled ``pwr N``/``pwrsys N``. Profiles for UP2500 and 2500LFP2 use unaddressed
``pwrsys`` and disable the optional ``pwr`` extension in single mode. System ``pwrsys`` is read
once where enabled. A single labeled address does not imply that preceding addresses exist. The
snapshot merge keeps capacity from ``pwr`` if detailed reads omit it. ``Unknown command``
replies are recognized as unsupported; optional ``pwrsys`` can then be omitted without losing
the other snapshot readings.

``RegoutConfig.xml`` describes voltage/current/temperature scaling by 1000. ``getpwr`` begins
with eight hash-delimited fields: voltage, current, temperature, capacity, basic state, voltage
state, current state, temperature state. Cell records contain voltage, temperature, voltage
state, temperature state. The configured trailing fields are error code and cycle count. Known
error bits are decoded using ``Indicator.xml``, and unknown bits remain visible. The library
also preserves the full hash sequence, including other firmware trailers. Native profiles share
the eight scalar/four cell-field layout; US2K uses the last trailer pair, while the other
supported layouts use the first pair after the cell block. Labeled replies normalize module
states, SOC and error codes too. Extrema use zero-based cell indices; system aggregates require
values from every observed module rather than silently treating missing values as zero.

Bundled native profiles are selected by ``Device name``, with an explicit override and a generic
fallback for unknown models. They encode supported fields/scales, extension enablement and
addressing from the default and model-specific XML. They do not execute XML or enable the
original’s disabled SOH queries.

Definitions cannot be mechanically reused: .NET variable-length lookbehinds are incompatible
with Python’s standard regex engine, some XML declarations misidentify their encoding, some type
definitions are inconsistent, and configuration limit expressions contain apparent typos. Python
parsing uses labels/headers and retains unrecognized fields rather than substituting zero.

.. _firmware-commands-routing-framing-and-implementation-notes:

Routing, framing and implementation notes
-----------------------------------------

.. _firmware-commands-local-and-remote-selection:

Local and remote selection
~~~~~~~~~~~~~~~~~~~~~~~~~~

For remote-capable names the frontend recognizes a decimal module address as the first argument:
``command N remaining-arguments``. The E2 dispatcher at ``0x080251f6``–``0x080252ac`` removes
the address before invoking the local handler when it matches the current module, forwards other
targets when connected to module 1, or reports a target mismatch on a non-master. Forwarding can
report ``Target device is Busy`` or ``Target device is not present``; retain these as specific
operational failures rather than generic parse errors. Python raises ``DeviceBusyError``
or ``DeviceNotPresentError`` for these replies, including replies with a success
footer. They do not trigger automatic retries or unsupported-command fallback.

The remote tables contain ``config``, ``ctrl``, ``data``, ``emptyvolt``, ``info``, ``login``,
``logout``, ``prot``, ``couls``, ``soh``, ``stat`` and ``statc``. **A remote-table entry alone
does not guarantee direct-console invocation:** the inspected frontend first requires a
local-table match. In particular, ``couls`` is remote-only in both images, and E2 ``soh`` is
remote-only. The reviewed E2 text frontend therefore rejects these names before their handlers
run; no alternate public text spelling was found.

``pwr [index]`` and ``getpwr [index]`` have their own selection behavior and are not registered
in the remote table. The E2 ``getpwr`` handler at ``0x0800ef84`` accepts a selected index,
checks presence from module 1, and otherwise requires the current module’s index. Do not
generalize either mechanism into a global selection effect from ``login N debug``.

.. _firmware-commands-response-boundaries-and-retries:

Response boundaries and retries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The E2 dispatcher at ``0x080252be``–``0x08025320`` checks the token ceiling and calls the
handler. A zero return produces ``Command completed successfully``; nonzero produces
``Invalid command or fail to excute.`` and usage. Unknown or inaccessible names can produce
``Unknown command``. Normal replies use ``@``, ``$$`` and a mode-dependent ``pylon...>`` prompt;
paginated output additionally uses the continuation message documented in
:doc:`protocol notes </protocol/index>`.

A successful handler return is not proof of hardware effect: ``tbar``, for example, also prints
an independent test result. Read an operation-specific result and verify state when implementing
a write. Tests, calibration, configuration, record creation/clearing, storage writes and
reset/update operations must not inherit automatic read retries. A name beginning with ``t`` is
not a read-only classification, and ``teepr`` actively writes to EEPROM.

.. _firmware-commands-recorded-data-selectors:

Recorded-data selectors
~~~~~~~~~~~~~~~~~~~~~~~

The registered ``data``/``datalist`` help lists these kinds:

.. code:: text

   event history pov puv plv bov buv inputov coc coca doc doca sc use

``data <kind> [item]`` retrieves an individual/default item. The detailed-list handler
recognizes ``datalist <kind> dtls <item>`` despite omitting ``dtls`` from help (E2 comparison at
``0x0800ba8a``). Actual E2 field forms are ``datalist kind bat field start`` and
``datalist kind bat cell field start``; ``item`` is not a recognized literal. The supplement
records zero-based cell selection, current scaling differences and paging behavior. The ``use``
path can report its recording interval in days.

Do not confuse event/history records with the separate internal ``log`` ring. ``datac``
advertises ``event/history/event_log/use``; ``logc`` resets log bookkeeping. The string ``misc``
is absent from both images. The BatteryView reset script sends it, but that is not evidence
these revisions support it.

.. _firmware-commands-protection-and-configuration-selectors:

Protection and configuration selectors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The decoded ``config`` selector array has **66 names** in both images. The help lists most of
them without explaining all units or relationships. Names ending in ``r`` must not be
automatically interpreted as recovery thresholds without checking the corresponding handler
branch.

.. code:: text

   pov povr phv phvr plv plvr puv puvr pslp
   bov bovr bhv bhvr blv blvr buv buvr bslp bsv bv
   bot botr bht bhtr blt bltr but butr
   coc coca cocar
   eot eotr eht ehtr elt eltr eut eutr
   doc doca docar ocd ocr oc2d oc2r sc scd scr clc
   recinv shuttime uvtime save default recuse idle
   sleep record hwsleep
   softtime mot motr cocp docp ocpd

The final six names above are present in the selector table but omitted from help. In E2,
``softtime``, ``cocp``, ``docp`` and ``ocpd`` dispatch directly to a successful exit without
implementing a setting. Recognized names do not guarantee effects. Exact selector order and
source addresses are retained in the JSON.

The advertised scheduling forms are
``[sleep/record] [on/off/day/week/month] [starttime] [endtime]`` and
``hwsleep [on/off] [sleeptime] [wakeuptime]``.

The decoded ``prot`` array has **34 selectors** in both images, with ``en``/``dis`` actions. Its
exact list is:

.. code:: text

   default bov bhv blv buv bslp
   cbot cbht cblt cbut dbot dbht dblt dbut
   pov phv plv puv pslp pot pht plt put
   sc doc2 doc doca coca coc coc2 buzz smartchg lcoul mot

``bslp``, ``pslp``, ``lcoul`` and ``mot`` are recognized by this array but omitted from its
help. The decoded ``ctrl`` array has **11 targets** in both images:

.. code:: text

   cfet dfet buzz heat pwmc pwmp softstart i2c afuse agelog mostest

``pwmc``, ``pwmp``, ``softstart``, ``i2c``, ``agelog`` and ``mostest`` are absent from help.
Actions/values are target-specific: do not infer PWM units or I2C semantics from these names.
The no-argument ``ctrl`` path displays status. Its E2 output also includes ``CFETFLAG``,
``DFETFLAG``, ``SOFT`` and ``dryct1``–``dryct4``; these display labels are **not** additional
selectors in that array. Ordinary output branches use ``on``/``off``, while other targets
require separate handler review.

The decoded ``datalist`` field-selector array is ``id``, ``volt``, ``curr``, ``temp``, ``coul``
in both images. This is separate from the record-kind strings and from the ``item``/``bat``
syntax advertised in help. The arrays prove recognized names, not that every argument
combination will succeed.

.. _firmware-commands-confirmed-state-changing-details:

Confirmed state-changing details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **``eepe``:** both images accept chip 0/1 and zero 2048 bytes in 16-byte writes. This is broad
  EEPROM clearing. See the :ref:`field map <protocol-confirmed-e2-persistent-fields>`.
- **``setsoc``:** E2 validates 0–100, then updates per-cell runtime coulomb and percentage
  fields at ``0x0800fc0a``–``0x0800fc40``. This handler has no EEPROM write call; later periodic
  persistence is a separate question. This is not the erase-and-reset sequence used by
  BatteryView’s SOC-reset button.
- **``totalcoul``:** E2’s no-value path reads nominal capacity from chip 1 offset ``0x021``. The
  setter accepts 50/74/100 Ah, writes the capacity and check byte, and updates related model
  data. Do not substitute arbitrary learned capacity.
- **``setlowcfg``:** E2’s no-argument path reports ``ShutSoc`` and ``ShutSocTime``;
  ``shutsoc``/``sstime`` change their runtime fields. ``sstime`` is stored internally in
  two-second increments (``value >> 1``, displayed ``stored << 1``). The ``save`` path
  explicitly prints ``LowConfig Save Not Support``; a zero return does not mean persistent
  configuration was saved.
- **``statc``:** E2 clears 60 halfwords starting at module-structure offset ``0x08c``, restores
  fields at ``0x0ce``, ``0x0de`` and ``0x0e0`` (reset, life-warning and life-alarm counts), then
  calls the module’s ``+0x280`` callback via ``0x080073dc``. The resolved callback immediately
  attempts a 124-byte write to EEPROM 0 ``0x38f``; the statc handler ignores the driver status.
  It does not preserve all statistics and is not an alias for ``datac`` or ``eepe``.
- **``logc``:** E2 zeros internal log index/wrap state and writes a two-byte count at EEPROM-0
  offset ``0x387``; that is bookkeeping clearing, not a proven erase of every underlying log
  record.
- **``teepr``:** E2 reads, overwrites with ``0x55``, reads back, and restores one byte at offset
  ``0x026`` on each EEPROM chip. Restoration attempts do not make this a passive diagnostic.
- **``tbar``:** E2 requires a 16-character alphanumeric barcode. It checks selected
  fourth-character/cell-count combinations, writes chip 0 offset ``0x021``, then reads it back
  and prints ``Test result:pass`` or failure. Other revisions may accept different serial
  formats.
- **``trst``:** E2 prepares state, masks faults, and requests a Cortex-M system reset. It is
  unrelated to ``logout`` and to closing a host serial handle.

These handler observations are E2-specific unless both images are explicitly mentioned. Shared
names/help do not establish identical hardware effects.

.. _firmware-parameters-session-and-communication:

Session and communication
-------------------------

+-----------------------------------------------+-----------------------------------------------+
| Form                                          | Parameters, defaults and effect               |
+===============================================+===============================================+
| ``help [name]``                               | With no name, lists commands accessible in    |
|                                               | the current mode. With a name, prints its     |
|                                               | help. Help is not a reliable argument         |
|                                               | specification.                                |
+-----------------------------------------------+-----------------------------------------------+
| ``login {config\|equipment\|debug}``          | Valid from user mode; sets access mask 3, 5   |
|                                               | or 15. An already elevated session reports    |
|                                               | ``Quit current mode``; it does not silently   |
|                                               | switch modes. Unknown modes report            |
|                                               | ``wrong mode``.                               |
+-----------------------------------------------+-----------------------------------------------+
| ``logout``                                    | Returns to user mask 1. Does not close the    |
|                                               | host serial port or request a reset.          |
+-----------------------------------------------+-----------------------------------------------+
| ``ci``                                        | No operands. Displays communication state;    |
|                                               | distinct from the buffered-frame dump below.  |
+-----------------------------------------------+-----------------------------------------------+
| ``ct port``                                   | Port is D, **0 or 1**. Dumps a buffered       |
|                                               | protocol frame, including SOI, VER, ADR,      |
|                                               | CID1/CID2/RTN, LENGTH, CHKSUM and EOI. The    |
|                                               | inspected handler does not enable a           |
|                                               | continuous trace stream.                      |
+-----------------------------------------------+-----------------------------------------------+
| ``urates [rate]``                             | No argument reports the unit/RS485-port rate. |
|                                               | D rate must be **9600, 115200 or 500000**. A  |
|                                               | changed value is written as four bytes to     |
|                                               | EEPROM 0 at ``0x7ae`` and cached in RAM. The  |
|                                               | handler does not reconfigure the UART; see    |
|                                               | the supplement for driver initialization and  |
|                                               | hardware-selected rate behavior. This is not  |
|                                               | the console baud rate.                        |
+-----------------------------------------------+-----------------------------------------------+
| ``setprt [sma\|lg]``                          | No argument reports the selected protocol.    |
|                                               | The setter changes protocol-related runtime   |
|                                               | settings and writes a byte at EEPROM 0        |
|                                               | ``0x7ab``. Immediately changes live protocol  |
|                                               | callbacks and CAN configuration; see the      |
|                                               | supplement for function addresses and         |
|                                               | 500000-rate activation.                       |
+-----------------------------------------------+-----------------------------------------------+
| ``lg [cstm\|sys en\|dis]``                    | No arguments reports customer/system CAN-ID   |
|                                               | state. Setters use separate EEPROM-1          |
|                                               | flags/check bytes: customer ``0x3a/0x3b``,    |
|                                               | system ``0x3c/0x3d``; enabled marker          |
|                                               | ``0x55``, disabled marker zero. These flags   |
|                                               | are not a console baud setting.               |
+-----------------------------------------------+-----------------------------------------------+

Evidence: E2 ``login`` ``0x08025578``, ``logout`` ``0x08025604``, ``ct`` ``0x0801e0f8``; other
entry addresses are in the catalog JSON.

.. _firmware-parameters-module-and-cell-selection:

Module and cell selection
-------------------------

``pwr``, ``getpwr``, ``bat`` and ``pwrsys`` implement their own selection; do not infer a
persistent selected module from a previous ``login N debug``. Module 1 has rack
lookup/forwarding behavior; non-master modules often accept only their own address. Presence
checks matter independently of numeric bounds.

+-----------------------------------------------+-----------------------------------------------+
| Form                                          | Parameters, defaults and output               |
+===============================================+===============================================+
| ``info``                                      | No handler operands; identity, versions,      |
|                                               | barcode and specifications. Remote module     |
|                                               | address, when used, belongs to the frontend.  |
+-----------------------------------------------+-----------------------------------------------+
| ``pwr [module]``                              | Module is D. On module 1, no argument prints  |
|                                               | the rack table, including absent slots; an    |
|                                               | explicit module is checked for presence. On a |
|                                               | non-master, selection must match the current  |
|                                               | module. Readings use native mV, mA, mC and    |
|                                               | percent fields.                               |
+-----------------------------------------------+-----------------------------------------------+
| ``getpwr [module]``                           | D selection, presence checked on the master;  |
|                                               | other modules require their own address. No   |
|                                               | selection uses the current module. Outputs    |
|                                               | hash-delimited details.                       |
|                                               | ``Device N is not present`` can coexist with  |
|                                               | a success footer.                             |
+-----------------------------------------------+-----------------------------------------------+
| ``bat [module [cell]]``                       | Both numbers are D. The first operand selects |
|                                               | a module, **not a cell**. The two-operand     |
|                                               | branch checks cell **0 through cell-count−1** |
|                                               | and directly indexes the cell array. No       |
|                                               | operands displays the current module’s cells; |
|                                               | one module operand displays that module’s     |
|                                               | cells.                                        |
+-----------------------------------------------+-----------------------------------------------+
| ``pwrsys [module]``                           | No argument displays system information on    |
|                                               | the master or local recommended               |
|                                               | charge/discharge values on another module.    |
|                                               | Explicit module is parsed D then narrowed to  |
|                                               | u8; the inspected lookup lacks a              |
|                                               | corresponding presence/null check. A client   |
|                                               | must validate the rack address and presence.  |
|                                               | Output includes recommended mV/mA limits.     |
+-----------------------------------------------+-----------------------------------------------+
| ``soh [module]``                              | D module selection and presence/own-address   |
|                                               | checks in the handler. E2 registration is     |
|                                               | remote-only, so the handler contract alone    |
|                                               | does not establish a working local-console    |
|                                               | spelling.                                     |
+-----------------------------------------------+-----------------------------------------------+
| ``stat``                                      | No handler operands. Displays record counts,  |
|                                               | operating/fault counts, cycle count, SOH and  |
|                                               | SOC/coulomb fields. Read these counts before  |
|                                               | enumerating records.                          |
+-----------------------------------------------+-----------------------------------------------+

Evidence: E2 ``bat`` ``0x080075a8``, ``pwr`` ``0x08007a1c``, ``getpwr`` ``0x0800ef84``.
``Power N`` in a selected summary is an address label, not proof of N installed modules. Reject
absent placeholders when building a collection list.
