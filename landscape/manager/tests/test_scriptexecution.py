import os
import pwd
import tempfile

from twisted.internet.defer import gatherResults
from twisted.internet import reactor

from landscape.manager.scriptexecution import (ScriptExecution,
                                               ProcessTimeLimitReachedError)
from landscape.manager.manager import SUCCEEDED, FAILED
from landscape.tests.helpers import (LandscapeTest, LandscapeIsolatedTest,
                                     ManagerHelper, RemoteBrokerHelper)
from landscape.tests.mocker import ANY, ARGS, MATCH

# Test GPG-signing

class StubProcessFactory(object):
    """
    A L{IReactorProcess} provider which records L{spawnProcess} calls and
    allows tests to get at the protocol.
    """
    def __init__(self):
        self.spawns = []

    def spawnProcess(self, protocol, executable, args=(), env={}, path=None,
                    uid=None, gid=None, usePTY=0, childFDs=None):
        self.spawns.append((protocol, executable, args,
                            env, path, uid, gid, usePTY, childFDs))


class DummyProcess(object):
    """A process (transport) that doesn't do anything."""
    def __init__(self):
        self.signals = []

    def signalProcess(self, signal):
        self.signals.append(signal)

    def closeChildFD(self, fd):
        pass


class RunScriptTests(LandscapeTest):

    helpers = [ManagerHelper]

    def setUp(self):
        super(RunScriptTests, self).setUp()
        self.plugin = ScriptExecution()
        self.manager.add(self.plugin)

    def test_basic_run(self):
        """
        The plugin returns a Deferred resulting in the output of basic
        commands.
        """
        result = self.plugin.run_script("/bin/sh", "echo hi")
        result.addCallback(self.assertEquals, "hi\n")
        return result

    def test_other_interpreter(self):
        """Non-shell interpreters can be specified."""
        result = self.plugin.run_script("/usr/bin/python", "print 'hi'")
        result.addCallback(self.assertEquals, "hi\n")
        return result

    def test_concurrent(self):
        """Scripts run with the ScriptExecution plugin are run concurrently."""
        fifo = self.make_path()
        os.mkfifo(fifo)
        # If the first process is blocking on a fifo, and the second process
        # wants to write to the fifo, the only way this will complete is if
        # run_script is truly async
        d1 = self.plugin.run_script("/bin/sh", "cat " + fifo)
        d2 = self.plugin.run_script("/bin/sh", "echo hi > " + fifo)
        d1.addCallback(self.assertEquals, "hi\n")
        d2.addCallback(self.assertEquals, "")
        return gatherResults([d1, d2])

    def test_user(self):
        """
        Running a script as a particular user calls
        C{IReactorProcess.spawnProcess} with an appropriate C{uid} argument and
        with the user's primary group as the C{gid} argument.
        """
        # ignore the call to chown!
        mock_chown = self.mocker.replace("os.chown", passthrough=False)
        mock_chown(ARGS)

        factory = StubProcessFactory()
        self.plugin.process_factory = factory
        uid = os.getuid()
        info = pwd.getpwuid(uid)
        username = info.pw_name
        gid = info.pw_gid

        self.mocker.replay()

        result = self.plugin.run_script("/bin/sh", "echo hi", user=username)

        self.assertEquals(len(factory.spawns), 1)
        spawn = factory.spawns[0]
        self.assertEquals(spawn[5], uid)
        self.assertEquals(spawn[6], gid)
        result.addCallback(self.assertEquals, "foobar")

        protocol = spawn[0]
        protocol.childDataReceived(1, "foobar")
        for fd in (0, 1, 2):
            protocol.childConnectionLost(fd)
        protocol.processEnded(None)
        return result

    def test_limit_size(self):
        """Data returned from the command is limited."""
        factory = StubProcessFactory()
        self.plugin.process_factory = factory
        self.plugin.size_limit = 100
        result = self.plugin.run_script("", "")
        result.addCallback(self.assertEquals, "x"*100)

        protocol = factory.spawns[0][0]
        protocol.childDataReceived(1, "x"*200)
        for fd in (0, 1, 2):
            protocol.childConnectionLost(fd)
        protocol.processEnded(None)

        return result

    def test_limit_time(self):
        """
        The process only lasts for a certain number of seconds.
        """
        result = self.plugin.run_script("/bin/sh", "cat", time_limit=500)
        self.manager.reactor.advance(501)
        self.assertFailure(result, ProcessTimeLimitReachedError)
        return result

    def test_limit_time_accumulates_data(self):
        """
        Data from processes that time out should still be accumulated and
        available from the exception object that is raised.
        """
        factory = StubProcessFactory()
        self.plugin.process_factory = factory
        result = self.plugin.run_script("", "", time_limit=500)
        protocol = factory.spawns[0][0]
        protocol.makeConnection(DummyProcess())
        protocol.childDataReceived(1, "hi\n")
        self.manager.reactor.advance(501)
        protocol.processEnded(None)
        def got_error(f):
            self.assertTrue(f.check(ProcessTimeLimitReachedError))
            self.assertEquals(f.value.data, "hi\n")
        result.addErrback(got_error)
        return result

    def test_time_limit_canceled_after_success(self):
        """
        The timeout call is cancelled after the script terminates.
        """
        factory = StubProcessFactory()
        self.plugin.process_factory = factory
        result = self.plugin.run_script("", "", time_limit=500)
        protocol = factory.spawns[0][0]
        transport = DummyProcess()
        protocol.makeConnection(transport)
        protocol.childDataReceived(1, "hi\n")
        protocol.processEnded(None)
        self.manager.reactor.advance(501)
        self.assertEquals(transport.signals, [])

    def test_cancel_doesnt_blow_after_success(self):
        """
        When the process ends successfully and is immediately followed by the
        timeout, the output should still be in the failure and nothing bad will
        happen!
        [regression test: killing of the already-dead process would blow up.]
        """
        factory = StubProcessFactory()
        self.plugin.process_factory = factory
        result = self.plugin.run_script("", "", time_limit=500)
        protocol = factory.spawns[0][0]
        protocol.makeConnection(DummyProcess())
        protocol.childDataReceived(1, "hi")
        protocol.processEnded(None)
        self.manager.reactor.advance(501)
        def got_error(f):
            print f
            self.assertTrue(f.check(ProcessTimeLimitReachedError))
            self.assertEquals(f.value.data, "hi\n")
        result.addErrback(got_error)
        return result

    def test_script_is_owned_by_user(self):
        """
        This is a very white-box test. When a script is generated, it must be
        created such that data NEVER gets into it before the file has the
        correct permissions. Therefore os.chmod and os.chown must be called
        before data is written.
        """
        uid = os.getuid()
        gid = os.getgid()

        mock_chown = self.mocker.replace("os.chown", passthrough=False)
        mock_chmod = self.mocker.replace("os.chmod", passthrough=False)
        mock_mkstemp = self.mocker.replace("tempfile.mkstemp",
                                           passthrough=False)
        mock_fdopen = self.mocker.replace("os.fdopen", passthrough=False)
        process_factory = self.mocker.mock()
        self.plugin.process_factory = process_factory

        self.mocker.order()

        self.expect(mock_mkstemp()).result((99, "tempo!"))

        script_file = mock_fdopen(99, "w")
        mock_chmod("tempo!", 0700)
        mock_chown("tempo!", uid, 0)
        # The contents are written *after* the permissions have been set up!
        script_file.write("#!interpreter\ncode")
        script_file.close()

        process_factory.spawnProcess(ANY, ANY, uid=uid, gid=gid)

        self.mocker.replay()

        # We don't really care about the deferred that's returned, as long as
        # those things happened in the correct order.
        self.plugin.run_script("interpreter", "code",
                               user=pwd.getpwuid(uid)[0])

    def test_script_removed(self):
        """
        The script is removed after it is finished.
        """
        mock_mkstemp = self.mocker.replace("tempfile.mkstemp",
                                           passthrough=False)
        fd, filename = tempfile.mkstemp()
        self.expect(mock_mkstemp()).result((fd, filename))
        self.mocker.replay()
        d = self.plugin.run_script("/bin/sh", "true")
        d.addCallback(lambda ign: self.assertFalse(os.path.exists(filename)))
        return d

class ScriptExecutionMessageTests(LandscapeIsolatedTest):
    helpers = [ManagerHelper]

    def setUp(self):
        super(ScriptExecutionMessageTests, self).setUp()
        self.broker_service.message_store.set_accepted_types(
            ["operation-result"])
        self.manager.config.script_users = "ALL"

    def _verify_script(self, executable, interp, code):
        """
        Given spawnProcess arguments, check to make sure that the temporary
        script has the correct content.
        """
        data = open(executable, "r").read()
        self.assertEquals(data, "#!%s\n%s" % (interp, code))


    def _send_script(self, interpreter, code, operation_id=123,
                     user=pwd.getpwuid(os.getuid())[0],
                     time_limit=None):
        return self.manager.dispatch_message(
            {"type": "execute-script",
             "interpreter": interpreter,
             "code": code,
             "operation-id": operation_id,
             "username": user,
             "time-limit": time_limit})

    def test_success(self):
        """
        When a C{execute-script} message is received from the server, the
        specified script will be run and an operation-result will be sent back
        to the server.
        """
        # Let's use a stub process factory, because otherwise we don't have
        # access to the deferred.
        factory = StubProcessFactory()

        # ignore the call to chown!
        mock_chown = self.mocker.replace("os.chown", passthrough=False)
        mock_chown(ARGS)

        self.manager.add(ScriptExecution(process_factory=factory))

        self.mocker.replay()
        result = self._send_script("python", "print 'hi'")

        self._verify_script(factory.spawns[0][1], "python", "print 'hi'")
        self.assertMessages(
            self.broker_service.message_store.get_pending_messages(), [])

        # Now let's simulate the completion of the process
        factory.spawns[0][0].childDataReceived(1, "hi!\n")
        factory.spawns[0][0].processEnded(None)

        def got_result(r):
            self.assertMessages(
                self.broker_service.message_store.get_pending_messages(),
                [{"type": "operation-result",
                  "operation-id": 123,
                  "status": SUCCEEDED,
                  "result-text": u"hi!\n"}])
        result.addCallback(got_result)
        return result

    def test_user(self):
        """A user can be specified in the message."""
        uid = os.getuid()
        gid = os.getgid()
        username = pwd.getpwuid(uid)[0]

        # ignore the call to chown!
        mock_chown = self.mocker.replace("os.chown", passthrough=False)
        mock_chown(ARGS)

        def spawn_called(protocol, filename, uid, gid):
            protocol.childDataReceived(1, "hi!\n")
            protocol.processEnded(None)
            self._verify_script(filename, "python", "print 'hi'")

        process_factory = self.mocker.mock()
        process_factory.spawnProcess(ANY, ANY, uid=uid, gid=gid)
        self.mocker.call(spawn_called)

        self.mocker.replay()

        self.manager.add(ScriptExecution(process_factory=process_factory))

        result = self._send_script("python", "print 'hi'", user=username)
        return result


    def test_timeout(self):
        """
        If a L{ProcessTimeLimitReachedError} is fired back, the
        operation-result should have a failed status.
        """
        factory = StubProcessFactory()
        self.manager.add(ScriptExecution(process_factory=factory))

        # ignore the call to chown!
        mock_chown = self.mocker.replace("os.chown", passthrough=False)
        mock_chown(ARGS)

        self.mocker.replay()
        result = self._send_script("foo", "bar", time_limit=30)
        self._verify_script(factory.spawns[0][1], "foo", "bar")

        protocol = factory.spawns[0][0]
        protocol.makeConnection(DummyProcess())
        protocol.childDataReceived(2, "ONOEZ")
        self.manager.reactor.advance(31)
        protocol.processEnded(None)

        def got_result(r):
            self.assertMessages(
                self.broker_service.message_store.get_pending_messages(),
                [{"type": "operation-result",
                  "operation-id": 123,
                  "status": FAILED,
                  "result-text": u"ONOEZ"}])
        result.addCallback(got_result)
        return result

    def test_configured_users(self):
        """
        Messages which try to run a script as a user that is not allowed should
        be rejected.
        """
        self.manager.add(ScriptExecution())
        self.manager.config.script_users = "landscape, nobody"
        result = self._send_script("foo", "bar", user="whatever")
        def got_result(r):
            self.assertMessages(
                self.broker_service.message_store.get_pending_messages(),
                [{"type": "operation-result",
                  "operation-id": 123,
                  "status": FAILED,
                  "result-text": u"Scripts cannot be run as user whatever."}])
        result.addCallback(got_result)
        return result


    def test_urgent_response(self):
        """Responses to script execution messages are urgent."""
        uid = os.getuid()
        gid = os.getgid()
        username = pwd.getpwuid(uid)[0]

        # ignore the call to chown!
        mock_chown = self.mocker.replace("os.chown", passthrough=False)
        mock_chown(ARGS)

        def spawn_called(protocol, filename, uid, gid):
            protocol.childDataReceived(1, "hi!\n")
            protocol.processEnded(None)
            self._verify_script(filename, "python", "print 'hi'")

        process_factory = self.mocker.mock()
        process_factory.spawnProcess(ANY, ANY, uid=uid, gid=gid)
        self.mocker.call(spawn_called)

        self.mocker.replay()

        self.manager.add(ScriptExecution(process_factory=process_factory))

        def got_result(r):
            self.assertTrue(self.broker_service.exchanger.is_urgent())
            self.assertMessages(
                self.broker_service.message_store.get_pending_messages(),
                [{"type": "operation-result",
                  "operation-id": 123,
                  "result-text": u"hi!\n",
                  "status": SUCCEEDED}])

        result = self._send_script("python", "print 'hi'")
        result.addCallback(got_result)
        return result


    def test_parse_error_causes_operation_failure(self):
        """
        If there is an error parsing the message, an operation-result will be
        sent (assuming operation-id *is* successfully parsed).
        """
        self.log_helper.ignore_errors(KeyError)
        self.manager.add(ScriptExecution())

        self.manager.dispatch_message(
            {"type": "execute-script", "operation-id": 444})

        self.assertMessages(
            self.broker_service.message_store.get_pending_messages(),
            [{"type": "operation-result",
              "operation-id": 444,
              "result-text": u"KeyError: 'username'",
              "status": FAILED}])

        self.assertTrue("KeyError: 'username'" in self.logfile.getvalue())