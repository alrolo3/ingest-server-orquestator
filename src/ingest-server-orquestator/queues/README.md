# Queues

Queue clients and message payload helpers live here.

The job object is defined in `job.py`.

Expected flow:

1. API puts a processing job with settings into the inbound queue.
2. Processing worker consumes from the inbound queue.
3. Processing result is put into the outbound queue.
4. Dispatcher consumes from the outbound queue and sends the result to external interfaces.

SQLite-friendly columns for a job record:

1. `job_id`
2. `parser_type`
3. `input_data_json`
4. `settings_json`
5. `status`
6. `created_at`
