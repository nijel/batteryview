BatteryView controls and workflows
==================================

.. _protocol-command-meanings-from-batteryviews-controls:

Command meanings from BatteryView’s controls
--------------------------------------------

This section adds **application intent**, alongside the firmware contracts in
:doc:`the parameter reference </protocol/index>`. Evidence is the managed code and bundled
configuration in ``BatteryView_3.0.28_1``, not successful execution on every supported model.
Reviewed ``BatteryView.exe`` SHA-256:
``af69bbf5118856b5a72b07bd2d773a4565062ade3932c53cf9fc05205bcd45b6``. Method RVAs below identify
this assembly, not MCU addresses.

The relevant files under the application’s ``Configs/`` directory are ``ParameterConfig.xml``,
``Params/*_ParameterConfig.xml``, ``CtrlConfig.xml``, ``Controls/*_CtrlConfig.xml``,
``SetItem.xml``, ``Controls/*_SetItem.xml``, and ``Indicator.xml`` /
``Indicators/*_Indicator.xml``. Labels describe intended use; ``CmdHeader`` / ``CmdBody``
describe what the application constructs. Neither is proof that the reviewed E2/C firmware
implements that spelling. Original logs, identities and telemetry were not used for this
additional analysis.

.. _protocol-parameter-vocabulary-and-units:

Parameter vocabulary and units
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The labels consistently distinguish **protection trips** from **warning/alarm thresholds**. A
release value is a recovery threshold, not another trip level. This makes the abbreviated
selectors easier to understand:

+-----------------------------------------------+-----------------------------------------------+
| Selector family                               | Application description                       |
+===============================================+===============================================+
| ``pov/povr``, ``puv/puvr``                    | Module over-/under-voltage protection         |
|                                               | threshold and release.                        |
+-----------------------------------------------+-----------------------------------------------+
| ``phv/phvr``, ``plv/plvr``                    | Module high-/low-voltage alarm threshold and  |
|                                               | release.                                      |
+-----------------------------------------------+-----------------------------------------------+
| ``pslp``                                      | Module sleep/shutdown voltage.                |
+-----------------------------------------------+-----------------------------------------------+
| ``bov/bovr``, ``buv/buvr``                    | Cell over-/under-voltage protection threshold |
|                                               | and release.                                  |
+-----------------------------------------------+-----------------------------------------------+
| ``bhv/bhvr``, ``blv/blvr``                    | Cell high-/low-voltage alarm threshold and    |
|                                               | release.                                      |
+-----------------------------------------------+-----------------------------------------------+
| ``bslp``                                      | Cell shutdown voltage.                        |
+-----------------------------------------------+-----------------------------------------------+
| ``bot/botr``, ``but/butr``                    | Battery over-/under-temperature protection    |
|                                               | and release in the US3000C/Forcel_C           |
|                                               | definitions. Their UI IDs retain older names  |
|                                               | ``COT/COTR``, ``CUT/CUTR``.                   |
+-----------------------------------------------+-----------------------------------------------+
| ``bht/bhtr``, ``blt/bltr``                    | Battery high-/low-temperature alarm and       |
|                                               | release in those definitions. UI IDs retain   |
|                                               | ``CHT/CHTR``, ``CLT/CLTR``.                   |
+-----------------------------------------------+-----------------------------------------------+
| Legacy ``cot/cotr``, ``dot/dotr``,            | Charge/discharge temperature protection or    |
| ``cht/chtr``, ``dht/dhtr``, ``clt/cltr``,     | alarm families in older configuration files;  |
| ``dlt/dltr``, ``cut/cutr``, ``dut/dutr``      | **not aliases proven in E2/C**.               |
+-----------------------------------------------+-----------------------------------------------+
| ``eht/ehtr``                                  | Environment high-temperature alarm and        |
|                                               | release.                                      |
+-----------------------------------------------+-----------------------------------------------+
| ``mot/motr``                                  | Board over-temperature protection and         |
|                                               | release, according to the Forcel_C labels.    |
|                                               | This is board-level intent, not               |
|                                               | identification of a particular physical       |
|                                               | sensor.                                       |
+-----------------------------------------------+-----------------------------------------------+
| ``coc``, ``doc``                              | Charge/discharge overcurrent protection       |
|                                               | threshold.                                    |
+-----------------------------------------------+-----------------------------------------------+
| ``coca/cocar``, ``doca/docar``                | Charge/discharge overcurrent alarm and alarm  |
|                                               | release; see the copied-selector bug below.   |
+-----------------------------------------------+-----------------------------------------------+
| ``ocd``, ``ocr``                              | Overcurrent protection delay and recovery     |
|                                               | time, labelled milliseconds.                  |
+-----------------------------------------------+-----------------------------------------------+
| ``COC2``, ``DOC2``, ``OC2D``, ``OC2R`` UI     | Secondary charge/discharge overcurrent        |
| fields                                        | thresholds and secondary delay/recovery.      |
|                                               | These have empty command bodies and are       |
|                                               | marked **read-only** in the US3000C profile.  |
+-----------------------------------------------+-----------------------------------------------+
| ``SC``, ``scd``, ``scr``                      | Short-circuit current threshold, delay and    |
|                                               | recovery. ``SC`` is also read-only in that    |
|                                               | profile.                                      |
+-----------------------------------------------+-----------------------------------------------+
| ``uvtime``                                    | Under-voltage shutdown time, labelled         |
|                                               | seconds.                                      |
+-----------------------------------------------+-----------------------------------------------+
| ``shuttime``                                  | Idle shutdown time, labelled hours in the     |
|                                               | legacy UI. E2 instead reports                 |
|                                               | ``NO IDLE SHUT``; the UI does not establish   |
|                                               | an implemented timer.                         |
+-----------------------------------------------+-----------------------------------------------+

``BMUParamterItem.GetSetCmdString`` (RVA ``0x2a3f0``) multiplies numeric UI values by configured
``Accuracy`` **when the numeric/HasLimit branch applies**. The reverse parser
``RegoutParamValue`` (``0x2a81c``) divides by that factor, except for the ``RECINV`` parameter
type. Typical voltage, current and temperature factors are 1000, explaining V→mV, A→mA and
°C→mC. For example, an invented UI value of 54.2 V with factor 1000 becomes integer ``54200``,
not a decimal-volts operand. The default factor is 1. An ``Accuracy`` attribute on a
``HasLimit="false"`` row is not sufficient to prove scaling: the legacy ``shuttime`` row has
factor 2 but bypasses this numeric-scaling branch. Use firmware units for implementation.

.. _protocol-named-actions-and-what-they-actually-send:

Named actions and what they actually send
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+-----------------------------------------------+-----------------------------------------------+
| UI action                                     | Application command / meaning                 |
+===============================================+===============================================+
| Set System Time                               | ``time`` with a supplied value; the builder   |
|                                               | has a dedicated TIME branch.                  |
+-----------------------------------------------+-----------------------------------------------+
| Clear EEProm                                  | ``eepe 0``; intended to clear external        |
|                                               | EEPROM, not erase event/history flash. The    |
|                                               | firmware analysis establishes its exact       |
|                                               | overwrite behavior.                           |
+-----------------------------------------------+-----------------------------------------------+
| Write module barcode                          | ``tbar`` plus the supplied identity. No       |
|                                               | original identity is embedded in this         |
|                                               | documentation.                                |
+-----------------------------------------------+-----------------------------------------------+
| Clear AFuse Error                             | ``ctrl afuse off``. The Chinese label         |
|                                               | explicitly refers to a **three-terminal       |
|                                               | fuse**. This establishes the application’s    |
|                                               | intended fault-clear action, not physical     |
|                                               | repair of a fuse or proof of its circuitry.   |
+-----------------------------------------------+-----------------------------------------------+
| Turn on/off aging log                         | ``ctrl agelog on/off``; ageing/test recording |
|                                               | control, separate from clearing stored        |
|                                               | records.                                      |
+-----------------------------------------------+-----------------------------------------------+
| Manual charge / discharge                     | ``ctrl cfet on/off`` / ``ctrl dfet on/off``;  |
|                                               | charge/discharge power-path control.          |
+-----------------------------------------------+-----------------------------------------------+
| Manual buzzer / heater                        | ``ctrl buzz on/off`` / ``ctrl heat on/off``;  |
|                                               | the heater label refers to a heating film.    |
|                                               | Availability depends on the board.            |
+-----------------------------------------------+-----------------------------------------------+
| Default Parameters                            | ``config default``; restore defaults, not     |
|                                               | show a default-value report.                  |
+-----------------------------------------------+-----------------------------------------------+
| LED Check                                     | ``tled``, followed by an operator question    |
|                                               | about the LED sequence.                       |
+-----------------------------------------------+-----------------------------------------------+
| Cell balance check                            | ``tbld ffff`` twice, followed by an operator  |
|                                               | question about the balancing LEDs. Two        |
|                                               | identical sends do **not** establish an       |
|                                               | on/off toggle. Both reviewed firmware tables  |
|                                               | allow only bare ``tbld``; the extra mask is a |
|                                               | compatibility mismatch.                       |
+-----------------------------------------------+-----------------------------------------------+

These descriptions come from ``SetItem.xml``, the model-specific SetItem files and
``CtrlConfig.xml``. In E2, for example, ``ctrl heat`` reports OFF and its setters have no
implemented effect; the heating-film label does not override that finding. ``prot`` entries
separately enable/disable protections and alarms; ``ctrl`` entries request manual controls.
Disabling a protection entry is not the same operation as clearing its recorded event or
restoring its threshold.

.. _protocol-current-sensor-reset-is-calibration-not-the-soc-reset-script:

“Current sensor reset” is calibration, not the SOC-reset script
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The default, UP2500 and US2KBPL action lists send ``ctrl cfet off``, wait 2 s, run
**``soccal bdoffset``**, send ``ctrl cfet on``, wait 3 s, then run **``soccal current 10000``**.
The explicit waits are empty-command script items; they send no console command. The
offset/current steps have Time values 60/30. The US5000 SetItem variant replaces that sequence
with **``currcal 10000``**, Time 30. The 2500LFP2 file includes the older sequence under both
ADC calibration and current-sensor-reset labels.

The prompt describes an external constant-current calibration fixture. Its 54 V / 10.03 A text
is bundled script text, **not a validated fixture requirement for every listed model**; the sent
reference remains 10000 mA. This is different from the EEPROM-clear/restart/barcode-restoration
:ref:`SOC-reset workflow <protocol-soc-reset-button>`. The C firmware’s selector list does not
recognize ``bdoffset``; its traced forms include ``ccoffset``, ``bdoffsetP1`` and
``bdoffsetP2``. Do not substitute between these automatically. E2’s actual ``currcal`` path is
documented in the firmware reference, including its failure to reject references other than
10000 before mutation.

``SendEquipmentCommand`` (RVA ``0x32e04``) uses the configured Time multiplied by 1.5, truncated
to an integer, as the send timeout. An empty command sleeps Time × 1000 ms. Therefore Time is a
UI workflow/timeout field, not necessarily a required delay after every nonempty command or a
firmware execution duration. Pre-/post-prompts pause for an operator; visual checks are not
autonomous measurements.

.. _protocol-mos-failure-monitoring-and-nominal-capacity-actions:

MOS-failure monitoring and nominal-capacity actions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``OnSetMosFail`` (``0x2dc50``) is more specific than its name suggests:

1. Read **``bat``** and extract four-digit cell voltages from matched rows.
2. Reject a parsed cell **>= 4200 mV** or a parsed sum **>= 60000 mV**.
3. Send **``ctrl mostest on``** and require the success footer.
4. Query **``ctrl mostest``**, accepting a response containing **``ON``**.

This enables the
:ref:`background fault checks <firmware-behavior-mostest-enables-active-background-fault-checks-e2>`;
it is not the one-shot ``tmos`` test or a generic fault-clear command. The app creates an SOC
regex but does not apply an SOC bound in this inspected check. Its row regex does not verify the
expected cell count: zero matched rows leave a zero sum and can reach the enable branch. A
future implementation should require a complete, correctly identified cell table rather than
copy that acceptance bug. The UI voltage checks also do not establish the conditions under which
the firmware’s background actions are safe on other boards.

``OnSetCoul`` (``0x2da84``) sends **``totalcoul supplied_value``**, checks for ``pass``, then
queries **``totalcoul``** and divides its reported mAh integer by 1000 for an Ah display. This
supports the nominal-capacity interpretation. It does not make the command an arbitrary SOC
adjustment: the firmware setter also changes model/default configuration, as described in the
firmware supplement.

.. _protocol-parameterprotection-command-construction-and-acknowledgement:

Parameter/protection command construction and acknowledgement
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``Login`` (``0x301c0``) translates zero-based UI device index ``i`` into ``login i+1 debug``,
caches an ``IsLogin`` flag when the response contains ``_debug``, and skips the send for
already-marked/offline devices. This is weaker than verifying the final prompt after every
exchange.

For per-item writes, ``GetSetCmdString`` constructs local ``config selector value`` or addressed
``config N selector value`` for combined commands, subject to ``IsSupportUnit``.
Control/protection items use the analogous ``ctrl`` / ``prot`` headers. Their numeric device
index is not an additional value argument; the firmware frontend must support addressed routing
for that command. Set-all processing loops over online modules and logs in to each; it is not
proof of an atomic broadcast operation.

The collection-level builders ``BMUParamItemCollection.GetCommand`` (``0x2aac8``) and
``BMUContorlItemCollection.GetCommand`` (``0x2b658``) select refresh/default/save strings. A
one-word query becomes ``config N``, ``ctrl N`` or ``prot N`` for N > 1. For multiword strings,
however, both call ``.Insert(...)`` and **discard its returned string**. They therefore return
bare ``config save``, ``config default`` or ``prot default`` despite receiving another module
address. Do not copy this addressing bug or assume numbered login redirects otherwise bare
commands.

``RefreshParam`` (``0x30584``) logs in, reads each configured category and parses its fields.
``OnSaveConfig`` (``0x30670``) and ``OnDefaultConfig`` (``0x3079c``) send the category’s
configured action strings. ``OnRefreshProtection`` (``0x30d94``) queries the control/protection
categories; it does not itself modify their settings. ``BMUParamterItem.CheckSetResult``
(``0x2a678``) merely searches for ``Command completed successfully``. The UI can update its
cached value from the requested value after that match, without reading back that individual
setting. This is application acknowledgement, not proof of persistence or effective protection
behavior. The firmware reference remains the authority for each setter’s actual return paths and
storage effects.

.. _protocol-fault-labels-are-tied-to-their-source-field:

Fault labels are tied to their source field
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``Indicator.xml`` and the US3000C/US2KBPL indicator variants label the following **``getpwr``
ERRORCODE StatusKey indices**:

===== ========= =====================================================
Index Mask      Vendor label, paraphrased
===== ========= =====================================================
0     ``0x001`` Reversed input polarity.
1     ``0x002`` Input overvoltage.
2     ``0x004`` Hardware-version error.
3     ``0x008`` Battery monitor IC error.
4     ``0x010`` HIB error; acronym not expanded by the configuration.
5     ``0x020`` Temperature-sensor error.
6     ``0x040`` Voltage-sensor error.
7     ``0x080`` I²C error.
8     ``0x100`` Address-allocation error.
9     ``0x200`` Internal communication error.
10    ``0x400`` Charge MOS failure.
11    ``0x800`` Discharge MOS failure.
===== ========= =====================================================

The UP2500 indicator file additionally names index 12 (``0x1000``) as fuse failure. These are
vendor UI meanings for that configured field/profile. They do not establish that an event’s
``System Fault``, a ``pwr`` event mask, and every firmware’s ``getpwr`` trailer share the same
bit layout. Preserve the source and raw value before applying a label.

.. _protocol-configuration-defects-and-unsupported-model-commands:

Configuration defects and unsupported model commands
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The XML is a description source, not a safe command generator:

- US3000C’s ``DOCA`` / ``DOCAR`` entries use **``coca`` / ``cocar``** as command bodies, despite
  discharge-alarm labels. Those bodies address **charge** settings in the reviewed firmware. The
  legacy ``DOTR`` entry similarly uses ``cotr``.
- Several limits contain malformed ``ax(...)`` expressions, copied voltage bounds on temperature
  entries, or self-referential limits. Firmware predicates take precedence over those UI limits.
- ``Forcel_C`` contains board-temperature entries such as ``mht``, ``mhtr``, ``mlt``, ``mltr``,
  ``mut``, ``mutr`` without corresponding E2/C config selectors. The file’s existence proves
  intended support for that family, not compatibility here.
- The 2500LFP2 SetItem file describes **``tclrpermflg``** as clearing permanent protection flags
  and **``ctrl canprt off``** as disabling an external-communication timeout. Neither spelling
  is established by the reviewed E2/C tables. Keep them as model-specific application evidence,
  not new aliases.
- Secondary-overcurrent UI fields being read-only do not remove the firmware’s ``oc2d`` setter.
  They explain why the application does not exercise that setter; they do not resolve its
  downstream negative-delay behavior.

.. _firmware-commands-batteryview-descriptions-and-application-compatibility:

BatteryView descriptions and application compatibility
------------------------------------------------------

:ref:`BatteryView’s control reference <protocol-command-meanings-from-batteryviews-controls>`
adds descriptions of protection/alarm/release selectors, AFUSE, ageing logging, current-sensor
calibration, MOS-failure monitoring and model-specific UI actions. It also records XML command
typos and the application’s collection-addressing bug. Those are application findings, separate
from this catalog’s firmware registration evidence; do not treat every bundled script spelling
as supported.
