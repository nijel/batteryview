Using the Python client
=======================

.. _README-python-api:

Python API
----------

.. code:: python

   from batteryview import BatteryClient

   with BatteryClient("/dev/ttyUSB0", module=3) as battery:
       identity = battery.info()
       snapshot = battery.snapshot()
       print(identity.name, snapshot.to_dict())

The client is synchronous and serializes operations on a shared console session.
``watch(interval=5, count=None)`` yields snapshots. ``reset_soc(path)`` is the separate mutating
workflow. Exceptions derive from ``BatteryViewError``; ``CommandTimeout``,
``UnsupportedCommand``, and ``ProtocolError`` retain any partial response.
``ResetRecoveryError`` exposes ``recovery_path``.

For support collection, use a client with no addressed module selection:

.. code:: python

   with BatteryClient("/dev/ttyUSB0") as battery:
       report = battery.export_history("history.txt.txt")
       print(report.records)
       result = battery.collect("support")
       print(result.complete, result.manifest_path)

``collect(output, progress=None)`` requires a connected client and returns a
``CollectionResult(directory, manifest_path, complete)``. Expected step failures return an
incomplete result. Cancellation is re-raised after updating the manifest; output-directory and
manifest-write errors are raised to the caller.

``BatteryClient.close()`` performs the same disconnect as context-manager exit. There are no
background polling tasks or queued report writes to drain: operations share a session lock, and
report responses are flushed before their methods return.
