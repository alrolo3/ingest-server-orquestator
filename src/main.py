from contextlib import asynccontextmanager
from threading import Thread, Event

from fastapi import FastAPI
from fastapi import Request

from config.config import load_server_config
from queues.domain.job import Job
from queues.queue_local import put_item
from workers.inbound_worker import InboundWorker


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.server_config = load_server_config()

    stop_event = Event()
    inbound_worker = InboundWorker(stop_event)
    inbound_thread = Thread(
        target=inbound_worker.run_forever,
        name="inbound-worker",
        daemon=True,
    )
    inbound_thread.start()

    app.state.inbound_worker_stop_event = stop_event
    app.state.inbound_worker_thread = inbound_thread

    yield

    stop_event.set()
    inbound_thread.join(timeout=5)

app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}


@app.post("/api/v1/ingest/file")
async def ingest_file(request: Request):
    server_config = request.app.state.server_config
    job = Job.create(
        parser_type="file",
        input_data={"source": "api"},
        settings={"queue": server_config.inbound_queue_name},
    )
    # queue_message = job.to_queue_message()

    put_item(job)

    return {
        "job": job,
        "queue": server_config.inbound_queue_name,
        "next_step": "processing worker picks the job and sends result to dispatcher",
    }
