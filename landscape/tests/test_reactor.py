import thread
import types
import time

from landscape.reactor import Reactor, FakeReactor, TwistedReactor

from landscape.tests.helpers import LandscapeTest


class ReactorTest(LandscapeTest):

    def get_reactor(self):
        return Reactor()

    def test_call_later(self):
        reactor = self.get_reactor()
        called = []
        def dummy():
            called.append("Hello!")
            reactor.stop()
        reactor.call_later(0, dummy)
        reactor.run()
        self.assertEquals(called, ["Hello!"])

    def test_call_later_with_args(self):
        reactor = self.get_reactor()
        called = []
        def dummy(a, b=3):
            called.append((a, b))
            reactor.stop()
        reactor.call_later(0, dummy, "a", b="b")
        reactor.run()
        self.assertEquals(called, [("a", "b")])

    def test_call_later_only_calls_once(self):
        reactor = self.get_reactor()
        called = []
        def append():
            called.append("Hey!")
            return True
        reactor.call_later(0, append)
        reactor.call_later(0.3, reactor.stop)
        reactor.run()
        self.assertEquals(len(called), 1)

    def test_cancel_call(self):
        reactor = self.get_reactor()
        called = []
        id = reactor.call_later(0, called.append, "hi")
        reactor.cancel_call(id)
        reactor.call_later(0.3, reactor.stop)
        reactor.run()
        self.assertEquals(len(called), 0)

    def test_call_every(self):
        reactor = self.get_reactor()
        called = []
        reactor.call_every(0.01, called.append, "hi")
        reactor.call_later(0.5, reactor.stop)
        reactor.run()
        self.failUnless(5 < len(called) < 100, len(called))

    def test_cancel_call_every(self):
        reactor = self.get_reactor()
        called = []
        id = reactor.call_every(0, called.append, "hi")
        reactor.cancel_call(id)
        reactor.call_later(0.3, reactor.stop)
        reactor.run()
        self.assertEquals(len(called), 0)

    def test_cancel_call_every_after_first_call(self):
        reactor = self.get_reactor()
        called = []
        def cancel_call():
            reactor.cancel_call(id)
            called.append("hi")
        id = reactor.call_every(0, cancel_call)
        reactor.call_later(0.1, reactor.stop)
        reactor.run()
        self.assertEquals(len(called), 1)

    def test_cancel_later_called(self):
        reactor = self.get_reactor()
        id = reactor.call_later(0, lambda: None)
        reactor.call_later(0.3, reactor.stop)
        reactor.run()
        reactor.cancel_call(id)

    def test_cancel_call_twice(self):
        """
        Multiple cancellations of a call will not raise any exceptions.
        """
        reactor = self.get_reactor()
        id = reactor.call_later(3, lambda: None)
        reactor.cancel_call(id)
        reactor.cancel_call(id)

    def test_reactor_doesnt_leak(self):
        reactor = self.get_reactor()
        called = []
        reactor.call_later(0, called.append, "hi")
        reactor = self.get_reactor()
        reactor.call_later(0.01, reactor.stop)
        reactor.run()
        self.assertEquals(called, [])

    def test_event(self):
        reactor = self.get_reactor()
        called = []
        def handle_foobar():
            called.append(True)
        reactor.call_on("foobar", handle_foobar)
        reactor.fire("foobar")
        self.assertEquals(called, [True])

    def test_event_with_args(self):
        reactor = self.get_reactor()
        called = []
        def handle_foobar(a, b=3):
            called.append((a, b))

        reactor.call_on("foobar", handle_foobar)
        reactor.fire("foobar", "a", b=6)
        self.assertEquals(called, [("a", 6)])

    def test_events(self):
        reactor = self.get_reactor()
        called = []

        reactor.call_on("foobar", called.append)
        reactor.call_on("foobar", called.append)

        reactor.fire("foobar", "a")
        self.assertEquals(called, ["a", "a"])

    def test_events_result(self):
        reactor = self.get_reactor()

        generator = iter([1, 2, 3]).next

        reactor.call_on("foobar", generator)
        reactor.call_on("foobar", generator)
        reactor.call_on("foobar", generator)

        self.assertEquals(reactor.fire("foobar"), [1, 2, 3])

    def test_event_priority(self):
        """
        Event callbacks should be able to be scheduled with a priority
        which specifies the order they are run in.
        """
        reactor = self.get_reactor()
        called = []
        reactor.call_on("foobar", lambda: called.append(5), priority=5)
        reactor.call_on("foobar", lambda: called.append(3), priority=3)
        reactor.call_on("foobar", lambda: called.append(4), priority=4)
        reactor.fire("foobar")
        self.assertEquals(called, [3, 4, 5])

    def test_default_priority(self):
        """
        The default priority of an event callback should be 0.
        """
        reactor = self.get_reactor()
        called = []
        reactor.call_on("foobar", lambda: called.append(1), 1)
        reactor.call_on("foobar", lambda: called.append(0))
        reactor.call_on("foobar", lambda: called.append(-1), -1)
        reactor.fire("foobar")
        self.assertEquals(called, [-1, 0, 1])

    def test_exploding_event_handler(self):
        self.log_helper.ignore_errors(ZeroDivisionError)
        reactor = self.get_reactor()
        called = []
        def handle_one(): called.append(1)
        def handle_two():
            1/0
        def handle_three(): called.append(3)

        reactor.call_on("foobar", handle_one)
        reactor.call_on("foobar", handle_two)
        reactor.call_on("foobar", handle_three)

        reactor.fire("foobar")
        self.assertTrue(1 in called)
        self.assertTrue(3 in called)
        self.assertTrue("handle_two" in self.logfile.getvalue())
        self.assertTrue("ZeroDivisionError" in self.logfile.getvalue(),
                        self.logfile.getvalue())

    def test_weird_event_type(self):
        #This can be useful for "namespaced" event types
        reactor = self.get_reactor()
        called = []
        reactor.call_on(("message", "foobar"), called.append)
        reactor.fire(("message", "foobar"), "namespaced!")
        self.assertEquals(called, ["namespaced!"])

    def test_nonexistent_event_type(self):
        reactor = self.get_reactor()
        reactor.fire("Blat!")

    def test_cancel_event(self):
        reactor = self.get_reactor()
        called = []
        id = reactor.call_on("foobar", called.append)
        reactor.cancel_call(id)
        reactor.fire("foobar")
        self.assertEquals(called, [])

    def test_run_stop_events(self):
        reactor = self.get_reactor()

        called = []
        called_copy = []

        reactor.call_on("run", lambda: called.append("run"))
        reactor.call_on("stop", lambda: called.append("stop"))
        reactor.call_later(0.0, lambda: called_copy.extend(called))
        reactor.call_later(0.5, reactor.stop)

        reactor.run()

        self.assertEquals(called, ["run", "stop"])
        self.assertEquals(called_copy, ["run"])

    def test_call_in_thread(self):
        reactor = self.get_reactor()

        called = []

        def f(a, b, c):
            called.append((a, b, c))
            called.append(thread.get_ident())

        reactor.call_in_thread(None, None, f, 1, 2, c=3)

        while not called:
            pass

        reactor.call_later(0.7, reactor.stop)
        reactor.run()

        self.assertEquals(len(called), 2)
        self.assertEquals(called[0], (1, 2, 3))

        if not isinstance(reactor, FakeReactor):
            self.assertNotEquals(called[1], thread.get_ident())

    def test_call_in_thread_with_callback(self):
        reactor = self.get_reactor()

        called = []

        def f():
            called.append("f")
            return 32

        def callback(result):
            called.append("callback")
            called.append(result)

        def errback(type, value, traceback):
            called.append("errback")
            called.append((type, value, traceback))

        reactor.call_in_thread(callback, errback, f)

        while not called:
            pass

        reactor.call_later(0.7, reactor.stop)
        reactor.run()

        self.assertEquals(called, ["f", "callback", 32])

    def test_call_in_thread_with_errback(self):
        reactor = self.get_reactor()

        called = []

        def f():
            called.append("f")
            1/0

        def callback(result):
            called.append("callback")
            called.append(result)

        def errback(*args):
            called.append("errback")
            called.append(args)

        reactor.call_in_thread(callback, errback, f)

        while not called:
            pass

        reactor.call_later(0.7, reactor.stop)
        reactor.run()

        self.assertEquals(called[:2], ["f", "errback"])
        self.assertEquals(len(called), 3)
        self.assertEquals(called[2][0], ZeroDivisionError)
        self.assertTrue(isinstance(called[2][1], ZeroDivisionError))
        self.assertTrue(isinstance(called[2][2], types.TracebackType))

    def test_call_in_thread_with_error_but_no_errback(self):
        self.log_helper.ignore_errors(ZeroDivisionError)
        reactor = self.get_reactor()

        called = []

        def f():
            called.append("f")
            1/0

        def callback(result):
            called.append("callback")
            called.append(result)

        reactor.call_in_thread(callback, None, f)

        while not called:
            pass

        reactor.call_later(0.7, reactor.stop)
        reactor.run()

        self.assertEquals(called, ["f"])
        self.assertTrue("ZeroDivisionError" in self.logfile.getvalue(),
                        self.logfile.getvalue())

    def test_call_in_main(self):
        reactor = self.get_reactor()

        called = []

        def f():
            called.append("f")
            called.append(thread.get_ident())
            reactor.call_in_main(g, 1, 2, c=3)

        def g(a, b, c):
            called.append("g")
            called.append(thread.get_ident())

        reactor.call_in_thread(None, None, f)

        while not called:
            pass

        reactor.call_later(0.7, reactor.stop)
        reactor.run()

        self.assertEquals(len(called), 4)
        self.assertEquals(called[0], "f")
        if not isinstance(reactor, FakeReactor):
            self.assertNotEquals(called[1], thread.get_ident())
        self.assertEquals(called[2], "g")
        self.assertEquals(called[3], thread.get_ident())


class FakeReactorTest(ReactorTest):

    def get_reactor(self):
        return FakeReactor()

    def test_incremental_advance(self):
        reactor = self.get_reactor()

        called = []
        def callback():
            called.append(True)

        reactor.call_later(2, callback)

        self.assertFalse(called)
        reactor.advance(1)
        self.assertFalse(called)
        reactor.advance(1)
        self.assertTrue(called)

    def test_time(self):
        """
        The time method of FakeReactor should return the current
        simulated time.
        """
        reactor = self.get_reactor()
        self.assertEquals(reactor.time(), 0)
        reactor.advance(10.5)
        self.assertEquals(reactor.time(), 10.5)
        reactor.advance(3)
        self.assertEquals(reactor.time(), 13.5)


class TwistedReactorTest(ReactorTest):

    def get_reactor(self):
        return TwistedReactor()

    def test_real_time(self):
        reactor = self.get_reactor()
        self.assertTrue(reactor.time() - time.time() < 3)


# FIXME This is here because the GObject reactor frequently causes the
# test suite to segfault.  When it becomes stable this can be removed.
del ReactorTest