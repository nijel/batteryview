SOC reset and recovery
======================

.. _README-soc-reset:

SOC reset
---------

.. code:: sh

   batteryview reset-soc --port /dev/ttyUSB0 --output reset.txt

This command **clears EEPROM, resets the battery, and restores its barcode**, following the
bundled BatteryView script. Invoke it only when you intend to perform that operation. History,
Event, and monitoring do not perform it.

Before EEPROM clearing, the client saves the original identity and barcode to
``reset.txt.recovery.json`` and flushes the pre-reset transcript to disk. It aborts before
clearing if no usable barcode was captured. It then performs the reset, reconnects, restores the
barcode, and verifies the device identity. Address changes are permitted after reset.

The recovery file records the last attempted step and completion status. If the operation fails
or is interrupted, retain both files and inspect the recovery state before taking further
action. Mutating commands are never automatically retried, and there is no automatic
restart/resume command. A timeout after a write cannot establish whether the battery executed
that command.
