import os

from twisted.internet.defer import Deferred, succeed

from landscape.lib.dbus_util import get_bus
from landscape.lib.lock import lock_path, LockError
from landscape.lib.log import log_failure
from landscape.deployment import Configuration, init_logging
from landscape.package.store import PackageStore
from landscape.broker.remote import RemoteBroker


class PackageTaskHandler(object):

    queue_name = "default"

    def __init__(self, package_store, package_facade, remote_broker):
        self._store = package_store
        self._facade = package_facade
        self._broker = remote_broker
        self._channels_reloaded = False

    def ensure_channels_reloaded(self):
        if not self._channels_reloaded:
            self._channels_reloaded = True
            self._facade.reload_channels()

    def run(self):
        return self.handle_tasks()

    def handle_tasks(self):
        deferred = Deferred()
        self._handle_next_task(None, deferred)
        return deferred

    def _handle_next_task(self, result, deferred, last_task=None):
        if last_task is not None:
            # Last task succeeded.  We can safely kill it now.
            last_task.remove()

        task = self._store.get_next_task(self.queue_name)

        if task:
            # We have another task.  Let's handle it.
            result = self.handle_task(task)
            result.addCallback(self._handle_next_task, deferred, task)
            result.addErrback(deferred.errback)

        else:
            # No more tasks!  We're done!
            deferred.callback(None)

    def handle_task(self, task):
        return succeed(None)


def run_task_handler(cls, args, reactor=None):
    from twisted.internet.glib2reactor import install
    install()

    # please only pass reactor when you have totally mangled everything with
    # mocker. Otherwise bad things will happen.
    if reactor is None:
        from twisted.internet import reactor

    program_name = cls.queue_name

    config = Configuration()
    config.load(args)

    package_directory = os.path.join(config.data_path, "package")
    if not os.path.isdir(package_directory):
        os.mkdir(package_directory)

    lock_filename = os.path.join(package_directory, program_name + ".lock")
    try:
        lock_path(lock_filename)
    except LockError:
        if config.quiet:
            raise SystemExit()
        raise SystemExit("error: package %s is already running"
                         % program_name)


    init_logging(config, "package-" + program_name)

    store_filename = os.path.join(package_directory, "database")

    # Setup our umask for Smart to use, this needs to setup file permissions to
    # 0644 so...
    os.umask(022)

    # Delay importing of the facade so that we don't
    # import Smart unless we need to.
    from landscape.package.facade import SmartFacade

    package_store = PackageStore(store_filename)
    package_facade = SmartFacade()
    remote = RemoteBroker(get_bus(config.bus))

    handler = cls(package_store, package_facade, remote)

    def got_err(failure):
        log_failure(failure)

    result = handler.run()
    result.addErrback(got_err)
    result.addBoth(lambda ignored: reactor.callLater(0, reactor.stop))

    reactor.run()

    return result