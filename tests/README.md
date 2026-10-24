# Test data policy

All distributed response strings are constructed synthetic examples. Use
`SYNTHETIC_MODEL`, barcodes such as `TEST123`, fixed year-2000 timestamps, and
invented small counters and measurements. Protocol words, command names, unit
scales, and page sizes are protocol facts, not private fixture data.

Do not copy battery barcodes, manufacture/release dates, firmware inventories,
operating timestamps, history counters, or telemetry rows from real recordings
into these files. Add synthetic cases for new formats instead.

Real reference recordings stay in the ignored `Logs/` directory or another local
directory. They are read only when explicitly requested with `--private-logs`.
Do not upload them to CI, commit them, or attach replay output to public issues.
The private replay test wrapper suppresses payloads on failure. Wheel and source
distribution builds exclude recordings and editor recovery files.
