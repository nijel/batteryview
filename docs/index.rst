Pylontech Tools
===============

Pylontech Tools connects your computer to a Pylontech battery's serial console.
Collect support files, export recorded events and history, or monitor module and
cell measurements from a command-line application or your own Python code.
It runs on Windows, Linux, and macOS with Python 3.11 or newer.

The project is an independent implementation informed by BatteryView and firmware
analysis. It produces BatteryView-compatible text reports and exposes measurements
as JSON, JSON Lines, or CSV for use with other tools.

Get started
-----------

You need an appropriate serial connection to the battery's console port. Follow
:doc:`the installation guide <software/installation>` to install the tools and
configure your connection. Once installed, list the available ports and read the
connected battery's identity:

.. code-block:: sh

   pylontech-console ports
   pylontech-console info --port /dev/ttyUSB0

Replace ``/dev/ttyUSB0`` with your serial port, such as ``COM3`` on Windows.
For a support request, :doc:`collect a support bundle <software/collection>`;
for integration into your own application, start with
:doc:`the Python client examples <software/python>`.

Explore the protocol
--------------------

Alongside the software guides, the communication manual explains console
sessions, command parameters, responses, model differences, storage behavior, and
firmware bugs. Source evidence and details that still need hardware validation
remain available alongside the command contracts.

The :doc:`communication manual <protocol/index>` is intended to help developers
understand existing workflows and implement additional operations. Command
availability varies by model and firmware; the
:doc:`compatibility and limitations <protocol/evidence>` explain the scope of the
analysis.

Pylontech Tools is developed in the
`source repository <https://github.com/nijel/pylontech-tools>`__. Bug reports,
corrections, and contributions are welcome.

.. toctree::
   :maxdepth: 2
   :hidden:

   software/index
   protocol/index
