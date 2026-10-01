"""供 Qt 页面复用的可取消业务请求。"""

import asyncio
from threading import Event

from PySide6.QtCore import QObject, QThread, Signal


class ApiTask(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, api, name, params, parent=None):
        """启动工作线程前保存接口操作名称及其关键字参数。"""
        super().__init__(parent)
        self.api, self.name, self.params = api, name, params
        self.loop = self.task = None
        self.cancelled = Event()

    def run(self):
        """执行异步 HTTP 请求；内存测试客户端则使用同步调用。"""
        try:
            result = asyncio.run(self._run())
            if not self.cancelled.is_set():
                self.succeeded.emit(result)
        except asyncio.CancelledError:
            self.failed.emit("请求已取消；服务端可能已完成操作，可刷新查看。")
        except Exception as exc:
            self.failed.emit(str(exc))

    async def _run(self):
        """在工作线程的事件循环中创建可中断的操作。"""
        self.loop, self.task = asyncio.get_running_loop(), asyncio.current_task()
        if self.cancelled.is_set():
            raise asyncio.CancelledError
        if hasattr(self.api, "invoke_async"):
            return await self.api.invoke_async(self.name, **self.params)
        return getattr(self.api, self.name)(**self.params)

    def cancel(self):
        """页面或窗口关闭时立即取消网络读写。"""
        self.cancelled.set()
        if self.loop and self.task:
            try:
                self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError:
                pass


class TaskRunner(QObject):
    idle = Signal()
    failed = Signal(str)

    def __init__(self, api, parent=None):
        """为每个页面管理至多一个正在执行的操作。"""
        super().__init__(parent)
        self.api, self.worker = api, None

    @property
    def busy(self):
        return self.worker is not None

    def start(self, name, callback, **params):
        """启动具名接口操作，并在界面线程中交付结果。"""
        if self.busy:
            return False
        self.worker = ApiTask(self.api, name, params, self)
        self.worker.succeeded.connect(callback)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self._finished)
        self.worker.start()
        return True

    def cancel(self):
        """存在正在执行的页面请求时将其取消。"""
        if self.worker:
            self.worker.cancel()

    def _finished(self):
        """释放已完成的工作线程，并通知窗口的关闭处理逻辑。"""
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.idle.emit()
