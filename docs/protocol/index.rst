Pylontech console communication manual
======================================

This manual describes how to communicate with a Pylontech battery console:
connect and frame requests, select a module, interpret responses, and use the
commands for measurements, recorded data, configuration, and maintenance.
It covers the text console and the separately described PC firmware-update
transfer; it is not a specification of the inverter communication protocol.

Start a session
---------------

Use the :doc:`console connection procedure <console>` to establish a serial
session. Send one command at a time and wait for a complete prompt or a pagination
boundary before sending the next request. For example, these separate requests
read identity, statistics, and the battery clock:

.. code-block:: text

   info
   stat
   time

These are command lines, not a batch to send without waiting. Ordinary console
requests use LF; script and pagination workflows can require different terminators.
A success footer is a handler status, not proof that every underlying operation
succeeded. Check the command-specific response as well.

Read the command contracts
--------------------------

The :doc:`command reference <commands>` lists names, access modes, and model
availability. Topic chapters describe accepted arguments, numeric bases and units,
response interpretation, side effects, and persistence. Optional arguments are
not necessarily harmless: a bare command can read a setting while the same name
with operands writes it. The :doc:`record-query chapter <records>` explains
pagination and complete History/Event transfers; configuration and maintenance
chapters distinguish runtime changes from persistent writes.

Select the correct firmware contract
------------------------------------

**E2** means ``US_E2_V2.5_Crc.bin`` and **C** means ``US_C_V3.1_Crc.bin``.
Unless a section explicitly says C or both, detailed firmware behavior is
**E2-specific**. A shared command name does not establish an identical contract
on another board or release. See :doc:`compatibility and limitations <evidence>`
for command availability differences and unresolved behavior.

Source addresses, hashes, decoded tables, implementation defects, and uncertainty
are retained as supporting evidence. They identify why a contract is documented;
they are not command operands. :doc:`Sources and verification <research>` records
the exact inputs, extraction methods, and reproduction steps. The
:doc:`BatteryView workflow chapter <batteryview>` distinguishes the original
application's labels and command sequences from firmware behavior.

.. toctree::
   :maxdepth: 2
   :hidden:

   console
   commands
   records
   configuration
   calibration
   storage
   diagnostics
   firmware-update
   batteryview
   evidence
   research
