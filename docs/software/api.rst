Python API reference
====================

Use :class:`pylontech_tools.BatteryClient` as a context manager to connect and close
the console. See :doc:`python` for examples. Measurements use the units in field
names; absent measurements are ``None``. Results retain raw console data.

.. autoclass:: pylontech_tools.Alarm
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.BatteryClient
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.PylontechError
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.CellReading
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.CollectionResult
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.CommandTimeout
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.CommandCancelled
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.ConnectionError
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.DeviceInfo
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.DiagnosticReadResult
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.DiagnosticsReport
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.ModuleReading
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.ProtocolError
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.ReportResult
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.ResetRecoveryError
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.Snapshot
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.SystemReading
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.UnsupportedCommand
   :members:
   :undoc-members:


.. autoclass:: pylontech_tools.ConsoleReadResult
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.DeviceBusyError
   :members:

.. autoclass:: pylontech_tools.DeviceNotPresentError
   :members:

.. autofunction:: pylontech_tools.analyze_logs

.. autoclass:: pylontech_tools.DoctorReport
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.DoctorBattery
   :members:
   :undoc-members:

.. autoclass:: pylontech_tools.DoctorFinding
   :members:
   :undoc-members:
