import asyncio
import janus
from typing import Dict, NamedTuple, Union, TypeVar, Generic


class StartResultStep(NamedTuple):
    steps: Union[int, None]
    current_step: int
    text: str


class StopResultStep(NamedTuple):
    text: str


class AdditionalPortsEntry(NamedTuple):
    host: int
    container: int


class LoggingEntry(NamedTuple):
    stdout: Union[str, None]
    stderr: Union[str, None]
    files: Dict


class StatusResult(NamedTuple):
    status: str  # stopped | running | starting
    web: Union[str, None]  # hostname if service has a web port assigned, None otherwise
    additional_ports: Union[AdditionalPortsEntry, None]  # if service has additional ports
    logging: Union[LoggingEntry, None]  # if service has logging defined


class EndResultQueue(Exception):
    """
    Marks the end of a ResultQueue.
    """
    pass


class ResultError(EndResultQueue):
    """
    Marks the end of a ResultQueue and signals an error.
    Is raised if a result queue was ended with an error.
    """
    def __init__(self, message: str, details: str=None, cause: Exception=None, *args: object, **kwargs: object) -> None:
        self.message = message
        self.details = details
        self.cause = cause
        super().__init__(*args, **kwargs)

    def __str__(self):
        if self.cause:
            stri = "%s : %s(%s)" % (self.message, self.cause.__class__.__name__, str(self.cause))
        else:
            stri = self.message
        if self.details:
            stri += "\n" + self.details
        return stri


T = TypeVar('T')


class ResultQueue(Generic[T]):
    """
    Class implementing a basic message queue via a asyncio.Queue.

    Writing:
        Synchronously (using a different thread/executor)
        acts like a regular Queue, but can be "ended"/"closed" by
        calling the end method, which marks the end of reading and writing.

    Reading:
        Asynchronously (asyncio).
        Can be read by (async.) iterating over it or by using get().

    Queue can be ended with an error (ResultError), which will be raised when reading over it.
    """
    def __init__(self):
        self.queue = janus.Queue()
        self.was_ended_put = False
        self.was_ended_get = False

    def put(self, obj):
        if self.was_ended_put:
            raise EOFError("ResultQueue was already ended.")
        self.queue.sync_q.put(obj)

    def end(self):
        self.was_ended_put = True
        self.queue.sync_q.put(EndResultQueue())

    def end_with_error(self, error: ResultError):
        self.was_ended_put = True
        self.queue.sync_q.put(error)

    async def get(self):
        """
        Returns the next element, or raises it, if is is an instance of
        EndResultQueue. If it is, the queue is also marked as ended,
        prohibiting calling get again.
        If a raised EndResultQueue is an instance of ResultError,
        then the queue was ended with an error.
        """
        if self.was_ended_get:
            raise EOFError("ResultQueue was already ended.")
        top = await self.queue.async_q.get()
        if isinstance(top, EndResultQueue):
            self.was_ended_get = True
            raise top
        return top

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.was_ended_get:
            raise StopAsyncIteration
        try:
            top = await self.get()
        except EndResultQueue as end:
            if isinstance(end, ResultError):
                raise end
            raise StopAsyncIteration
        return top
    pass


class MultiResultQueue(Generic[T]):
    """
    Class bundling multiple ResultQueues into one class for easier reading.

    Provides following values while (async.) iterating:
        When a result queue returned a value:
            (id_of_queue, value_put_into_queue, False)
        When a result queue was ended without an error:
            (id_of_queue, None, True)
        When a result queue was ended with an error:
            (id_of_queue, result_error_object, True)

    The end of iteration is reached when all ResultQueues are ended.

    A list of ids and ResultQueues in it can also be manually retrieved.
    """

    def __init__(self, dict_of_queues: Dict[ResultQueue, str]):
        """
        Creates the multi queue.
        :param dict_of_queues: The parameter has to contain the result queues in a dict. Key is the queue and value a string
                               identifier for this queue.
        """
        self.dict_of_queues = dict_of_queues
        self.ended = False

    def ids(self):
        return list(self.dict_of_queues.values())

    def __aiter__(self):
        # pending_in_iteration is a dict that maps the asyncio tasks created from the queue.get methods to the
        # queue objects, so that when a get task finishes the queue that the task belongs to can be found
        self.pending_in_iteration = {}
        self.done_list = []
        for queue in self.dict_of_queues.keys():
            task = asyncio.ensure_future(queue.get())
            self.pending_in_iteration[task] = queue
        return self

    async def __anext__(self):
        if self.ended:
            raise StopAsyncIteration

        # Check if we still have done elements to process, if not, get next ones.
        if len(self.done_list) > 0:
            done = self.done_list.pop()
        else:
            done_set, _ = await asyncio.wait(self.pending_in_iteration.keys(), return_when=asyncio.FIRST_COMPLETED)
            self.done_list = list(done_set)
            done = self.done_list.pop()

        # Delete from pending list and get the queue for this done task.
        queue = self.pending_in_iteration[done]
        del self.pending_in_iteration[done]

        if done.exception():
            # Deal with exceptions (=> done was ended)
            if isinstance(done.exception(), ResultError):
                # Provide error for queue
                result = (self.dict_of_queues[queue], done.exception(), True)
            elif isinstance(done.exception(), EndResultQueue):
                # Provide end value for queue
                result = (self.dict_of_queues[queue], None,             True)
            else:
                raise done.exception()
        else:
            # Provide value from queue
            result = (self.dict_of_queues[queue], done.result(), False)

            # Add next get call to list of pending tasks.
            new_task = asyncio.ensure_future(queue.get())
            self.pending_in_iteration[new_task] = queue

        # If nothing is pending, then all queues were ended.
        if len(self.pending_in_iteration) <= 0:
            self.ended = True

        return result
