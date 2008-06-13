from landscape.plugin import PluginConfigError
from landscape.monitor.processorinfo import ProcessorInfo
from landscape.tests.helpers import LandscapeTest, MakePathHelper, MonitorHelper
from landscape.tests.mocker import ANY


# The extra blank line at the bottom of some sample data definitions
# is intentional.

class ProcessorInfoTest(LandscapeTest):
    """Tests for CPU info plugin."""

    helpers = [MonitorHelper]

    def test_unknown_machine_name(self):
        """Ensure a PluginConfigError is raised for unknown machines."""
        self.assertRaises(PluginConfigError,
                          lambda: ProcessorInfo(machine_name="wubble"))

    def test_read_proc_cpuinfo(self):
        """Ensure the plugin can parse /proc/cpuinfo."""
        message = ProcessorInfo().create_message()
        self.assertEquals(message["type"], "processor-info")
        self.assertTrue(message["processors"] > 0)

        for processor in message["processors"]:
            self.assertTrue("processor-id" in processor)
            self.assertTrue("model" in processor)

    def test_call_on_accepted(self):
        plugin = ProcessorInfo()
        self.monitor.add(plugin)

        remote_broker_mock = self.mocker.replace(self.remote)
        remote_broker_mock.send_message(ANY, urgent=True)
        self.mocker.replay()

        self.reactor.fire(("message-type-acceptance-changed", "processor-info"),
                          True)


class ResynchTest(LandscapeTest):

    helpers = [MonitorHelper]

    def test_resynchronize(self):
        """
        The "resynchronize" reactor message should cause the plugin to
        send fresh data.
        """
        self.mstore.set_accepted_types(["processor-info"])
        plugin = ProcessorInfo()
        self.monitor.add(plugin)
        plugin.run()
        self.reactor.fire("resynchronize")
        plugin.run()
        messages = self.mstore.get_pending_messages()
        self.assertEquals(len(messages), 2)



class PowerPCMessageTest(LandscapeTest):
    """Tests for powerpc-specific message builder."""

    helpers = [MonitorHelper, MakePathHelper]

    SMP_PPC_G5 = """
processor       : 0
cpu             : PPC970FX, altivec supported
clock           : 2500.000000MHz
revision        : 3.0 (pvr 003c 0300)

processor       : 1
cpu             : PPC970FX, altivec supported
clock           : 2500.000000MHz
revision        : 3.0 (pvr 003c 0300)

timebase        : 33333333
machine         : PowerMac7,3
motherboard     : PowerMac7,3 MacRISC4 Power Macintosh
detected as     : 336 (PowerMac G5)
pmac flags      : 00000000
L2 cache        : 512K unified
pmac-generation : NewWorld
"""

    UP_PPC_G4 = """
processor       : 0
cpu             : 7447A, altivec supported
clock           : 666.666000MHz
revision        : 0.1 (pvr 8003 0101)
bogomips        : 36.73
timebase        : 18432000
machine         : PowerBook5,4
motherboard     : PowerBook5,4 MacRISC3 Power Macintosh
detected as     : 287 (PowerBook G4 15")
pmac flags      : 0000001b
L2 cache        : 512K unified
pmac-generation : NewWorld
"""

    def setUp(self):
        LandscapeTest.setUp(self)
        self.mstore.set_accepted_types(["processor-info"])

    def test_read_sample_ppc_g5_data(self):
        """Ensure the plugin can parse /proc/cpuinfo from a dual PowerPC G5."""
        filename = self.make_path(self.SMP_PPC_G5)
        plugin = ProcessorInfo(machine_name="ppc64",
                               source_filename=filename)
        message = plugin.create_message()
        self.assertEquals(message["type"], "processor-info")
        self.assertTrue(len(message["processors"]) == 2)

        processor_0 = message["processors"][0]
        self.assertEquals(len(processor_0), 2)
        self.assertEquals(processor_0["processor-id"], 0)
        self.assertEquals(processor_0["model"],
                          "PPC970FX, altivec supported")

        processor_1 = message["processors"][1]
        self.assertEquals(len(processor_1), 2)
        self.assertEquals(processor_1["processor-id"], 1)
        self.assertEquals(processor_1["model"],
                          "PPC970FX, altivec supported")

    def test_ppc_g5_cpu_info_same_as_last_known_cpu_info(self):
        """Test that one message is queued for duplicate G5 CPU info."""
        filename = self.make_path(self.SMP_PPC_G5)
        plugin = ProcessorInfo(delay=0.1, machine_name="ppc64",
                               source_filename=filename)
        self.monitor.add(plugin)
        plugin.run()
        plugin.run()

        messages = self.mstore.get_pending_messages()
        self.assertEquals(len(messages), 1)

        message = messages[0]
        self.assertEquals(message["type"], "processor-info")
        self.assertEquals(len(message["processors"]), 2)

        processor_0 = message["processors"][0]
        self.assertEquals(len(processor_0), 2)
        self.assertEquals(processor_0["model"],
                          "PPC970FX, altivec supported")
        self.assertEquals(processor_0["processor-id"], 0)

        processor_1 = message["processors"][1]
        self.assertEquals(len(processor_1), 2)
        self.assertEquals(processor_1["model"],
                          "PPC970FX, altivec supported")
        self.assertEquals(processor_1["processor-id"], 1)

    def test_read_sample_ppc_g4_data(self):
        """Ensure the plugin can parse /proc/cpuinfo from a G4 PowerBook."""
        filename = self.make_path(self.UP_PPC_G4)
        plugin = ProcessorInfo(machine_name="ppc",
                               source_filename=filename)
        message = plugin.create_message()
        self.assertEquals(message["type"], "processor-info")
        self.assertTrue(len(message["processors"]) == 1)

        processor = message["processors"][0]
        self.assertEquals(len(processor), 2)
        self.assertEquals(processor["processor-id"], 0)
        self.assertEquals(processor["model"], "7447A, altivec supported")


class SparcMessageTest(LandscapeTest):
    """Tests for sparc-specific message builder."""

    helpers = [MonitorHelper, MakePathHelper]

    SMP_SPARC = """
cpu             : TI UltraSparc IIIi (Jalapeno)
fpu             : UltraSparc IIIi integrated FPU
prom            : OBP 4.16.2 2004/10/04 18:22
type            : sun4u
ncpus probed    : 2
ncpus active    : 2
D$ parity tl1   : 0
I$ parity tl1   : 0
Cpu0Bogo        : 24.00
Cpu0ClkTck      : 000000004fa1be00
Cpu1Bogo        : 24.00
Cpu1ClkTck      : 000000004fa1be00
MMU Type        : Cheetah+
State:
CPU0:           online
CPU1:           online
"""

    def test_read_sample_sparc_data(self):
        """Ensure the plugin can parse /proc/cpuinfo from a dual UltraSparc."""
        filename = self.make_path(self.SMP_SPARC)
        plugin = ProcessorInfo(machine_name="sparc64",
                               source_filename=filename)
        message = plugin.create_message()
        self.assertEquals(message["type"], "processor-info")
        self.assertTrue(len(message["processors"]) == 2)

        processor_0 = message["processors"][0]
        self.assertEquals(len(processor_0), 2)
        self.assertEquals(processor_0["model"],
                          "TI UltraSparc IIIi (Jalapeno)")
        self.assertEquals(processor_0["processor-id"], 0)

        processor_1 = message["processors"][1]
        self.assertEquals(len(processor_1), 2)
        self.assertEquals(processor_1["model"],
                          "TI UltraSparc IIIi (Jalapeno)")
        self.assertEquals(processor_1["processor-id"], 1)


class X86MessageTest(LandscapeTest):
    """Test for x86-specific message handling."""

    helpers = [MonitorHelper, MakePathHelper]

    SMP_OPTERON = """
processor       : 0
vendor_id       : AuthenticAMD
cpu family      : 15
model           : 37
model name      : AMD Opteron(tm) Processor 250
stepping        : 1
cpu MHz         : 2405.489
cache size      : 1024 KB
fpu             : yes
fpu_exception   : yes
cpuid level     : 1
wp              : yes
flags           : fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 clflush mmx fxsr sse sse2 syscall nx mmxext fxsr_opt lm 3dnowext 3dnow pni
bogomips        : 4718.59
TLB size        : 1024 4K pages
clflush size    : 64
cache_alignment : 64
address sizes   : 40 bits physical, 48 bits virtual
power management: ts fid vid ttp

processor       : 1
vendor_id       : AuthenticAMD
cpu family      : 15
model           : 37
model name      : AMD Opteron(tm) Processor 250
stepping        : 1
cpu MHz         : 2405.489
cache size      : 1024 KB
fpu             : yes
fpu_exception   : yes
cpuid level     : 1
wp              : yes
flags           : fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 clflush mmx fxsr sse sse2 syscall nx mmxext fxsr_opt lm 3dnowext 3dnow pni
bogomips        : 4800.51
TLB size        : 1024 4K pages
clflush size    : 64
cache_alignment : 64
address sizes   : 40 bits physical, 48 bits virtual
power management: ts fid vid ttp

"""

    UP_PENTIUM_M = """
processor       : 0
vendor_id       : GenuineIntel
cpu family      : 6
model           : 13
model name      : Intel(R) Pentium(R) M processor 1.50GHz
stepping        : 8
cpu MHz         : 598.834
cache size      : 2048 KB
fdiv_bug        : no
hlt_bug         : no
f00f_bug        : no
coma_bug        : no
fpu             : yes
fpu_exception   : yes
cpuid level     : 2
wp              : yes
flags           : fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat clflush dts acpi mmx fxsr sse sse2 ss tm pbe nx est tm2
bogomips        : 1198.25

"""

    def setUp(self):
        LandscapeTest.setUp(self)
        self.mstore.set_accepted_types(["processor-info"])

    def test_read_sample_opteron_data(self):
        """Ensure the plugin can parse /proc/cpuinfo from a dual Opteron."""
        filename = self.make_path(self.SMP_OPTERON)
        plugin = ProcessorInfo(machine_name="x86_64",
                               source_filename=filename)
        message = plugin.create_message()
        self.assertEquals(message["type"], "processor-info")
        self.assertTrue(len(message["processors"]) == 2)

        processor_0 = message["processors"][0]
        self.assertEquals(len(processor_0), 4)
        self.assertEquals(processor_0["vendor"], "AuthenticAMD")
        self.assertEquals(processor_0["model"],
                          "AMD Opteron(tm) Processor 250")
        self.assertEquals(processor_0["cache-size"], 1024)
        self.assertEquals(processor_0["processor-id"], 0)

        processor_1 = message["processors"][1]
        self.assertEquals(len(processor_1), 4)
        self.assertEquals(processor_1["vendor"], "AuthenticAMD")
        self.assertEquals(processor_1["model"],
                          "AMD Opteron(tm) Processor 250")
        self.assertEquals(processor_1["cache-size"], 1024)
        self.assertEquals(processor_1["processor-id"], 1)

    def test_plugin_manager(self):
        """Test plugin manager integration."""
        filename = self.make_path(self.UP_PENTIUM_M)
        plugin = ProcessorInfo(delay=0.1, machine_name="i686",
                               source_filename=filename)
        self.monitor.add(plugin)
        self.reactor.advance(0.5)
        self.monitor.exchange()

        self.assertMessages(
            self.mstore.get_pending_messages(),
            [{"type": "processor-info",
              "processors": [
                        {"vendor": "GenuineIntel",
                         "model": "Intel(R) Pentium(R) M processor 1.50GHz",
                         "cache-size": 2048,
                         "processor-id": 0}],
              }])

    def test_read_sample_pentium_m_data(self):
        """Ensure the plugin can parse /proc/cpuinfo from a Pentium-M."""
        filename = self.make_path(self.UP_PENTIUM_M)
        plugin = ProcessorInfo(machine_name="i686",
                               source_filename=filename)
        message = plugin.create_message()
        self.assertEquals(message["type"], "processor-info")
        self.assertTrue(len(message["processors"]) == 1)

        processor = message["processors"][0]
        self.assertEquals(len(processor), 4)
        self.assertEquals(processor["vendor"], "GenuineIntel")
        self.assertEquals(processor["model"],
                          "Intel(R) Pentium(R) M processor 1.50GHz")
        self.assertEquals(processor["cache-size"], 2048)
        self.assertEquals(processor["processor-id"], 0)

    def test_pentium_m_cpu_info_same_as_last_known_cpu_info(self):
        """Test that one message is queued for duplicate Pentium-M CPU info."""

        filename = self.make_path(self.UP_PENTIUM_M)
        plugin = ProcessorInfo(delay=0.1, machine_name="i686",
                               source_filename=filename)
        self.monitor.add(plugin)
        self.monitor.add(plugin)
        self.reactor.call_later(0.5, self.reactor.stop)
        self.reactor.run()

        messages = self.mstore.get_pending_messages()
        self.assertEquals(len(messages), 1)

        message = messages[0]
        self.assertEquals(message["type"], "processor-info")
        self.assertEquals(len(message["processors"]), 1)

        processor = message["processors"][0]
        self.assertEquals(len(processor), 4)
        self.assertEquals(processor["vendor"], "GenuineIntel")
        self.assertEquals(processor["model"],
                          "Intel(R) Pentium(R) M processor 1.50GHz")
        self.assertEquals(processor["cache-size"], 2048)
        self.assertEquals(processor["processor-id"], 0)

    def test_unchanging_data(self):
        filename = self.make_path(self.UP_PENTIUM_M)
        plugin = ProcessorInfo(delay=0.1, machine_name="i686",
                               source_filename=filename)
        self.monitor.add(plugin)
        plugin.run()
        plugin.run()
        self.assertEquals(len(self.mstore.get_pending_messages()), 1)

    def test_changing_data(self):
        filename = self.make_path(self.UP_PENTIUM_M)
        plugin = ProcessorInfo(delay=0.1, machine_name="i686",
                               source_filename=filename)
        self.monitor.add(plugin)
        plugin.run()
        self.make_path(self.SMP_OPTERON, filename)
        plugin.run()

        self.assertEquals(len(self.mstore.get_pending_messages()), 2)

    def test_no_message_if_not_accepted(self):
        """
        Don't add any messages at all if the broker isn't currently
        accepting their type.
        """
        self.mstore.set_accepted_types([])
        filename = self.make_path(self.UP_PENTIUM_M)
        plugin = ProcessorInfo(delay=0.1, machine_name="i686",
                               source_filename=filename)
        self.monitor.add(plugin)

        self.mstore.set_accepted_types(["processor-info"])
        self.assertMessages(list(self.mstore.get_pending_messages()), [])
