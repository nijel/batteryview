Records, reports and pagination
===============================

.. _protocol-report-writer:

Report writer
-------------

``DataStorage.SaveLogDataToTxt`` opens a new or appended file and constructs a ``StreamWriter``
with ``Encoding.Unicode``, then calls ``WriteLine(response)``. On Windows this yields:

- One UTF-16LE BOM at the beginning of the file.
- The response text exactly as accumulated from the console.
- An additional CRLF after each saved response.

The Python writer emits those bytes explicitly on every platform, flushes after each response,
and exclusively creates output files to prevent accidental mixing of sessions. It does not
prepend commands: command echoes come from the console itself. Recovery metadata is a separate
UTF-8 JSON file.

The History/Event button handlers append ``.txt`` to the selected filename, explaining
``.txt.txt`` in the supplied reports. The reset button embeds a space in ``_resetsoc _``; both
quirks are retained in generated default filenames.

.. _protocol-history-and-event-buttons:

History and Event buttons
-------------------------

1. Save ``info``, ``stat``, then ``data history`` or ``data event``.
2. The original uses the latest ``Item Index + 1`` as its count. Python does the same and falls
   back to a valid ``stat`` counter when that index is absent. Disagreements are logged; an
   indeterminate count is an error.
3. For offsets ``0, 15, 30, ...``, try ``datalist KIND dtls OFFSET``.
4. Explicit rejection switches to ``datalist KIND OFFSET``, at the same offset.
5. After each page, save the response to a blank LF, including the final page.
6. In fallback mode, save ``data KIND INDEX`` for each record on the page.

The original’s ``RegoutHistoryData`` changes ``HistoryGetInfo.DtlsMode`` on rejection;
``OnGetHistoryData`` and ``OnGetHistoryDataItem`` implement both formats for both kinds. The
original always queues 15 individual reads on the last page, even beyond the count. Python
bounds those reads and verifies each returned index instead.

Detailed pages are checked for ordered record coverage. Some firmware includes a sixteenth
record overlapping the next page; that boundary overlap is accepted. Other missing, repeated or
unexpected indices fail collection and preserve partial output. The private historical History
capture has three missing records, so it is now a negative completeness reference rather than
proof of a complete export. No response text is reconstructed or modified to repair it. Unknown
columns and firmware-specific fields remain intact in raw transcripts.

Full reports and SOC reset reject addressed selection before any operation. The original uses
explicit addressed identity/history-item commands in separate UI paths; numbered login is a
parameter/protection authorization helper, not a verified redirection mechanism for bare report
commands.

.. _protocol-support-collection-wrapper:

Support collection wrapper
--------------------------

``collect`` reuses the identity, History, Event, and snapshot operations in that order, holding
the session lock across the run. It uses the same History/Event command selection and UTF-16
serialization as standalone exports, including repeated ``info``/``stat`` requests. Normal
disconnect runs afterward and remains outside report content.

The wrapper supports repeated physical connections to different modules with one shared flat
output directory. Complete support exports routed to a remote module have not been verified.
Consequently, ``collect`` rejects addressed module selection; the existing monitoring and
standalone command interfaces remain available.

Each invocation reserves its own manifest using a UTC timestamp and UUID-based run ID. JSON
artifacts share that run ID, while transcripts keep their existing barcode/timestamp filenames.
Exclusive artifact creation prevents replacement of earlier files, and manifest references never
claim a colliding report from an earlier run as this run’s partial output.

Manifest format version 1 records the application version, run ID, start/end times, overall
status/completeness, device identity, and ordered step records. Step records contain a name,
status, relative artifact filename, reported record count where available, and failure
type/message. Status transitions are ``pending`` → ``running`` → ``complete``, ``failed``, or
``interrupted``; later steps become ``skipped`` after a failure or interruption. Updates replace
the run’s manifest atomically.

The first failed step ends collection. By default reads are not retried; ``read_retries=1`` or
``2`` enables bounded recovery of explicit reads after a debug prompt is verified. Pagination
continuations and reset operations are never retried. Failed report attempts and
resynchronization replies remain in reports. Existing artifacts remain available, and
read-response payloads are not copied into manifest errors. The CLI prints an escaped, bounded
response tail from the failed exchange, including failures returned inside collection; that
diagnostic can contain private data. Successful raw traffic remains opt-in. Expected operational
failures return an incomplete collection result; interruption is re-raised after finalization.
Fatal manifest I/O failures are raised and can leave the last valid manifest indicating an
unfinished run. Serial packet traces are only produced when explicitly enabled.

.. _firmware-parameters-recorded-data-logs-and-counters:

Recorded data, logs and counters
--------------------------------

+-----------------------------------------------+-----------------------------------------------+
| Form                                          | Parameters, defaults and effect               |
+===============================================+===============================================+
| ``data [kind [index]]``                       | No arguments selects the latest event.        |
|                                               | ``data kind`` selects that kind’s latest      |
|                                               | item. An explicit index is D, narrowed to     |
|                                               | u16, and must be **less than the selected     |
|                                               | count**; indices are zero-based. An empty     |
|                                               | collection has a separate no-data path.       |
+-----------------------------------------------+-----------------------------------------------+
| ``datalist kind [start]``                     | Start is a decimal record index, not a        |
|                                               | requested count. Lists summary rows and may   |
|                                               | paginate. Determine the available count       |
|                                               | instead of probing arbitrarily high indices.  |
+-----------------------------------------------+-----------------------------------------------+
| ``datalist kind dtls start``                  | Handler-recognized detailed form omitted from |
|                                               | help. ``start`` is D. This is separate from   |
|                                               | ``data kind index``, which retrieves an       |
|                                               | individual record.                            |
+-----------------------------------------------+-----------------------------------------------+
| ``datalist kind ...``                         | Exact forms are                               |
|                                               | ``datalist kind bat field start`` and         |
|                                               | ``datalist kind bat cell field start``, with  |
|                                               | zero-based cell. ``item`` is not an E2        |
|                                               | literal selector. See the supplement for      |
|                                               | scaling, paging and malformed-input quirks.   |
+-----------------------------------------------+-----------------------------------------------+
| ``save [event\|history]``                     | No argument defaults to event; ``event``      |
|                                               | selects callback argument 0 and ``history``   |
|                                               | selects 1. Unknown names fail. Tail-calls the |
|                                               | module record-save callback, propagating its  |
|                                               | return status. The synchronous writer, slot   |
|                                               | allocation and count-update failure behavior  |
|                                               | are traced in the supplement.                 |
+-----------------------------------------------+-----------------------------------------------+
| ``datac [event\|history\|event_log\|use]``    | No argument resets **both event and history   |
|                                               | bookkeeping without entering the              |
|                                               | flash-erasure loop**. Explicit event/history  |
|                                               | also erases the corresponding flash           |
|                                               | allocation. The other kinds clear separate    |
|                                               | counters/metadata. See the storage map below; |
|                                               | this is not a general EEPROM erase.           |
+-----------------------------------------------+-----------------------------------------------+
| ``log [count]``                               | Separate diagnostic ring. Count is D,         |
|                                               | **1–32**. No argument uses the available      |
|                                               | count, or 32 for a wrapped ring. Traverses    |
|                                               | newest first; records are 20 bytes at EEPROM  |
|                                               | 0 ``0x6c + index*20``. Behavior when          |
|                                               | requesting more than the available entries    |
|                                               | should not be used to infer valid historical  |
|                                               | records.                                      |
+-----------------------------------------------+-----------------------------------------------+
| ``logc``                                      | Clears diagnostic-ring index/wrap state and   |
|                                               | writes a two-byte zero at EEPROM 0 ``0x387``. |
|                                               | This does not establish that old payload      |
|                                               | bytes are erased.                             |
+-----------------------------------------------+-----------------------------------------------+
| ``logt value``                                | Value is H. Injects an internal test-log      |
|                                               | event through the logger with code ``0x600``, |
|                                               | source/argument 1 and the supplied 32-bit     |
|                                               | value.                                        |
+-----------------------------------------------+-----------------------------------------------+
| ``statc``                                     | Clears 60 halfword statistics fields starting |
|                                               | at module offset ``0x08c``,                   |
|                                               | preserving/restoring reset, life-warning and  |
|                                               | life-alarm fields at ``0x0ce/0x0de/0x0e0``.   |
|                                               | Synchronously saves the 124-byte block at     |
|                                               | EEPROM 0 ``0x38f`` through the resolved       |
|                                               | callback; individual command return handling  |
|                                               | still matters.                                |
+-----------------------------------------------+-----------------------------------------------+
| ``tcycle [count]``                            | No argument reports cycle count and real      |
|                                               | coulomb value. D count **0–10000** changes    |
|                                               | the cycle field and recalculates related      |
|                                               | runtime coulomb state; this is not just a     |
|                                               | counter display. No direct EEPROM write was   |
|                                               | found in the handler.                         |
+-----------------------------------------------+-----------------------------------------------+

Supported record kinds advertised by the firmware are ``event``, ``history``, ``pov``, ``puv``,
``plv``, ``bov``, ``buv``, ``inputov``, ``coc``, ``coca``, ``doc``, ``doca``, ``sc``, ``use``.
The ``use`` path also reports an interval in days. Internal ``log`` is a different ring from
these recorded-data collections.

Evidence: E2 ``data`` ``0x080092f8`` (default/index logic ``0x08009324``–``0x080093e0``),
``datalist`` comparison ``0x0800ba8a``, ``log`` ``0x080175b8``, ``logc`` ``0x08017794``,
``statc`` ``0x08009036``, ``tcycle`` ``0x0800f32c``. C ``statc`` ``0x08008ff0`` has the same
preservation pattern.

.. _firmware-parameters-datac-bookkeeping-and-payload-erasure-are-different-operations:

``datac``: bookkeeping and payload erasure are different operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

E2 handler ``0x08029d08``–``0x08029edc`` accepts no operand or one of the four literal names. It
initializes a zero-filled temporary buffer, selects a storage descriptor for the requested kind,
and performs these operations:

+-----------------------------------------------+-----------------------------------------------+
| Form                                          | Confirmed runtime and persistent changes      |
+===============================================+===============================================+
| ``datac``                                     | Zeros event write-index at EEPROM 0           |
|                                               | ``0x389``, event count at ``0x38f``, history  |
|                                               | write-index at ``0x38b``, history count at    |
|                                               | ``0x391`` (two bytes each), with              |
|                                               | corresponding RAM fields. Skips the           |
|                                               | flash-erasure loop because both kinds were    |
|                                               | selected. Old payload bytes are not           |
|                                               | physically erased by this path.               |
+-----------------------------------------------+-----------------------------------------------+
| ``datac event``                               | Same event-index/count clearing, then         |
|                                               | flash-erasure loop over the event             |
|                                               | descriptor’s allocation.                      |
+-----------------------------------------------+-----------------------------------------------+
| ``datac history``                             | Same history-index/count clearing, then       |
|                                               | flash-erasure loop over the history           |
|                                               | descriptor’s allocation.                      |
+-----------------------------------------------+-----------------------------------------------+
| ``datac event_log``                           | Clears 22 bytes of runtime event-specific     |
|                                               | counters beginning at module offset           |
|                                               | ``0x104``, then writes 22 zero bytes at       |
|                                               | EEPROM **1** ``0x658``. No event/history      |
|                                               | flash-erasure loop. This is separate from the |
|                                               | internal diagnostic ``logc`` ring.            |
+-----------------------------------------------+-----------------------------------------------+
| ``datac use``                                 | Zeros the two runtime halfwords at module     |
|                                               | ``0x11a/0x11c``, four EEPROM-1 bytes at       |
|                                               | ``0x66e``, and seven EEPROM-0 bytes at        |
|                                               | ``0x40d``. No event/history flash-erasure     |
|                                               | loop.                                         |
+-----------------------------------------------+-----------------------------------------------+

The explicit event/history paths get their start address, allocation length and erase
granularities from runtime storage descriptors. The loop calls flash helpers ``0x0801fd48`` /
``0x0801fd98``, which emit address-bearing SPI commands ``0x20`` / ``0x52``. The supplement
traces the E2 event/history allocation addresses and 4 KiB/32 KiB erase geometry; neither is a
command parameter.

Bookkeeping is reset **before** payload erasure. EEPROM return codes are accumulated; a nonzero
total produces handler return 5. The erase-helper results are not accumulated into that total.
Bad alignment can return 1 after prior changes. Consequently a failed command can already have
changed counts, and a success footer alone does not verify every erase completed. Do not retry
this operation as though it were a read or claim transactional clearing.

``save`` at ``0x08009074`` dispatches through ``0x080073ec``; no argument selects an event. It
requests a fresh record, rather than flushing every existing record or saving configuration. The
callback’s physical storage sequence and error handling are documented in the supplement.

.. _firmware-behavior-recorded-data-query-grammar:

Recorded-data query grammar
---------------------------

E2 ``datalist`` (``0x0800b094``) dispatches by **total token count**:

+-----------------------------------------------+-----------------------------------------------+
| Form                                          | Output / validation                           |
+===============================================+===============================================+
| ``datalist kind start``                       | Summary records from zero-based D ``start``,  |
|                                               | strictly below the selected count.            |
+-----------------------------------------------+-----------------------------------------------+
| ``datalist kind dtls start``                  | Expanded rows from D ``start``, including     |
|                                               | per-cell state. ``dtls`` must match           |
|                                               | literally.                                    |
+-----------------------------------------------+-----------------------------------------------+
| ``datalist kind bat field start``             | Selected field for **all cells**, beginning   |
|                                               | at D record index ``start``.                  |
+-----------------------------------------------+-----------------------------------------------+
| ``datalist kind bat cell field start``        | Selected field for one **zero-based D cell**, |
|                                               | bounded by current module cell count; D       |
|                                               | ``start`` below the record count.             |
+-----------------------------------------------+-----------------------------------------------+

Fields are ``id``, ``volt``, ``curr``, ``temp``, ``coul``. Record kinds are those listed in the
parameter reference. ``item`` is **not** a recognized literal in these E2 branches, despite its
appearance in help. No-argument and kind-only calls do not select an implicit start: they fail.
Do not translate the help’s brackets into arbitrary optional arguments.

The two all-record list forms load records through module callback ``+0x288``, check the
``55 AA`` record prefix and report ``Error!`` on a bad record. The all-cell field form formats
two records per output chunk; the single-cell form formats up to sixteen. Continuation is
controlled by the output/pager helper, so stopping at one chunk does not mean the collection
ends there. Summary/detail loops also validate the record and cell buffer boundaries; retain
error output rather than silently treating a corrupt record as absent.

The all-cell ``curr`` branch divides stored current by **1000 using signed integer division**
(``0x0800c280``–``0x0800c28c``). The single-cell branch prints the stored integer directly
(``0x0800c3f0``–``0x0800c408``). Thus those two forms have different current scales/truncation.
Other fields are printed as raw integers. Client normalization must depend on the selected form,
not only the ``curr`` name.

The summary/detail start parsers do not consistently test their error flag before using the
value. Supply strictly validated decimal tokens. The explicit field forms do test the flag.
Evidence: E2 summary ``0x0800b17e``, detailed ``0x0800ba84``, all-cell ``0x0800c148``,
single-cell ``0x0800c2b8``.
