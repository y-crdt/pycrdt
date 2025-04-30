from contextlib import AsyncExitStack

from anyio import create_task_group


class StartStopContextManager:
    def __init__(self, service):
        self._service = service

    async def __aenter__(self):
        async with AsyncExitStack() as exit_stack:
            self._task_group = await exit_stack.enter_async_context(create_task_group())
            await self._task_group.start(self._service.start)
            self._exit_stack = exit_stack.pop_all()
        await self._service.started.wait()
        return self._service

    async def __aexit__(self, exc_type, exc_value, exc_tb):
        self._task_group.start_soon(self._service.stop)
        return await self._exit_stack.__aexit__(exc_type, exc_value, exc_tb)
