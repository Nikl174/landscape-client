from optparse import OptionParser
import logging
import os
import signal

from landscape.lib.dbus_util import Object
from landscape.lib.persist import Persist
from landscape import deployment
from landscape.deployment import (
    LandscapeService, Configuration, get_versioned_persist,
    assert_unowned_bus_name)
from landscape.reactor import TwistedReactor, FakeReactor
from landscape.tests.helpers import (
    LandscapeTest, LandscapeIsolatedTest, DBusHelper)
from landscape.tests.mocker import ANY


class ConfigurationTest(LandscapeTest):

    def setUp(self):
        super(ConfigurationTest, self).setUp()
        self.reset_config()

    def reset_config(self):
        class MyConfiguration(Configuration):
            default_config_filenames = []
        self.config_class = MyConfiguration
        self.config = MyConfiguration()
        self.parser = self.config.make_parser()

    def write_config_file(self, **kwargs):
        config = "\n".join(["[client]"] +
                           ["%s = %s" % pair for pair in kwargs.items()])
        self.config_filename = self.makeFile(config)
        self.config.default_config_filenames[:] = [self.config_filename]

    def test_command_line_has_precedence(self):
        self.write_config_file(log_level="file")
        self.config.load(["--log-level", "command line"])
        self.assertEquals(self.config.log_level, "command line")

    def test_command_line_option_without_default(self):
        class MyConfiguration(Configuration):
            def make_parser(self):
                parser = OptionParser()
                # Keep the dash in the option name to ensure it works.
                parser.add_option("--foo-bar")
                return parser
        self.assertEquals(MyConfiguration().foo_bar, None)

    def test_config_file_has_precedence_over_default(self):
        self.write_config_file(log_level="file")
        self.config.load([])
        self.assertEquals(self.config.log_level, "file")

    def test_write_configuration(self):
        self.write_config_file(log_level="debug")
        self.config.log_level = "warning"
        self.config.write()
        data = open(self.config_filename).read()
        self.assertEquals(data.strip(), "[client]\nlog_level = warning")

    def test_write_on_the_right_default_config_file(self):
        self.write_config_file(log_level="debug")
        config_class = self.config_class
        config_class.default_config_filenames.insert(0, "/non/existent")
        self.config.load([])
        self.config.log_level = "warning"
        self.config.write()
        data = open(self.config_filename).read()
        self.assertEquals(data.strip(), "[client]\nlog_level = warning")

    def test_dont_write_default_options(self):
        self.write_config_file(log_level="debug")
        self.config.log_level = "info"
        self.config.write()
        data = open(self.config_filename).read()
        self.assertEquals(data.strip(), "[client]")

    def test_dont_write_config_option(self):
        self.write_config_file()
        self.config.config = self.config_filename
        self.config.write()
        data = open(self.config_filename).read()
        self.assertEquals(data.strip(), "[client]")

    def test_write_command_line_options(self):
        self.write_config_file()
        self.config.load(["--log-level", "warning"])
        self.config.write()
        data = open(self.config_filename).read()
        self.assertEquals(data.strip(), "[client]\nlog_level = warning")

    def test_write_command_line_precedence(self):
        """Command line options take precedence over config file when writing.
        """
        self.write_config_file(log_level="debug")
        self.config.load(["--log-level", "warning"])
        self.config.write()
        data = open(self.config_filename).read()
        self.assertEquals(data.strip(), "[client]\nlog_level = warning")

    def test_write_manually_set_precedence(self):
        """Manually set options take precedence over command line when writing.
        """
        self.write_config_file(log_level="debug")
        self.config.load(["--log-level", "warning"])
        self.config.log_level = "error"
        self.config.write()
        data = open(self.config_filename).read()
        self.assertEquals(data.strip(), "[client]\nlog_level = error")

    def test_write_to_given_config_file(self):
        filename = self.makeFile()
        self.config.load(["--log-level", "warning", "--config", filename],
                         accept_unexistent_config=True)
        self.config.log_level = "error"
        self.config.write()
        data = open(filename).read()
        self.assertEquals(data.strip(), "[client]\nlog_level = error")

    def test_bus_option(self):
        """The bus option must be specified as 'system' or 'session'."""
        self.assertRaises(SystemExit,
                          self.config.load,
                          ["--bus", "foobar"])
        self.config.load(["--bus", "session"])
        self.assertEquals(self.config.bus, "session")
        self.config.load(["--bus", "system"])
        self.assertEquals(self.config.bus, "system")

    def test_config_option(self):
        opts = self.parser.parse_args(["--config", "hello.cfg"])[0]
        self.assertEquals(opts.config, "hello.cfg")

    def test_load_config_from_option(self):
        filename = self.makeFile("[client]\nhello = world\n")
        self.config.load(["--config", filename])
        self.assertEquals(self.config.hello, "world")

    def test_load_typed_option_from_file(self):
        class MyConfiguration(self.config_class):
            def make_parser(self):
                parser = super(MyConfiguration, self).make_parser()
                parser.add_option("--year", default=1, type="int")
                return parser
        filename = self.makeFile("[client]\nyear = 2008\n")
        config = MyConfiguration()
        config.load(["--config", filename])
        self.assertEquals(config.year, 2008)

    def test_load_typed_option_from_command_line(self):
        class MyConfiguration(self.config_class):
            def make_parser(self):
                parser = super(MyConfiguration, self).make_parser()
                parser.add_option("--year", default=1, type="int")
                return parser
        config = MyConfiguration()
        config.load(["--year", "2008"])
        self.assertEquals(config.year, 2008)

    def test_reload(self):
        filename = self.makeFile("[client]\nhello = world1\n")
        self.config.load(["--config", filename])
        open(filename, "w").write("[client]\nhello = world2\n")
        self.config.reload()
        self.assertEquals(self.config.hello, "world2")

    def test_data_directory_option(self):
        opts = self.parser.parse_args(["--data-path", "/opt/hoojy/var/run"])[0]
        self.assertEquals(opts.data_path, "/opt/hoojy/var/run")

    def test_data_directory_default(self):
        opts = self.parser.parse_args([])[0]
        self.assertEquals(opts.data_path, "/var/lib/landscape/client/")

    def test_log_file_option(self):
        opts = self.parser.parse_args(["--log-dir",
                                       "/var/log/my-awesome-log"])[0]
        self.assertEquals(opts.log_dir, "/var/log/my-awesome-log")

    def test_log_level_option(self):
        opts = self.parser.parse_args([])[0]
        self.assertEquals(opts.log_level, "info")
        opts = self.parser.parse_args(["--log-level", "debug"])[0]
        self.assertEquals(opts.log_level, "debug")

    def test_quiet_option(self):
        opts = self.parser.parse_args(["--quiet"])[0]
        self.assertEquals(opts.quiet, True)

    def test_quiet_default(self):
        opts = self.parser.parse_args([])[0]
        self.assertEquals(opts.quiet, False)

    def test_ignore_sigint_option(self):
        opts = self.parser.parse_args(["--ignore-sigint"])[0]
        self.assertEquals(opts.ignore_sigint, True)

    def test_ignore_sigint_default(self):
        opts = self.parser.parse_args([])[0]
        self.assertEquals(opts.ignore_sigint, False)


class GetVersionedPersistTest(LandscapeTest):

    def test_upgrade_service(self):
        class FakeService(object):
            persist_filename = self.make_path(content="")
            service_name = "monitor"

        upgrade_managers = self.mocker.replace(
            "landscape.upgraders.UPGRADE_MANAGERS", passthrough=False)
        upgrade_manager = upgrade_managers["monitor"]
        upgrade_manager.apply(ANY)

        stash = []
        self.mocker.call(stash.append)
        self.mocker.replay()

        persist = get_versioned_persist(FakeService())
        self.assertEquals(stash[0], persist)


class LandscapeServiceTest(LandscapeTest):

    def test_create_persist(self):
        class FakeService(LandscapeService):
            persist_filename = self.make_path(content="")
            service_name = "monitor"
        service = FakeService(None)
        self.assertEquals(service.persist.filename, service.persist_filename)

    def test_no_persist_without_filename(self):
        class FakeService(LandscapeService):
            service_name = "monitor"
        service = FakeService(None)
        self.assertFalse(hasattr(service, "persist"))

    def test_usr1_rotates_logs(self):
        """
        SIGUSR1 should cause logs to be reopened.
        """
        logging.getLogger().addHandler(logging.FileHandler(self.make_path()))
        # Store the initial set of handlers
        original_streams = [handler.stream for handler in
                            logging.getLogger().handlers if
                            isinstance(handler, logging.FileHandler)]

        # Instantiating LandscapeService should register the handler
        LandscapeService(None)
        # We'll call it directly
        handler = signal.getsignal(signal.SIGUSR1)
        self.assertTrue(handler)
        handler(None, None)
        new_streams = [handler.stream for handler in
                       logging.getLogger().handlers if
                       isinstance(handler, logging.FileHandler)]

        for stream in new_streams:
            self.assertTrue(stream not in original_streams)



class AssertUnownedBusNameTest(LandscapeIsolatedTest):

    helpers = [DBusHelper]

    class BoringService(Object):
        bus_name = "com.example.BoringService"
        object_path = "/com/example/BoringService"

    def test_raises_sysexit_when_owned(self):
        service = self.BoringService(self.bus)
        self.assertRaises(SystemExit, assert_unowned_bus_name,
                          self.bus, self.BoringService.bus_name)

    def test_do_nothing_when_unowned(self):
        assert_unowned_bus_name(self.bus, self.BoringService.bus_name)
