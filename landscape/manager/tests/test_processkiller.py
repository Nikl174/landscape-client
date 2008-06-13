from datetime import datetime
import signal
import subprocess

from landscape.tests.helpers import LandscapeTest, ManagerHelper
from landscape.reactor import FakeReactor
from landscape.lib.process import ProcessInformation
from landscape.monitor.tests.test_activeprocessinfo import SampleDataBuilder

from landscape.manager.manager import SUCCEEDED, FAILED
from landscape.manager.processkiller import (
    ProcessKiller, ProcessNotFoundError, ProcessMismatchError,
    SignalProcessError)


def get_active_process():
    return subprocess.Popen(["python", "-c", "raw_input()"],
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)


def get_missing_pid():
    popen = subprocess.Popen(["hostname"], stdout=subprocess.PIPE)
    popen.wait()
    return popen.pid


class ProcessKillerTests(LandscapeTest):
    """Tests for L{ProcessKiller}."""

    helpers = [ManagerHelper]

    def setUp(self):
        LandscapeTest.setUp(self)
        self.sample_dir = self.make_dir()
        self.builder = SampleDataBuilder(self.sample_dir)
        self.process_info = ProcessInformation(proc_dir=self.sample_dir,
                                               jiffies=1, boot_time=10)
        self.signaller = ProcessKiller(process_info=self.process_info)
        service = self.broker_service
        service.message_store.set_accepted_types(["operation-result"])

    def _test_signal_name(self, signame, signum):
        self.manager.add(self.signaller)
        self.builder.create_data(100, self.builder.RUNNING,
                                 uid=1000, gid=1000, started_after_uptime=10,
                                 process_name="ooga")

        kill = self.mocker.replace("os.kill", passthrough=False)
        kill(100, signum)
        self.mocker.replay()

        self.manager.dispatch_message(
            {"type": "signal-process",
             "operation-id": 1,
             "pid": 100, "name": "ooga",
             "start-time": 20, "signal": signame})

    def test_kill_process_signal(self):
        """
        When specifying the signal name as 'KILL', os.kill should be passed the
        KILL signal.
        """
        self._test_signal_name("KILL", signal.SIGKILL)

    def test_end_process_signal(self):
        """
        When specifying the signal name as 'TERM', os.kill should be passed the
        TERM signal.
        """
        self._test_signal_name("TERM", signal.SIGTERM)

    def _test_signal_real_process(self, signame):
        """
        When a 'signal-process' message is received the plugin should
        signal the appropriate process and generate an operation-result
        message with details of the outcome.  Data is gathered from
        internal plugin methods to get the start time of the test
        process being signalled.
        """
        process_info_factory = ProcessInformation()
        signaller = ProcessKiller()
        signaller.register(self.manager)
        popen = get_active_process()
        process_info = process_info_factory.get_process_info(popen.pid)
        self.assertNotEquals(process_info, None)
        start_time = process_info["start-time"]

        self.manager.dispatch_message(
            {"type": "signal-process",
             "operation-id": 1,
             "pid": popen.pid, "name": "python",
             "start-time": start_time, "signal": signame})
        # We're waiting on the child process here so that we (the
        # parent process) consume it's return code; this prevents it
        # from becoming a zombie and makes the test do a better job of
        # reflecting the real world.
        return_code = popen.wait()
        # The return code is negative if the process was terminated by
        # a signal.
        self.assertTrue(return_code < 0)
        process_info = process_info_factory.get_process_info(popen.pid)
        self.assertEquals(process_info, None)

        service = self.broker_service
        self.assertMessages(service.message_store.get_pending_messages(),
                            [{"type": "operation-result",
                              "status": SUCCEEDED, "operation-id": 1}])

    def test_kill_real_process(self):
        self._test_signal_real_process("KILL")

    def test_end_real_process(self):
        self._test_signal_real_process("TERM")

    def test_signal_missing_process(self):
        """
        When a 'signal-process' message is received for a process that
        no longer the exists the plugin should generate an error.
        """
        self.log_helper.ignore_errors(ProcessNotFoundError)
        self.manager.add(self.signaller)

        pid = get_missing_pid()
        self.manager.dispatch_message(
            {"operation-id": 1, "type": "signal-process",
             "pid": pid, "name": "zsh", "start-time": 110,
             "signal": "KILL"})
        expected_text = ("ProcessNotFoundError: The process zsh with PID %d "
                         "that started at 110 was not found" % (pid,))

        service = self.broker_service
        self.assertMessages(service.message_store.get_pending_messages(),
                            [{"type": "operation-result",
                              "operation-id": 1,
                              "status": FAILED,
                              "result-text": expected_text}])
        self.assertTrue("ProcessNotFoundError" in self.logfile.getvalue())


    def test_signal_process_start_time_mismatch(self):
        """
        When a 'signal-process' message is received with a mismatched
        start time the plugin should generate an error.
        """
        self.log_helper.ignore_errors(ProcessMismatchError)
        self.manager.add(self.signaller)
        pid = get_missing_pid()
        self.builder.create_data(pid, self.builder.RUNNING,
                                 uid=1000, gid=1000, started_after_uptime=10,
                                 process_name="hostname")

        self.manager.dispatch_message(
            {"operation-id": 1, "type": "signal-process",
             "pid": pid, "name": "python",
             "start-time": 11, "signal": "KILL"})
        expected_time = datetime.utcfromtimestamp(11)
         # boot time + proc start time = 20
        actual_time = datetime.utcfromtimestamp(20)
        expected_text = ("ProcessMismatchError: The process python with "
                         "PID %d that started at %s was not found.  A "
                         "process with the same PID that started at %s "
                         "was found and not sent the KILL signal"
                         % (pid, expected_time, actual_time))

        service = self.broker_service
        self.assertMessages(service.message_store.get_pending_messages(),
                            [{"type": "operation-result",
                              "operation-id": 1,
                              "status": FAILED,
                              "result-text": expected_text}])
        self.assertTrue("ProcessMismatchError" in self.logfile.getvalue())

    def test_signal_process_race(self):
        """
        Before trying to signal a process it first checks to make sure a
        process with a matching PID and name exist. It's possible for the
        process to disappear after checking the process exists and before
        sending the signal; a generic error should be raised in that case.
        """
        self.log_helper.ignore_errors(SignalProcessError)
        pid = get_missing_pid()
        self.builder.create_data(pid, self.builder.RUNNING,
                                 uid=1000, gid=1000, started_after_uptime=10,
                                 process_name="hostname")
        self.assertRaises(SignalProcessError,
                          self.signaller.signal_process, pid,
                          "hostname", 20, "KILL")

        self.manager.add(self.signaller)
        self.manager.dispatch_message(
            {"operation-id": 1, "type": "signal-process",
             "pid": pid, "name": "hostname", "start-time": 20,
             "signal": "KILL"})
        expected_text = ("SignalProcessError: Attempting to send the KILL "
                         "signal to the process hostname with PID %d failed"
                         % (pid,))

        service = self.broker_service
        self.assertMessages(service.message_store.get_pending_messages(),
                            [{"type": "operation-result",
                              "operation-id": 1,
                              "status": FAILED,
                              "result-text": expected_text}])
        self.assertTrue("SignalProcessError" in self.logfile.getvalue())