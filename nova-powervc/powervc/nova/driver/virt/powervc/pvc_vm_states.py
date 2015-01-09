# Copyright 2013 IBM Corp.

ACTIVE = u'ACTIVE'  # PowerVC VM is running
BUILD = u'BUILD'  # PowerVC VM only exists in DB
ERROR = u'ERROR'
SHUTOFF = u'SHUTOFF'
RESIZE = u'RESIZE'
VERIFY_RESIZE = u'VERIFY_RESIZE'
MIGRATING = u' MIGRATING'


class InstanceInfo(object):

    def __init__(self, state=None, max_mem_kb=0, mem_kb=0, num_cpu=0,
                 cpu_time_ns=0):
        """Create a new Instance Info object

        :param state: the running state, one of the power_state codes
        :param max_mem_kb: (int) the maximum memory in KBytes allowed
        :param mem_kb: (int) the memory in KBytes used by the instance
        :param num_cpu: (int) the number of virtual CPUs for the instance
        :param cpu_time_ns: (int) the CPU time used in nanoseconds
        :param id: a unique ID for the instance
        """
        self.state = state
        self.max_mem_kb = max_mem_kb
        self.mem_kb = mem_kb
        self.num_cpu = num_cpu
        self.cpu_time_ns = cpu_time_ns
