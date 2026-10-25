Configuration, protection and controls
======================================

.. _firmware-parameters-protection-configuration-and-control:

Protection configuration and control
------------------------------------

.. _firmware-parameters-config-thresholds-are-related-not-independent-scalars:

``config``: thresholds are related, not independent scalars
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``config`` prints the full configuration. Most scalar selectors accept ``config key`` to read
and ``config key value`` to change runtime state. The common value parser is **signed decimal**,
so negative current/temperature values are meaningful. Numeric parsing is attempted before some
selector-specific string branches; a robust client must validate the intended form rather than
use the parser’s permissiveness.

E2 dispatch is at ``0x0800cc14``, using the selector order retained in JSON. Threshold branches
validate against **other current settings**, not just fixed minimum/maximum constants. The
following pack/cell-voltage bounds are taken from the comparisons, including endpoint
strictness:

======== ==== ===============================
Key      Unit Setter condition for value x
======== ==== ===============================
``pov``  mV   ``max(phv, povr) < x <= 65000``
``povr`` mV   ``20000 <= x < pov``
``phv``  mV   ``max(plv, phvr) < x < pov``
``phvr`` mV   ``20000 <= x < phv``
``plv``  mV   ``puv < x < min(phv, plvr)``
``plvr`` mV   ``plv < x < 65000``
``puv``  mV   ``pslp < x < min(plv, puvr)``
``puvr`` mV   ``puv < x <= 65000``
``pslp`` mV   ``20000 <= x < puv``
``bov``  mV   ``max(bhv, bovr) < x <= 7000``
``bovr`` mV   ``100 <= x < bov``
``bhv``  mV   ``max(blv, bhvr) < x < bov``
``bhvr`` mV   ``100 <= x < bhv``
``blv``  mV   ``buv < x < min(bhv, blvr)``
``blvr`` mV   ``blv < x <= 7000``
``buv``  mV   ``bslp < x < min(blv, buvr)``
``buvr`` mV   ``buv < x <= 7000``
``bslp`` mV   ``100 <= x < buv``
======== ==== ===============================

E2 pack/cell-voltage branches: ``0x0800cc9c``–``0x0800d1c2``. These limits describe firmware
acceptance, not recommended battery operating values.

The other selector groups and their confirmed units/roles are:

+-----------------------------------------------+-----------------------------------------------+
| Selectors                                     | Meaning and parameter status                  |
+===============================================+===============================================+
| ``bot botr bht bhtr blt bltr but butr``       | Battery temperature protection/recovery       |
|                                               | fields, mC; exact cross-field/constant bounds |
|                                               | and mirrored charge/discharge writes are in   |
|                                               | the supplement.                               |
+-----------------------------------------------+-----------------------------------------------+
| ``eot eotr eht ehtr elt eltr eut eutr``       | Environment temperature protection/alarm and  |
|                                               | recovery fields, mC; BatteryView explicitly   |
|                                               | labels ``eht/ehtr`` as environment            |
|                                               | high-temperature alarm/release. Exact bounds  |
|                                               | are in the supplement, including the          |
|                                               | legacy-field comparison mismatch and          |
|                                               | asymmetric endpoints.                         |
+-----------------------------------------------+-----------------------------------------------+
| ``mot motr``                                  | Board over-temperature protection/release     |
|                                               | according to BatteryView’s Forcel_C labels.   |
|                                               | Exact mC bounds are in the supplement;        |
|                                               | physical sensor wiring remains a hardware     |
|                                               | question.                                     |
+-----------------------------------------------+-----------------------------------------------+
| ``coc coca cocar``                            | Charge current protection/alarm/recovery      |
|                                               | values, mA; exact predicates, including       |
|                                               | rejected zero recovery value, are in the      |
|                                               | supplement.                                   |
+-----------------------------------------------+-----------------------------------------------+
| ``doc doca docar``                            | Discharge current protection/alarm/recovery   |
|                                               | values, **negative mA**; exact predicates and |
|                                               | strict zero exclusion are in the supplement.  |
+-----------------------------------------------+-----------------------------------------------+
| ``sc``                                        | Short-circuit threshold, negative mA:         |
|                                               | **−300000 <= x < min(0, doc, −coc)**.         |
|                                               | Strictly below both related thresholds.       |
+-----------------------------------------------+-----------------------------------------------+
| ``ocd ocr oc2d oc2r scd scr``                 | Protection delay/recovery values, ms; exact   |
|                                               | bounds and the ``oc2d`` signedness bug are    |
|                                               | listed below.                                 |
+-----------------------------------------------+-----------------------------------------------+
| ``clc``                                       | Current-limit value, mA: **1–10000            |
|                                               | inclusive**. Stores the same value in pack    |
|                                               | and cell parameter structures.                |
+-----------------------------------------------+-----------------------------------------------+
| ``bsv bv``                                    | Balancing-related voltage parameters, mV:     |
|                                               | **BSV 2800–3600 inclusive**, **BV 30–100      |
|                                               | inclusive**. Both endpoints confirmed by      |
|                                               | unsigned subtraction/range comparisons.       |
+-----------------------------------------------+-----------------------------------------------+
| ``recinv``                                    | D interval multiplier **1–65536 inclusive**.  |
|                                               | Displayed recording interval is the supplied  |
|                                               | multiplier times the module’s base interval;  |
|                                               | the raw value is not necessarily seconds.     |
+-----------------------------------------------+-----------------------------------------------+
| ``uvtime``                                    | D seconds **0–864000 inclusive** (ten days).  |
|                                               | Updates a runtime under-voltage timer field.  |
+-----------------------------------------------+-----------------------------------------------+
| ``recuse idle``                               | S values **1–365 inclusive**, displayed in    |
|                                               | days. Change the use-record interval /        |
|                                               | idle-time fields.                             |
+-----------------------------------------------+-----------------------------------------------+
| ``shuttime``                                  | E2 branch prints ``NO IDLE SHUT``; it does    |
|                                               | not implement the implied numeric setter.     |
+-----------------------------------------------+-----------------------------------------------+
| ``softtime cocp docp ocpd``                   | E2 jump-table entries point straight to the   |
|                                               | common successful exit. Recognized names,     |
|                                               | **no implemented setter/read branch** in this |
|                                               | image.                                        |
+-----------------------------------------------+-----------------------------------------------+
| ``save default``                              | Actions, described below; no numeric value.   |
+-----------------------------------------------+-----------------------------------------------+
| ``sleep record hwsleep``                      | Scheduling forms below.                       |
+-----------------------------------------------+-----------------------------------------------+

This accounts for all 66 selector-table names. Four recognized no-op selectors are especially
important: help/registration alone must not be treated as proof that a setting changed. E2 jump
table ``0x0800cc18``, common exit ``0x0800e8ee``.

``config save`` calls several parameter-save callbacks and writes the record interval field at
EEPROM 0 ``0x38d``. ``config default`` calls the corresponding restore-default callbacks,
changes scheduling values and writes that interval field too. These are state-changing actions,
not ways to display defaults. The supplement supplies the resolved word/check-byte storage map.
Neither is an erase of all settings. Branches ``0x0800e472``–``0x0800e5b2``.

.. _firmware-parameters-delayrecovery-limits-and-a-signedness-bug:

Delay/recovery limits and a signedness bug
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All setters have form ``config key value``, using the common **S** parser; the query form omits
value. Accepted conditions below describe the comparisons, not merely the diagnostic strings:

+-------------------------------+-------------------------------+-------------------------------+
| Key                           | Accepted value in             | E2 setter branch              |
|                               | milliseconds                  |                               |
+===============================+===============================+===============================+
| ``ocd``                       | 2000–300000 inclusive         | ``0x0800d6d8``                |
+-------------------------------+-------------------------------+-------------------------------+
| ``ocr``                       | 2000–300000 inclusive         | ``0x0800d744``                |
+-------------------------------+-------------------------------+-------------------------------+
| ``scd``                       | 0–31 inclusive                | ``0x0800d818``                |
+-------------------------------+-------------------------------+-------------------------------+
| ``scr``                       | 2000–300000 inclusive         | ``0x0800d860``                |
+-------------------------------+-------------------------------+-------------------------------+
| ``oc2d``                      | Signed comparison accepts     | ``0x0800e35c``                |
|                               | **any parsed value <= 5000**, |                               |
|                               | including negative values     |                               |
+-------------------------------+-------------------------------+-------------------------------+
| ``oc2r``                      | 500–60000 inclusive           | ``0x0800e3a8``                |
+-------------------------------+-------------------------------+-------------------------------+

The unsigned subtraction checks in the bounded branches reject negative values. ``oc2d`` instead
uses a signed ``< 5001`` comparison and has **no zero lower check**, despite printing
``0 ~ 5000 ms`` on error. Future clients should enforce 0–5000; the effect of a negative stored
delay on timer consumers remains unverified. Successful setters copy the raw value to pack and
cell parameter structures; there is no rounding at this point. Later timer resolution and
persistence are separate from the parser contract.

``clc`` bounds are at ``0x0800d8b4``; ``bsv``/``bv`` at ``0x0800e3f8``/``0x0800e44c``.

.. _firmware-parameters-scheduling-forms:

Scheduling forms
~~~~~~~~~~~~~~~~

E2 ``config sleep`` reads the sleep schedule; ``config sleep on`` / ``off`` toggles it. The
daily setter has separate hour/minute tokens:

.. code:: text

   config sleep day start-hour start-minute end-hour end-minute

All four numbers are D; normal values are hour 0–23, minute 0–59. Firmware narrows them to bytes
before checking. Start and end must differ; an end earlier than start sets an internal
next-period flag. Weekly/monthly forms and Monday=1 weekday numbering are now documented in the
supplement. ``config record`` has corresponding on/off/day/week/month paths; do not assume its
state polarity matches sleep.

Hardware sleep uses a **different syntax than the help suggests**:

.. code:: text

   config hwsleep
   config hwsleep on
   config hwsleep off
   config hwsleep sleep-seconds wake-seconds

The two-number form uses D, requires **sleep 5–10 inclusive** and **wake >= 7**, and enables
hardware sleep. No upper wake bound was found in this branch. It does not require an additional
``on`` token. Display labels explicitly use seconds. E2 branches ``0x0800dd64``–``0x0800de3a``.

.. _firmware-parameters-prot-ctrl-autoswitch-couls:

``prot``, ``ctrl``, ``autoswitch``, ``couls``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``prot`` displays protection state. ``prot default`` requests defaults. ``prot key en`` /
``prot key dis`` choose a named protection enable bit, not a numeric threshold. The
:ref:`34-selector list <firmware-commands-protection-and-configuration-selectors>` includes
battery charge/discharge temperature protections separately, pack protections, buzzer and
smart-charge controls. The masks are not simply ``1 << selector_index``: the jump table maps
names to bits with gaps. E2 handler ``0x0800e96c``, selector dispatch ``0x0800ea0c``. Mask
persistence uses callback 0x19 and its two EEPROM blocks, as traced in the supplement;
electrical meanings still require board context.

``ctrl`` displays state. E2 accepts ``ctrl target`` queries and, for implemented setters,
``ctrl target on|off`` or the numeric form below. Dispatch is at ``0x080297ca``; the common
parser turns ``on`` into 1 and ``off`` into 0. Invalid other action strings are rejected except
on the numeric PWM paths.

+-----------------------------------------------+-----------------------------------------------+
| Target                                        | Handler behavior and limits                   |
+===============================================+===============================================+
| ``cfet``, ``dfet``                            | Query reads output state. ``on``/``off``      |
|                                               | invoke different module-control operation     |
|                                               | codes; these are active charge/discharge-path |
|                                               | controls.                                     |
+-----------------------------------------------+-----------------------------------------------+
| ``buzz``                                      | Query reads GPIO state; ``on``/``off``        |
|                                               | directly sets/clears the buzzer GPIO.         |
+-----------------------------------------------+-----------------------------------------------+
| ``heat``                                      | Query reports OFF. Setter branches go to the  |
|                                               | common exit without changing hardware in E2.  |
+-----------------------------------------------+-----------------------------------------------+
| ``pwmc``                                      | Query reports state and a percentage with one |
|                                               | decimal place. D numeric setter clamps to     |
|                                               | **0–1000**, representing **0.0–100.0%**;      |
|                                               | ``on``/``off`` also parse but store 1/0 in    |
|                                               | the same numeric field. The setter changes a  |
|                                               | runtime field, not a proven PWM-enable flag.  |
+-----------------------------------------------+-----------------------------------------------+
| ``pwmp``                                      | Numeric parser clamps to **20000–200000**,    |
|                                               | but the E2 dispatch entry goes straight to    |
|                                               | the exit; no implemented effect. Do not infer |
|                                               | frequency units or a working setter.          |
+-----------------------------------------------+-----------------------------------------------+
| ``softstart``                                 | Query reads GPIO. Both ``on`` and ``off``     |
|                                               | reach a branch that compares the **argument   |
|                                               | count with 1**, instead of the parsed action. |
|                                               | Since a setter has three total tokens, both   |
|                                               | take the same output-control path. Treat as a |
|                                               | firmware bug, not a reliable Boolean setter.  |
+-----------------------------------------------+-----------------------------------------------+
| ``i2c``                                       | Bare target **clears bit 0 of I2C1 control    |
|                                               | register at 0x40005400**, disabling the       |
|                                               | peripheral; it is **not a status query**. The |
|                                               | ``on``/``off`` forms do not reach that call.  |
|                                               | Helper ``0x0802b958`` has no restore step.    |
+-----------------------------------------------+-----------------------------------------------+
| ``afuse``                                     | Passes inverse on/off state to module         |
|                                               | callback operation ``0x29``, then reports the |
|                                               | cached AFUSE flag. The handler prints         |
|                                               | ``Nonsupport currlimit mode`` as well;        |
|                                               | persistent EEPROM markers/GPIO effects are    |
|                                               | now traced in the supplement; the physical    |
|                                               | circuit action remains board-specific.        |
|                                               | BatteryView labels ``ctrl afuse off`` “Clear  |
|                                               | AFuse Error” and refers to a three-terminal   |
|                                               | fuse. Bare target follows the same            |
|                                               | default-zero action path rather than a pure   |
|                                               | query.                                        |
+-----------------------------------------------+-----------------------------------------------+
| ``agelog``                                    | Query reads EEPROM 0 ``0x7b7``; marker        |
|                                               | ``0x5a`` enables the cached flag. Setter      |
|                                               | persists ``0x5a`` for on, zero for off.       |
+-----------------------------------------------+-----------------------------------------------+
| ``mostest``                                   | Query reads EEPROM 0 ``0x7f4`` and EEPROM 1   |
|                                               | ``0x2a``; either ``0x5a`` marker enables the  |
|                                               | cached flag. Setter writes both locations     |
|                                               | with ``0x5a`` or zero. The flag gates active  |
|                                               | background fault checks that can invoke       |
|                                               | AFUSE, record an event and persist state; see |
|                                               | the supplement for thresholds and conditions. |
|                                               | BatteryView first checks cell voltages and    |
|                                               | their sum before enabling it; its guard and   |
|                                               | parsing bug are documented in the protocol    |
|                                               | reference.                                    |
+-----------------------------------------------+-----------------------------------------------+

These observations are specific to E2 ``0x08029500``–``0x08029bcc``. Display labels such as
``CFETFLAG``, ``DFETFLAG`` and ``dryct1``–``dryct4`` are not additional selectors. Several
**bare target forms change state**, so they cannot all be exposed as read-only queries.

``autoswitch`` queries the EEPROM-0 byte at ``0x7fa``. Setters accept **literal strings**
``autoswitch 0`` or ``autoswitch 1``, not arbitrary decimal representations. Zero stores **0x5a
= OFF**, one stores **0 = ON**, updates RAM and reads the byte back for reporting. E2
``0x0800fce8``–``0x0800fd8c``; this inverted stored marker is not an ordinary persisted Boolean.

``couls [iah|vah|asic|default]`` advertises coulomb-calculation modes but is remote-only in both
images; the supplement maps runtime mode numbers and confirms rejection by the normal E2
local-first frontend.

.. _firmware-behavior-remaining-configuration-comparisons:

Remaining configuration comparisons
-----------------------------------

These are E2 **setter acceptance conditions**, using the signed-decimal value x. They describe
the code’s limits, not recommended operating thresholds. Named fields mean the related current
setting unless a raw field offset is specified.

======== ====================================
Key      Condition (mC)
======== ====================================
``bot``  ``max(bht, botr) < x <= 100000``
``botr`` ``−40000 <= x < bot``
``bht``  ``max(blt, bhtr) < x < bot``
``bhtr`` ``−40000 <= x < bht``
``blt``  ``but < x < min(bht, bltr)``
``bltr`` ``blt < x <= 100000``
``but``  ``−40000 <= x < min(butr, blt)``
``butr`` ``but < x <= 100000``
``eot``  ``max(P[0x2c], eotr) < x <= 100000``
``eotr`` ``−40000 <= x < eot``
``eht``  ``ehtr < x <= 100000``
``ehtr`` ``−40000 <= x < eht``
``elt``  ``eut < x < min(eltr, P[0x2c])``
``eltr`` ``elt < x <= 100000``
``eut``  **``−39999 <= x < min(eutr, elt)``**
``eutr`` **``eut < x < 100000``**
``mot``  ``motr < x < 100000``
``motr`` **``−39999 <= x < mot``**
======== ====================================

Battery-temperature setters mirror their values into both charge and discharge parameter fields.
Environment OT/LT branches similarly mirror selected fields. Do not promise independent
charge/discharge thresholds through these setters.

``P`` is the pack parameter structure. **Reported ``eht`` is at P+0xb8**, while the EOT/ELT
comparisons above read **P+0x2c**, a distinct legacy field. Their error messages suggest EHT but
the code does not compare against the reported EHT field. These mismatches and asymmetric
−39999/100000 endpoints must not be “corrected” in a description of actual firmware behavior.

Evidence: E2 battery branches ``0x0800d1c6``–``0x0800d456``, environment/MOT
``0x0800e5b4``–``0x0800e878``. Physical mapping of the extra MOT sensor still depends on board
wiring; these offsets and mC comparisons are established independently.

========= =========================================================================
Key       Condition (mA)
========= =========================================================================
``coc``   ``coca < x``, ``x < −sc``, ``x <= 150000``
``coca``  ``cocar < x < coc``
``cocar`` **``1 <= x < coca``**, despite the message advertising a lower bound of 0
``doc``   ``−150000 <= x``, ``sc < x < doca``
``doca``  ``doc < x < docar``
``docar`` **``doca < x < 0``**, so zero itself is rejected
========= =========================================================================

These setters mirror pack/cell parameter values and use the cell-parameter copy for the
related-field comparisons. Evidence: ``0x0800d456``–``0x0800d6b4``.

.. _firmware-behavior-daily-weekly-and-monthly-schedules:

Daily, weekly and monthly schedules
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

E2 accepts the following complete setter forms for ``sleep`` and ``record``:

.. code:: text

   config sleep day sh sm eh em
   config sleep week sd sh sm ed eh em
   config sleep month sd sh sm ed eh em
   config record day sh sm eh em
   config record week sd sh sm ed eh em
   config record month sd sh sm ed eh em

All numbers are D, narrowed to bytes before validation. Hours are 0–23, minutes 0–59. Weekdays
are **1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat, 7=Sun**; monthly days are **1–31**. A monthly
day is not validated against a particular month’s length. Start and end must differ; an earlier
end receives a wrap-to-next period flag. Scheduling a period does not imply the same
enabled-state polarity for sleep and record: ``sleep on`` clears its disabled flag, while
``record on`` sets its enable flag. Queries ``config sleep``/``config record`` print the state.

E2 weekday labels were recovered from initialized data at RAM ``0x20000818``– ``0x20000830``;
weekly/monthly sleep validation is at ``0x0800da30``/``0x0800db48``. Firmware validates the
truncated byte, so clients must reject values outside the normal ranges before serialization.

.. _firmware-behavior-config-savedefault-and-prot-storage:

``config save/default`` and ``prot`` storage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The E2 configuration callback is ``0x08010dc8``. Its persistence helper ``0x080201de`` stores
each four-byte data word followed by a **one-byte check value**, so serialized EEPROM blocks
occupy five bytes per runtime word:

+--------------------+----------------------+--------------------+-----------------------------+
| Callback operation | EEPROM 0 start       | Runtime data bytes | Meaning                     |
+====================+======================+====================+=============================+
| ``0x0f``           | ``0x5a9``            | 192                | Cell/battery parameters     |
+--------------------+----------------------+--------------------+-----------------------------+
| ``0x11``           | ``0x699``            | 192                | Pack parameters             |
+--------------------+----------------------+--------------------+-----------------------------+
| ``0x15``           | ``0x59a``            | 12                 | Additional configuration    |
|                    |                      |                    | block                       |
+--------------------+----------------------+--------------------+-----------------------------+
| ``0x17``           | ``0x58b``            | 12                 | Sleep-control block         |
+--------------------+----------------------+--------------------+-----------------------------+
| ``0x19``           | ``0x581``, ``0x586`` | 4 each             | Battery and pack            |
|                    |                      |                    | protection-enable masks     |
+--------------------+----------------------+--------------------+-----------------------------+
| ``0x1d``           | ``0x78b``            | 16                 | Hardware-sleep/scheduling   |
|                    |                      |                    | configuration block         |
+--------------------+----------------------+--------------------+-----------------------------+
| ``0x21``           | ``0x7a6``            | 4                  | Under-voltage time; also    |
|                    |                      |                    | updates a GPIO output       |
+--------------------+----------------------+--------------------+-----------------------------+

``config save`` invokes 0x0f/0x11/0x17/0x21/0x1d/0x15 and writes the raw two-byte record
interval at ``0x38d``. It does **not** invoke operation 0x19: ``prot`` writes its masks through
0x19 as part of its own command path. ``config default`` supplies restore flags to the parameter
callbacks, sets additional scheduling defaults, and persists the resulting blocks. This
establishes direct EEPROM effects; it is not just a dirty flag waiting for a reset.

The word/check helper ignores individual EEPROM write return values and itself returns zero.
Several callers also discard callback status, so the footer cannot verify every configuration
word was saved. A later readback is needed for a future implementation to confirm persistence.

.. _firmware-behavior-communication-settings-and-hidden-modes:

Communication settings and hidden modes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``couls``\ ’ handler maps ``iah`` to runtime mode 1, ``vah`` to mode 3, ``asic`` to mode 4, and
``default`` to mode 3. It reports ``IAH``, ``IAH_VOL`` or ``ASIC``; no direct EEPROM write
appears in this handler (``0x0800f25c``–``0x0800f2fc``). The naming establishes selection, not a
complete mathematical specification of the SOC algorithms.

The reviewed E2 console frontend at ``0x080251d8`` **requires a local-table match before
consulting the remote table**. ``couls``, and E2 ``soh``, have no such local entry; ordinary
text invocation is rejected before their handler can run. A remote-table entry/help listing
alone does not make them callable. No alternate public text spelling was found; do not expose
invented aliases.

The live communication activation and stored bytes are distinguished in
:ref:`Communication activation and electrical controls <firmware-behavior-communication-activation-and-electrical-controls>`.

.. _firmware-behavior-additional-shared-setter-checks:

Additional shared setter checks
-------------------------------

+-----------------------------------------------+-----------------------------------------------+
| Command                                       | Independently reviewed C behavior             |
+===============================================+===============================================+
| ``emptyvolt``                                 | ``0x0802d7d0``–``0x0802d85c``: decimal        |
|                                               | conversion, **u16 narrowing before 500–3300   |
|                                               | validation**, runtime halfword plus two-byte  |
|                                               | EEPROM-0 ``0x7a3`` write. The handler ignores |
|                                               | the EEPROM-write result and returns zero.     |
|                                               | This matches the E2 setter contract; it does  |
|                                               | not prove identical SOC algorithms.           |
+-----------------------------------------------+-----------------------------------------------+
| ``totalcoul``                                 | ``0x0802d570`` onward: **u8 narrowing before  |
|                                               | checking 50/74/100 Ah**; internal capacity =  |
|                                               | Ah × 3,600,000. Writes eight bytes to         |
|                                               | EEPROM-1 ``0x21`` and a check byte to         |
|                                               | ``0x29``, then reads them back. On the        |
|                                               | success path it changes model                 |
|                                               | identity/runtime selection and invokes        |
|                                               | operations ``0x0f`` and ``0x11`` with value 1 |
|                                               | to restore/persist model defaults. It is      |
|                                               | broader than changing a gauge report scale.   |
+-----------------------------------------------+-----------------------------------------------+

For ``totalcoul``, the C success branches select ``US3000C`` for 74, ``US2000C`` for 50, and
``UP5000`` for 100 (``0x0802d69a``–``0x0802d764``). The selector helper ``0x08012dfa`` stores a
runtime byte, not a bus programming operation. No direct gauge-register write appears in this
handler. A future client should validate literal capacity values before narrowing and describe
the accompanying model and protection-default changes; it should not accept aliases produced by
u8 wraparound. Callback dispatch ``0x08010dd0`` resolves the two operations to ``0x0801132a``
and ``0x08011384``; their value-1 branches restore defaults before writing the parameter blocks
at EEPROM-0 ``0x5a9`` and ``0x699``.

.. _firmware-behavior-mostest-enables-active-background-fault-checks-e2:

``mostest`` enables active background fault checks (E2)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The stored markers enable byte ``0x20000967``, tested at ``0x08011a84``–``0x08011a8a``. The
periodic module path calls this check at ``0x080072ea``; a separate readiness byte
(``0x20000d44``) must also be nonzero. Thus enabling the flag is not merely changing a report
label or running the one-shot ``tmos`` procedure.

The gated routines are ``0x0801182c`` and ``0x080118ec``:

- The first checks module ``+0x270``, two digital input levels, and current below **−999 mA**.
  It accumulates a byte counter using the module interval; at 6 it starts reporting the
  condition, and at 10 it sets fault bit ``0x800``, resets the counter and invokes callback
  operation ``0x29`` with value zero.
- The second checks module ``+0x26f`` and another digital input. With current **at least 1000
  mA**, it uses a similar 6/10 counter and sets fault bit ``0x400`` before invoking the same
  operation. A further branch checks module voltage **at least 60000 mV** or a cell voltage **at
  least 4200 mV**, with a counter threshold of 16, and can invoke that operation too. Its cell
  loop includes index equal to the cell count (``0x080119b8``–``0x080119be``), an apparent
  off-by-one bug; do not copy it into a client implementation.
- Operation ``0x29`` is the AFUSE GPIO/persistent-marker operation described in the parameter
  reference and above. If either routine reports a condition, the caller stores an event and
  requests both statistics and extended-state persistence (``0x08011aac``–``0x08011aca``).

These are counter thresholds, not a claim of exact seconds. The board’s circuit and pin polarity
are still needed to name the electrical failure precisely or prove what the AFUSE circuit
physically does. The code does establish that ``mostest on`` can enable consequential background
actions.
