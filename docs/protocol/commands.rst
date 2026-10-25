Firmware command inventory
==========================

.. _firmware-commands-notation-and-dispatch-rules:

Notation and dispatch rules
---------------------------

``L`` means registered in the local table; ``R`` means registered in the remote table. ``—``
means absent from that image’s command tables. A local and a remote entry can have different
metadata, so the JSON retains both rather than collapsing them.

========= ============= ==============================
Mode code Required mask Available in session modes
========= ============= ==============================
U         ``0x01``      User, config, equipment, debug
C         ``0x03``      Config or debug
E         ``0x05``      Equipment or debug
D         ``0x0f``      Debug only
========= ============= ==============================

E2 ``help`` at ``0x08024d66`` and local/remote lookup at ``0x08024cbe``/``0x08024d12`` require
``(session_mask & command_mask) == command_mask``. ``login`` at ``0x08025578`` sets masks 3/5/15
for config/equipment/debug; ``logout`` returns to mask 1. The C handlers have the corresponding
mask checks. Access does not describe safety: for example, ``trst``, ``shut`` and ``updata`` are
U commands.

The firmware’s **maximum token count includes the command name**. It is not a minimum-argument
count: handlers decide whether no-argument calls read status or fail. Do not infer valid
arguments merely from that maximum. Firmware help contains omissions and inconsistencies
highlighted below. Syntax in the tables is a compact guide; exact original help and limits are
in the JSON. ``<...>`` marks a value/choice and ``[...]`` an optional or incompletely specified
argument. Numeric base, value units, signedness, range and persistence are not globally uniform
and remain unverified unless a note explicitly establishes them.

``V`` means a relevant part of the handler was inspected, with confirmed details below; it does
not mean all branches and arguments have been validated. ``H`` means the description is based on
the registered help and command name. Unknown acronyms and undocumented argument meanings are
left unresolved.

.. _firmware-commands-command-inventory:

Command inventory
-----------------

.. _firmware-commands-session-and-communications:

Session and communications
~~~~~~~~~~~~~~~~~~~~~~~~~~

+-----------------------------------+------------------+------------------+------------------+------------------+
| Command / compact syntax          | Purpose          | E2               | C                | Evidence         |
+===================================+==================+==================+==================+==================+
| ``help [command]``                | List accessible  | L:U              | L:U              | V                |
|                                   | local/remote     |                  |                  |                  |
|                                   | commands, or     |                  |                  |                  |
|                                   | show help for    |                  |                  |                  |
|                                   | one name.        |                  |                  |                  |
+-----------------------------------+------------------+------------------+------------------+------------------+
| ``login <mode>``                  | Enter config,    | L/R:U            | L/R:U            | V                |
|                                   | equipment or     |                  |                  |                  |
|                                   | debug mode from  |                  |                  |                  |
|                                   | user mode.       |                  |                  |                  |
+-----------------------------------+------------------+------------------+------------------+------------------+
| ``logout``                        | Return to user   | L/R:U            | L/R:U            | V                |
|                                   | mode.            |                  |                  |                  |
+-----------------------------------+------------------+------------------+------------------+------------------+
| ``ci``                            | Show current     | L:D              | L:D              | H                |
|                                   | communications   |                  |                  |                  |
|                                   | information.     |                  |                  |                  |
+-----------------------------------+------------------+------------------+------------------+------------------+
| ``ct <port>``                     | Dump a buffered  | L:D              | L:D              | V                |
|                                   | protocol frame   |                  |                  |                  |
|                                   | for decimal port |                  |                  |                  |
|                                   | 0 or 1.          |                  |                  |                  |
+-----------------------------------+------------------+------------------+------------------+------------------+
| ``lg <cstm\|sys> <en\|dis>``      | Control LG       | L:D              | L:D              | V                |
|                                   | customer/system  |                  |                  |                  |
|                                   | compatibility    |                  |                  |                  |
|                                   | state.           |                  |                  |                  |
+-----------------------------------+------------------+------------------+------------------+------------------+
| ``setprt <sma\|lg>``              | Select the       | L:C              | L:C              | V                |
|                                   | inverter         |                  |                  |                  |
|                                   | communication    |                  |                  |                  |
|                                   | protocol.        |                  |                  |                  |
+-----------------------------------+------------------+------------------+------------------+------------------+
| ``urates <500000\|115200\|9600>`` | Set the RS485    | L:C              | L:C              | V                |
|                                   | port rate; this  |                  |                  |                  |
|                                   | is not the       |                  |                  |                  |
|                                   | console baud     |                  |                  |                  |
|                                   | setting.         |                  |                  |                  |
+-----------------------------------+------------------+------------------+------------------+------------------+

.. _firmware-commands-identity-measurements-and-status:

Identity, measurements and status
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+-----------------------------+-------------------+------------------+------------------+------------------+
| Command / compact syntax    | Purpose           | E2               | C                | Evidence         |
+=============================+===================+==================+==================+==================+
| ``info``                    | Show identity,    | L/R:U            | L/R:U            | H                |
|                             | firmware, barcode |                  |                  |                  |
|                             | and module        |                  |                  |                  |
|                             | specification.    |                  |                  |                  |
+-----------------------------+-------------------+------------------+------------------+------------------+
| ``bmicrdcfg <total-ic>``    | Read              | L:D              | L:D              | V                |
|                             | battery-monitor   |                  |                  |                  |
|                             | IC configuration  |                  |                  |                  |
|                             | for the requested |                  |                  |                  |
|                             | IC count.         |                  |                  |                  |
+-----------------------------+-------------------+------------------+------------------+------------------+
| ``bmicrdcomm <total-ic>``   | Read              | L:D              | L:D              | V                |
|                             | battery-monitor   |                  |                  |                  |
|                             | IC communication  |                  |                  |                  |
|                             | data for the      |                  |                  |                  |
|                             | requested IC      |                  |                  |                  |
|                             | count.            |                  |                  |                  |
+-----------------------------+-------------------+------------------+------------------+------------------+
| ``bat [pwr] [index]``       | Show battery/cell | L:U              | L:U              | V                |
|                             | readings; exact   |                  |                  |                  |
|                             | selection         |                  |                  |                  |
|                             | defaults are      |                  |                  |                  |
|                             | handler-specific. |                  |                  |                  |
+-----------------------------+-------------------+------------------+------------------+------------------+
| ``pwr [index]``             | Show module power | L:U              | L:U              | V                |
|                             | summaries,        |                  |                  |                  |
|                             | including absent  |                  |                  |                  |
|                             | rack slots.       |                  |                  |                  |
+-----------------------------+-------------------+------------------+------------------+------------------+
| ``getpwr [index]``          | Show detailed     | L:U              | L:U              | V                |
|                             | module/cell       |                  |                  |                  |
|                             | readings in       |                  |                  |                  |
|                             | hash-delimited    |                  |                  |                  |
|                             | form; checks      |                  |                  |                  |
|                             | optional module   |                  |                  |                  |
|                             | selection.        |                  |                  |                  |
+-----------------------------+-------------------+------------------+------------------+------------------+
| ``pwrsys [argument]``       | Show system       | L:E              | L:E              | V                |
|                             | status or         |                  |                  |                  |
|                             | selected module   |                  |                  |                  |
|                             | charge/discharge  |                  |                  |                  |
|                             | recommendations.  |                  |                  |                  |
+-----------------------------+-------------------+------------------+------------------+------------------+
| ``soh [addr]``              | Show state of     | R:U              | L/R:U            | V                |
|                             | health;           |                  |                  |                  |
|                             | remote-only in    |                  |                  |                  |
|                             | E2, local and     |                  |                  |                  |
|                             | remote in C.      |                  |                  |                  |
+-----------------------------+-------------------+------------------+------------------+------------------+
| ``tsoh``                    | Read-only SOH     | —                | L:E              | V                |
|                             | event-count test; |                  |                  |                  |
|                             | C only.           |                  |                  |                  |
+-----------------------------+-------------------+------------------+------------------+------------------+
| ``disp [selection...]``     | Select background | L:U              | L:U              | V                |
|                             | module/cell       |                  |                  |                  |
|                             | display; zero     |                  |                  |                  |
|                             | stops it.         |                  |                  |                  |
+-----------------------------+-------------------+------------------+------------------+------------------+
| ``euro [arguments...]``     | Euro metrics      | L:U              | L:U              | V                |
|                             | report, optional  |                  |                  |                  |
|                             | module selection, |                  |                  |                  |
|                             | or mutating       |                  |                  |                  |
|                             | clear.            |                  |                  |                  |
+-----------------------------+-------------------+------------------+------------------+------------------+
| ``eurostub [arguments...]`` | Report,           | L:U              | L:U              | V                |
|                             | initialize or     |                  |                  |                  |
|                             | inject runtime    |                  |                  |                  |
|                             | Euro test slots.  |                  |                  |                  |
+-----------------------------+-------------------+------------------+------------------+------------------+

.. _firmware-commands-recorded-data-and-counters:

Recorded data and counters
~~~~~~~~~~~~~~~~~~~~~~~~~~

+--------------------------------------------+--------------------+------------------+------------------+------------------+
| Command / compact syntax                   | Purpose            | E2               | C                | Evidence         |
+============================================+====================+==================+==================+==================+
| ``stat``                                   | Show record        | L/R:U            | L/R:U            | V                |
|                                            | counts,            |                  |                  |                  |
|                                            | SOC/coulomb fields |                  |                  |                  |
|                                            | and                |                  |                  |                  |
|                                            | operating/fault    |                  |                  |                  |
|                                            | counters.          |                  |                  |                  |
+--------------------------------------------+--------------------+------------------+------------------+------------------+
| ``statc``                                  | Clear most runtime | L/R:C            | L/R:C            | V                |
|                                            | statistics,        |                  |                  |                  |
|                                            | preserving         |                  |                  |                  |
|                                            | selected counters; |                  |                  |                  |
|                                            | invokes a state    |                  |                  |                  |
|                                            | callback. Not      |                  |                  |                  |
|                                            | EEPROM erase.      |                  |                  |                  |
+--------------------------------------------+--------------------+------------------+------------------+------------------+
| ``data <kind> [item]``                     | Show a recorded    | L/R:U            | L/R:U            | V                |
|                                            | item; the          |                  |                  |                  |
|                                            | no-item/default    |                  |                  |                  |
|                                            | path is            |                  |                  |                  |
|                                            | handler-dependent. |                  |                  |                  |
+--------------------------------------------+--------------------+------------------+------------------+------------------+
| ``datalist <kind> [selection...]``         | List recorded      | L:U              | L:U              | V                |
|                                            | data; handler also |                  |                  |                  |
|                                            | supports the       |                  |                  |                  |
|                                            | unadvertised dtls  |                  |                  |                  |
|                                            | form.              |                  |                  |                  |
+--------------------------------------------+--------------------+------------------+------------------+------------------+
| ``datac [event\|history\|event_log\|use]`` | Clear record       | L:C              | L:C              | V                |
|                                            | metadata; explicit |                  |                  |                  |
|                                            | event/history also |                  |                  |                  |
|                                            | enters flash       |                  |                  |                  |
|                                            | erasure, while     |                  |                  |                  |
|                                            | bare form resets   |                  |                  |                  |
|                                            | both counts.       |                  |                  |                  |
+--------------------------------------------+--------------------+------------------+------------------+------------------+
| ``save [event\|history]``                  | Request a record;  | L:D              | L:D              | V                |
|                                            | defaults to event. |                  |                  |                  |
+--------------------------------------------+--------------------+------------------+------------------+------------------+
| ``log [data]``                             | Show internal      | L:U              | L:U              | V                |
|                                            | diagnostic log     |                  |                  |                  |
|                                            | information.       |                  |                  |                  |
+--------------------------------------------+--------------------+------------------+------------------+------------------+
| ``logc``                                   | Clear internal log | L:C              | L:C              | V                |
|                                            | count/wrap         |                  |                  |                  |
|                                            | bookkeeping; E2    |                  |                  |                  |
|                                            | writes chip-0      |                  |                  |                  |
|                                            | offset 0x387.      |                  |                  |                  |
+--------------------------------------------+--------------------+------------------+------------------+------------------+
| ``logt <data>``                            | Generate test log  | L:D              | L:D              | V                |
|                                            | data.              |                  |                  |                  |
+--------------------------------------------+--------------------+------------------+------------------+------------------+
| ``tclear``                                 | Clear record       | L:E              | L:E              | V                |
|                                            | indices and        |                  |                  |                  |
|                                            | runtime            |                  |                  |                  |
|                                            | statistics;        |                  |                  |                  |
|                                            | persist both state |                  |                  |                  |
|                                            | blocks.            |                  |                  |                  |
+--------------------------------------------+--------------------+------------------+------------------+------------------+
| ``tcycle [cycle-times]``                   | Set/test the       | L:D              | L:D              | V                |
|                                            | cycle-count value; |                  |                  |                  |
|                                            | do not treat as a  |                  |                  |                  |
|                                            | read.              |                  |                  |                  |
+--------------------------------------------+--------------------+------------------+------------------+------------------+

.. _firmware-commands-configuration-protection-and-soc:

Configuration, protection and SOC
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+------------------------------------------------------+---------------------+------------------+------------------+------------------+
| Command / compact syntax                             | Purpose             | E2               | C                | Evidence         |
+======================================================+=====================+==================+==================+==================+
| ``config [key] [values...]``                         | Read/change         | L/R:C            | L/R:C            | V                |
|                                                      | protection and      |                  |                  |                  |
|                                                      | scheduling          |                  |                  |                  |
|                                                      | parameters;         |                  |                  |                  |
|                                                      | includes            |                  |                  |                  |
|                                                      | save/default        |                  |                  |                  |
|                                                      | actions.            |                  |                  |                  |
+------------------------------------------------------+---------------------+------------------+------------------+------------------+
| ``prot [key] [en\|dis]``                             | Read/change         | L/R:C            | L/R:C            | V                |
|                                                      | protection          |                  |                  |                  |
|                                                      | enablement;         |                  |                  |                  |
|                                                      | includes default    |                  |                  |                  |
|                                                      | and smart-charge    |                  |                  |                  |
|                                                      | controls.           |                  |                  |                  |
+------------------------------------------------------+---------------------+------------------+------------------+------------------+
| ``ctrl [target] [value]``                            | Read/control FETs,  | L/R:C            | L/R:C            | V                |
|                                                      | outputs and test    |                  |                  |                  |
|                                                      | flags; handler      |                  |                  |                  |
|                                                      | supports more       |                  |                  |                  |
|                                                      | targets than help   |                  |                  |                  |
|                                                      | lists.              |                  |                  |                  |
+------------------------------------------------------+---------------------+------------------+------------------+------------------+
| ``couls [iah\|vah\|asic\|default]``                  | Select/report       | R:D              | R:D              | V                |
|                                                      | coulomb calculation |                  |                  |                  |
|                                                      | mode; registered    |                  |                  |                  |
|                                                      | only in the remote  |                  |                  |                  |
|                                                      | table.              |                  |                  |                  |
+------------------------------------------------------+---------------------+------------------+------------------+------------------+
| ``autoswitch [1\|0]``                                | Read/control        | L:D              | L:D              | V                |
|                                                      | automatic-switching |                  |                  |                  |
|                                                      | enablement.         |                  |                  |                  |
+------------------------------------------------------+---------------------+------------------+------------------+------------------+
| ``setlowcfg [save\|shutsoc\|sstime] [num]``          | Read/set low-SOC    | L:D              | L:D              | V                |
|                                                      | shutdown settings;  |                  |                  |                  |
|                                                      | E2 save path        |                  |                  |                  |
|                                                      | reports             |                  |                  |                  |
|                                                      | unsupported.        |                  |                  |                  |
+------------------------------------------------------+---------------------+------------------+------------------+------------------+
| ``setsoc <0..100>``                                  | Set per-cell        | L:C              | L:C              | V                |
|                                                      | runtime remaining   |                  |                  |                  |
|                                                      | charge/SOC;         |                  |                  |                  |
|                                                      | distinct from       |                  |                  |                  |
|                                                      | BatteryView SOC     |                  |                  |                  |
|                                                      | reset.              |                  |                  |                  |
+------------------------------------------------------+---------------------+------------------+------------------+------------------+
| ``emptyvolt [val]``                                  | Read/set            | L/R:C            | L/R:C            | V                |
|                                                      | empty-voltage       |                  |                  |                  |
|                                                      | threshold; E2       |                  |                  |                  |
|                                                      | accepts 500–3300    |                  |                  |                  |
|                                                      | after u16           |                  |                  |                  |
|                                                      | conversion.         |                  |                  |                  |
+------------------------------------------------------+---------------------+------------------+------------------+------------------+
| ``blocksoc [val]``                                   | Read/set            | —                | L:C              | V                |
|                                                      | block-current SOC   |                  |                  |                  |
|                                                      | percentage; C       |                  |                  |                  |
|                                                      | accepts 1–100.      |                  |                  |                  |
+------------------------------------------------------+---------------------+------------------+------------------+------------------+
| ``totalcoul [val]``                                  | Read/set configured | L:C              | L:C              | V                |
|                                                      | nominal capacity;   |                  |                  |                  |
|                                                      | E2 accepts 50, 74   |                  |                  |                  |
|                                                      | or 100 Ah and       |                  |                  |                  |
|                                                      | stores chip-1 data. |                  |                  |                  |
+------------------------------------------------------+---------------------+------------------+------------------+------------------+
| ``time [yy MM dd hh mm ss]``                         | Read/set battery    | L:U              | L:U              | V                |
|                                                      | RTC; six date/time  |                  |                  |                  |
|                                                      | values when         |                  |                  |                  |
|                                                      | setting.            |                  |                  |                  |
+------------------------------------------------------+---------------------+------------------+------------------+------------------+
| ``cmudtesttime [year month day hour minute second]`` | Read/write EEPROM   | L:U              | L:U              | V                |
|                                                      | manufacturing-test  |                  |                  |                  |
|                                                      | timestamp; separate |                  |                  |                  |
|                                                      | from RTC.           |                  |                  |                  |
+------------------------------------------------------+---------------------+------------------+------------------+------------------+

.. _firmware-commands-eeprom-external-flash-and-memory:

EEPROM, external flash and memory
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+-------------------------------------------+------------------+------------------+------------------+------------------+
| Command / compact syntax                  | Purpose          | E2               | C                | Evidence         |
+===========================================+==================+==================+==================+==================+
| ``eepe <chip>``                           | Overwrite the    | L:D              | L:D              | V                |
|                                           | selected logical |                  |                  |                  |
|                                           | EEPROM with      |                  |                  |                  |
|                                           | zeros: 2048      |                  |                  |                  |
|                                           | bytes in both    |                  |                  |                  |
|                                           | images.          |                  |                  |                  |
+-------------------------------------------+------------------+------------------+------------------+------------------+
| ``eepr <chip> <offset> <size>``           | Read bytes:      | L:D              | L:D              | V                |
|                                           | decimal          |                  |                  |                  |
|                                           | chip/count,      |                  |                  |                  |
|                                           | hexadecimal      |                  |                  |                  |
|                                           | offset.          |                  |                  |                  |
+-------------------------------------------+------------------+------------------+------------------+------------------+
| ``eepw <chip> <offset> <value> [repeat]`` | Repeat a byte;   | L:D              | L:D              | V                |
|                                           | offset, value    |                  |                  |                  |
|                                           | and optional     |                  |                  |                  |
|                                           | repeat are       |                  |                  |                  |
|                                           | hexadecimal.     |                  |                  |                  |
+-------------------------------------------+------------------+------------------+------------------+------------------+
| ``flae <chip>``                           | Erase selected   | L:D              | L:D              | V                |
|                                           | external flash;  |                  |                  |                  |
|                                           | not the same     |                  |                  |                  |
|                                           | storage          |                  |                  |                  |
|                                           | operation as     |                  |                  |                  |
|                                           | eepe.            |                  |                  |                  |
+-------------------------------------------+------------------+------------------+------------------+------------------+
| ``flar <chip> <offset> <size>``           | Read external    | L:D              | L:D              | V                |
|                                           | flash.           |                  |                  |                  |
+-------------------------------------------+------------------+------------------+------------------+------------------+
| ``flaw <chip> <offset> <value>``          | Write external   | L:D              | L:D              | V                |
|                                           | flash.           |                  |                  |                  |
+-------------------------------------------+------------------+------------------+------------------+------------------+
| ``md <width> <address> <size>``           | Dump MCU         | L:D              | L:D              | V                |
|                                           | address-space    |                  |                  |                  |
|                                           | contents,        |                  |                  |                  |
|                                           | potentially      |                  |                  |                  |
|                                           | including        |                  |                  |                  |
|                                           | peripheral       |                  |                  |                  |
|                                           | registers.       |                  |                  |                  |
+-------------------------------------------+------------------+------------------+------------------+------------------+
| ``mm <width> <address> <value>``          | Write MCU        | L:D              | L:D              | V                |
|                                           | address-space    |                  |                  |                  |
|                                           | contents,        |                  |                  |                  |
|                                           | potentially      |                  |                  |                  |
|                                           | including        |                  |                  |                  |
|                                           | peripheral       |                  |                  |                  |
|                                           | registers.       |                  |                  |                  |
+-------------------------------------------+------------------+------------------+------------------+------------------+

.. _firmware-commands-fuel-gauge-registers-and-calibration:

Fuel-gauge registers and calibration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+----------------------------------------+-----------------------------+------------------+------------------+------------------+
| Command / compact syntax               | Purpose                     | E2               | C                | Evidence         |
+========================================+=============================+==================+==================+==================+
| ``inar <offset>``                      | Read INA226 register;       | L:D              | —                | V                |
|                                        | actual name differs from    |                  |                  |                  |
|                                        | socr in its help.           |                  |                  |                  |
+----------------------------------------+-----------------------------+------------------+------------------+------------------+
| ``inaw <offset> <value>``              | Write INA226 register; help | L:D              | —                | V                |
|                                        | calls this socw.            |                  |                  |                  |
+----------------------------------------+-----------------------------+------------------+------------------+------------------+
| ``inash``                              | Show INA226 registers; help | L:D              | —                | V                |
|                                        | calls this socsh.           |                  |                  |                  |
+----------------------------------------+-----------------------------+------------------+------------------+------------------+
| ``inacal <arguments...>``              | INA226 current-calibration  | L:D              | —                | V                |
|                                        | handler; help incorrectly   |                  |                  |                  |
|                                        | names currcal and omits a   |                  |                  |                  |
|                                        | possible argument.          |                  |                  |                  |
+----------------------------------------+-----------------------------+------------------+------------------+------------------+
| ``currcal [value]``                    | Separate                    | L:D              | —                | V                |
|                                        | current-calibration         |                  |                  |                  |
|                                        | handler; do not alias to    |                  |                  |                  |
|                                        | inacal.                     |                  |                  |                  |
+----------------------------------------+-----------------------------+------------------+------------------+------------------+
| ``socr <offset>``                      | Read C-image fuel-gauge     | —                | L:D              | V                |
|                                        | register.                   |                  |                  |                  |
+----------------------------------------+-----------------------------+------------------+------------------+------------------+
| ``socw <offset> <value>``              | Write C-image fuel-gauge    | —                | L:D              | V                |
|                                        | register.                   |                  |                  |                  |
+----------------------------------------+-----------------------------+------------------+------------------+------------------+
| ``socsh``                              | Show C-image fuel-gauge     | —                | L:D              | V                |
|                                        | registers.                  |                  |                  |                  |
+----------------------------------------+-----------------------------+------------------+------------------+------------------+
| ``soccfg <subclass> <offset> <value>`` | Write fuel-gauge            | —                | L:D              | V                |
|                                        | subclass/data               |                  |                  |                  |
|                                        | configuration.              |                  |                  |                  |
+----------------------------------------+-----------------------------+------------------+------------------+------------------+
| ``soccal <quantity> <value>``          | Calibrate                   | —                | L:D              | V                |
|                                        | voltage/current/temperature |                  |                  |                  |
|                                        | or current-counter/board    |                  |                  |                  |
|                                        | offsets.                    |                  |                  |                  |
+----------------------------------------+-----------------------------+------------------+------------------+------------------+
| ``socd [arguments...]``                | Show fuel-gauge data; table | —                | L:D              | V                |
|                                        | permits two arguments       |                  |                  |                  |
|                                        | absent from help.           |                  |                  |                  |
+----------------------------------------+-----------------------------+------------------+------------------+------------------+
| ``socclr [argument]``                  | Clear bq34z100 data flash   | —                | L:C              | V                |
|                                        | and reload defaults         |                  |                  |                  |
|                                        | according to help; separate |                  |                  |                  |
|                                        | from eepe.                  |                  |                  |                  |
+----------------------------------------+-----------------------------+------------------+------------------+------------------+
| ``soct [arguments...]``                | Show fuel-gauge Ra table;   | —                | L:D              | V                |
|                                        | table permits two arguments |                  |                  |                  |
|                                        | absent from help.           |                  |                  |                  |
+----------------------------------------+-----------------------------+------------------+------------------+------------------+
| ``tsoc``                               | Gauge test that can run     | —                | L:E              | V                |
|                                        | embedded programming script |                  |                  |                  |
|                                        | and reset; C only.          |                  |                  |                  |
+----------------------------------------+-----------------------------+------------------+------------------+------------------+

.. _firmware-commands-reset-power-control-and-firmware-transfer:

Reset, power control and firmware transfer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+------------------+-------------------------+------------------+------------------+------------------+
| Command /        | Purpose                 | E2               | C                | Evidence         |
| compact syntax   |                         |                  |                  |                  |
+==================+=========================+==================+==================+==================+
| ``trst``         | Soft system reset; E2   | L:U              | L:U              | V                |
|                  | ultimately requests     |                  |                  |                  |
|                  | Cortex-M SYSRESETREQ.   |                  |                  |                  |
+------------------+-------------------------+------------------+------------------+------------------+
| ``shut``         | Request shutdown;       | L:U              | L:U              | V                |
|                  | confirmation/repetition |                  |                  |                  |
|                  | behavior must follow    |                  |                  |                  |
|                  | the handler.            |                  |                  |                  |
+------------------+-------------------------+------------------+------------------+------------------+
| ``tsoftdsg``     | Run soft-discharge test | L:D              | L:D              | V                |
|                  | routine; distinct from  |                  |                  |                  |
|                  | ordinary status reads.  |                  |                  |                  |
+------------------+-------------------------+------------------+------------------+------------------+
| ``updata``       | Write bootloader marker | L:U              | L:U              | V                |
|                  | and reset; PC transfer  |                  |                  |                  |
|                  | protocol is traced in   |                  |                  |                  |
|                  | the supplement, but the |                  |                  |                  |
|                  | receiver is absent from |                  |                  |                  |
|                  | these images.           |                  |                  |                  |
+------------------+-------------------------+------------------+------------------+------------------+

.. _firmware-commands-manufacturing-and-hardware-tests:

Manufacturing and hardware tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+----------------------------------------+--------------------+------------------+------------------+------------------+
| Command / compact syntax               | Purpose            | E2               | C                | Evidence         |
+========================================+====================+==================+==================+==================+
| ``tbar <barcode>``                     | Validate/write     | L:E              | L:E              | V                |
|                                        | barcode; E2        |                  |                  |                  |
|                                        | requires 16        |                  |                  |                  |
|                                        | alphanumeric       |                  |                  |                  |
|                                        | characters and     |                  |                  |                  |
|                                        | checks selected    |                  |                  |                  |
|                                        | cell-count cases.  |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tbuz``                               | Run buzzer test.   | L:E              | L:E              | V                |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tchgc [current [limit]]``            | Charge-current     | L:E              | L:E              | V                |
|                                        | test; E2 and C     |                  |                  |                  |
|                                        | argument limits    |                  |                  |                  |
|                                        | differ.            |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tdisc [current [limit]]``            | Discharge-current  | L:E              | L:E              | V                |
|                                        | test; E2 and C     |                  |                  |                  |
|                                        | argument limits    |                  |                  |                  |
|                                        | differ.            |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tvolt [value]``                      | Cell voltage test; | L:E              | L:E              | V                |
|                                        | E2 optional value  |                  |                  |                  |
|                                        | is allowed spread  |                  |                  |                  |
|                                        | in mV.             |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tpwr``                               | Test total module  | —                | L:E              | V                |
|                                        | voltage; C only.   |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``ttmp [value]``                       | Cell temperature   | L:E              | L:E              | V                |
|                                        | test; E2 optional  |                  |                  |                  |
|                                        | value is allowed   |                  |                  |                  |
|                                        | spread in mC.      |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tetmp``                              | Compare two        | L:E              | L:E              | V                |
|                                        | temperature        |                  |                  |                  |
|                                        | sensors against    |                  |                  |                  |
|                                        | the                |                  |                  |                  |
|                                        | cell-temperature   |                  |                  |                  |
|                                        | average; E2        |                  |                  |                  |
|                                        | accepts −10/+30 °C |                  |                  |                  |
|                                        | offsets.           |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tinput <rv\|dcov\|absent\|present>`` | Test selected      | L:E              | L:E              | V                |
|                                        | input condition;   |                  |                  |                  |
|                                        | present/absent     |                  |                  |                  |
|                                        | branches invoke    |                  |                  |                  |
|                                        | hardware           |                  |                  |                  |
|                                        | callbacks.         |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tmos <cfet\|dfet>``                  | Test selected      | L:E              | L:E              | V                |
|                                        | MOSFET.            |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``teepr``                              | EEPROM write/read  | L:E              | L:E              | V                |
|                                        | test; E2           |                  |                  |                  |
|                                        | temporarily writes |                  |                  |                  |
|                                        | 0x55 at offset     |                  |                  |                  |
|                                        | 0x26 on both       |                  |                  |                  |
|                                        | chips, then        |                  |                  |                  |
|                                        | restores it.       |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tflash``                             | Destructive        | L:E              | L:E              | V                |
|                                        | sector-zero        |                  |                  |                  |
|                                        | erase/program      |                  |                  |                  |
|                                        | test; also clears  |                  |                  |                  |
|                                        | record metadata.   |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``ti2c``                               | Run I2C test       | L:E              | L:E              | V                |
|                                        | routine.           |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tcan``                               | Run CAN test; help | L:E              | L:E              | H                |
|                                        | advertises port#   |                  |                  |                  |
|                                        | but table rejects  |                  |                  |                  |
|                                        | additional tokens. |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tusart``                             | Run USART test     | L:E              | L:E              | V                |
|                                        | routine.           |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tdip <expected>``                    | Compare DIP-switch | L:E              | L:E              | V                |
|                                        | state with a       |                  |                  |                  |
|                                        | decimal value      |                  |                  |                  |
|                                        | 0–15.              |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tled <selector> [on\|off]``          | Test/control LEDs  | L:E              | L:E              | V                |
|                                        | using selector 0,  |                  |                  |                  |
|                                        | LED number or      |                  |                  |                  |
|                                        | on/off per help.   |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tibcio <nc\|sc>``                    | Test IBC I/O;      | L:E              | L:E              | V                |
|                                        | nc/sc meanings are |                  |                  |                  |
|                                        | not expanded by    |                  |                  |                  |
|                                        | firmware help.     |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tcbnio <nc\|sc>``                    | Test CBN I/O;      | L:E              | L:E              | V                |
|                                        | nc/sc meanings are |                  |                  |                  |
|                                        | not expanded by    |                  |                  |                  |
|                                        | firmware help.     |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tmprctrl <flag> [bat-id value]``     | Inject runtime     | L:D              | L:D              | V                |
|                                        | temperature,       |                  |                  |                  |
|                                        | voltage or a       |                  |                  |                  |
|                                        | monitor-reference  |                  |                  |                  |
|                                        | diagnostic by      |                  |                  |                  |
|                                        | selector; short    |                  |                  |                  |
|                                        | form restores      |                  |                  |                  |
|                                        | measurement flags. |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tsto``                               | Report cached      | —                | L:E              | V                |
|                                        | self-test faults;  |                  |                  |                  |
|                                        | C only, no output  |                  |                  |                  |
|                                        | drive.             |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tver <version>``                     | Compare            | —                | L:E              | V                |
|                                        | hexadecimal value  |                  |                  |                  |
|                                        | with actual        |                  |                  |                  |
|                                        | software version;  |                  |                  |                  |
|                                        | C only, does not   |                  |                  |                  |
|                                        | set it.            |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tdct``                               | Run dry-contact    | L:E              | L:E              | V                |
|                                        | test.              |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tbld``                               | Run                | L:E              | L:E              | V                |
|                                        | bleeding/balancing |                  |                  |                  |
|                                        | test; help         |                  |                  |                  |
|                                        | advertises val but |                  |                  |                  |
|                                        | table accepts no   |                  |                  |                  |
|                                        | extra token.       |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``twdg``                               | Stop feeding       | L:E              | L:E              | H                |
|                                        | watchdog; help     |                  |                  |                  |
|                                        | says wdg but only  |                  |                  |                  |
|                                        | twdg is            |                  |                  |                  |
|                                        | registered.        |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``tagevolt``                           | Run aging-voltage  | —                | L:E              | V                |
|                                        | test; C only.      |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+
| ``trdagevolt``                         | Read recorded      | L:E              | L:E              | V                |
|                                        | aging-voltage      |                  |                  |                  |
|                                        | extrema/history.   |                  |                  |                  |
+----------------------------------------+--------------------+------------------+------------------+------------------+

.. _firmware-parameters-reading-the-contracts:

Reading the contracts
---------------------

- ``D``: unsigned decimal; ``S``: signed decimal; ``H``: hexadecimal, with an optional
  ``0x``/``0X`` prefix. Bare ``10`` means sixteen in an H parameter and ten in a D parameter.
- ``[argument]`` is optional. Values in braces are literal choices. Commands and selectors are
  case-sensitive string comparisons unless stated otherwise.
- ``u8``/``u16`` describe firmware truncation to 8/16 bits, **not a recommended input range**. A
  client should reject overflow instead of reproducing it.
- Storage addresses are byte offsets on the named logical chip. A direct EEPROM write is
  persistent; a runtime update alone does not prove either persistence or loss on reboot because
  other tasks can save state later.
- A successful console footer only means the handler returned zero. Several tests and drivers
  print failure and still return zero. Preserve their output and interpret the
  operation-specific result.

The E2 unsigned conversion routine is ``0x08019d2e``: it checks digits against the requested
base, accumulates a 32-bit value, and reports invalid/trailing input through a caller-provided
error pointer. It rejects nine or more digits after stripping an optional hexadecimal prefix.
The signed wrapper at ``0x08019e08`` recognizes a leading minus. Some callers do not provide
robust error handling; validate complete tokens, signs, lengths and bounds before sending them.
Do not use malformed inputs to discover firmware limits.

The table’s token ceiling includes the command word. It does not establish a minimum: some
storage handlers load missing operands without checking them. Remote addressing is a frontend
operation: for eligible commands, ``command N ...`` can remove decimal module address N before
the handler sees the remaining arguments. The forms here describe those **remaining handler
arguments**.
