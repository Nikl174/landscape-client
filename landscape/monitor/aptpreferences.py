import os

from landscape.monitor.monitor import DataWatcher


class AptPreferences(DataWatcher):
    """
    Report the system APT preferences configuration.
    """

    persist_name = "apt-preferences"
    message_type = "apt-preferences"
    message_key = "data"
    run_interval = 3600 # 1 hour

    def __init__(self, etc_apt_directory="/etc/apt"):
        self._etc_apt_directory = etc_apt_directory

    def get_data(self):
        """Return a C{dict} mapping APT preferences files to their contents.

        If no APT preferences configuration is set at all on the system, then
        simply return C{None}
        """
        data = {}

        def read_file(filename):
            fd = open(filename, "r")
            content = fd.read()
            fd.close()
            return unicode(content)

        preferences_filename = os.path.join(self._etc_apt_directory,
                                            u"preferences")
        if os.path.exists(preferences_filename):
            data[preferences_filename] = read_file(preferences_filename)

        preferences_directory = os.path.join(self._etc_apt_directory,
                                            u"preferences.d")
        if os.path.isdir(preferences_directory):
            for entry in os.listdir(preferences_directory):
                filename = os.path.join(preferences_directory, entry)
                if os.path.isfile(filename):
                    data[filename] = read_file(filename)

        if data == {}:
            return None
        return data

    def run(self):
        return self.exchange(urgent=True)
