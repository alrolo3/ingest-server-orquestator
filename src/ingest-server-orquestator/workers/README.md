# Workers

Worker entrypoints live here.

Keep two worker responsibilities separated:

1. Processing worker: reads inbound jobs, runs the processing pipeline, writes results to the outbound queue.
2. Dispatcher worker: reads processed results and sends them through one or more dispatcher adapters.
