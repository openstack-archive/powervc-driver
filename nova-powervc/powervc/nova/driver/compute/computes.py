# Copyright 2013 IBM Corp.

'''
This module manages the virtual nova compute services managed by the PowerVC
service.
'''
import eventlet
import sys
import traceback

import powervc.common.config as config
import powervc.common.utils as commonutils

from nova.compute import api
from nova import context

from oslo_log import log as logging
from nova.openstack.common import loopingcall
from oslo import messaging

from nova import service
from powervc import utils
from powervc.common.gettextutils import _

CONF = config.CONF


LOG = logging.getLogger(__name__)


class StatefulService(service.Service):
    """
    This class wraps the local compute services and provides added
    state information
    """
    def start(self):
        super(StatefulService, self).start()
        self.started = True

    def stop(self):
        super(StatefulService, self).stop()
        self.started = False


class ComputeServiceManager(object):
    """
    This class is responsible for creating and managing compute-services
    managed by the PowerVC service.
    """

    def __init__(self, driver, scg_list, auto_refresh=True):
        """
        Initializes the compute services manager using the given PowerVC driver

        :param driver: an PowerVC driver used to retrieve the hypervisors that
                       will be used to create the corresponding compute
                       services.
        :param auto_refresh: indicates whether or not to automatically try
                             to refresh the services based on new hypervisors,
                             if auto_refresh is false the `refresh()` method
                             needs to be invoked manually
        """
        self.running = False
        self.driver = driver
        self.services = {}
        self.manager = CONF.compute_manager
        self.auto_refresh = auto_refresh
        self.ctx = context.get_admin_context()
        self.api = api.AggregateAPI()
        self.scg_list = scg_list

    def start(self):
        """
        This method retrieves all services from PowerVC and for each
        service it creates a local nova-compute service.
        """

        try:
            remote_services = self._get_filtered_remote_services()

            for remote_service in remote_services:
                eventlet.greenthread.sleep(0)
                self.new_compute_service(remote_service)

            if self.auto_refresh:
                refresher = loopingcall.FixedIntervalLoopingCall(self.refresh)
                refresher.start(
                    interval=CONF.powervc.hypervisor_refresh_interval)
            LOG.info(_('The PowerVC compute service manager is running.'))

            self.running = True
        except Exception:
            LOG.exception("exception during startup.  Stopping compute"
                          "driver")
            traceback.print_exc()
            sys.exit(1)

    def refresh(self):
        """
        This method refreshes the computes services based on the PowerVC
        services.
        """
        # Exit if the compute services have not been started.
        if not self.running:
            return

        LOG.debug("Refreshing compute services based on remote services ...")

        try:
            remote_services = self._get_filtered_remote_services()
            remote_hostnames = [utils.normalize_host(remote_service.host)
                                for remote_service in remote_services]
            # First we kill the services for services no longer running
            for local_service_name in self.services.keys():
                # calls to greenthread.sleep have been added to all of the
                # loops in this class because it has been long running
                eventlet.greenthread.sleep(0)
                if local_service_name in remote_hostnames:
                    LOG.debug("Service %s still running compute-service "
                              "is left intact." % local_service_name)
                    continue
                LOG.debug("Service %s is no longer running. "
                          "Ending compute-service..." % local_service_name)
                self.destroy_service(local_service_name)

            # Then we add services for new services found and update the
            # state of existing services
            for remote_service in remote_services:
                eventlet.greenthread.sleep(0)
                hostname = utils.normalize_host(remote_service.host)
                if hostname in self.services:
                    self._sync_service_state(remote_service)
                    continue
                LOG.debug("New service %s found. "
                          "Will create a new compute-service..." % hostname)
                self.new_compute_service(remote_service)
        except Exception:
            LOG.warning("exception during periodic sync.  Stopping compute"
                        "services")
            traceback.print_exc()
            self._stop_local_services()

    def new_compute_service(self, remote_service):
        """
        Creates and starts a new compute service for the given hypervisor.
        """
        host = utils.normalize_host(remote_service.host)
        try:
            local_service = StatefulService.\
                create(binary='nova-compute',
                       host=host,
                       topic=CONF.compute_topic,
                       manager=CONF.compute_manager,
                       db_allowed=False)
            local_service.start()
            self.services[host] = local_service
            LOG.info(_('Created nova-compute service for %s') % host)
            self._sync_service_state(remote_service)
        except messaging.MessagingTimeout as e:
            LOG.debug(_('Failed to launch nova-compute service for %s .') %
                      host)
            LOG.debug(_('Most likely the other nova services are not '
                        'running normally. Make sure the nova services '
                        'like nova-network, nova-scheduler, '
                        'nova-conductor all start up and can be reached, '
                        'then restart the PowerVC service.'))
            LOG.debug(_('Error: %s') % e)
            sys.exit(1)
        except (Exception, SystemExit) as e:
            LOG.critical(_('Failed to launch nova-compute service for %s') %
                         host)
            LOG.exception(_('Error: %s') % e)
            sys.exit(1)

    def destroy_service(self, hostname):
        """
        Kills the service for the given hostname, and destroys any
        corresponding aggregates and availability zones if necessary.
        """
        local_service = self.services[hostname]
        local_service.kill()
        self.services.pop(hostname)
        LOG.info(_("Compute service %s was killed.") % hostname)

    def _sync_service_state(self, remote_service):
        """
        Updates the state of the local service which corresponds
        to the remote_service.  This method assumes the local
        service already exists.
        """
        local_service = self.services[remote_service.host]
        if local_service is None:
            LOG.debug("local service not found for %s" % remote_service.host)
            return
        if (remote_service.state == "down" or
            remote_service.hypervisor_state != "operating") \
                and local_service.started:
            LOG.debug("Stopping remote service %s" % local_service.host)
            local_service.stop()
            return
        if (remote_service.state == "up" and
            remote_service.hypervisor_state == "operating") \
                and not local_service.started:
            LOG.debug("Starting remote service %s" % local_service.host)
            local_service.start()

    def _stop_local_services(self):
        """
        Puts all services to a down state.  For use in exception handling
        """
        if not self.services:
            return
        for local_service in self.services.itervalues():
            try:
                local_service.stop()
            except Exception:
                LOG.warning("Exception stopping local service")
                traceback.print_exc()

    def _get_filtered_remote_services(self):
        remote_services = self.driver._service._client.\
            client.services.list(binary="nova-compute")
        multi_scg_hosts_names = set()
        for old_scg in self.scg_list:
            # Try use the latest one?
            scg = (commonutils.get_utils().
                   get_scg_by_scgName(old_scg.display_name))
            scg_host_list = getattr(scg, 'host_list', [])
            for host in scg_host_list:
                if host and host.get('name'):
                    multi_scg_hosts_names.add(host.get('name'))

        if not multi_scg_hosts_names:
            LOG.info("No host listed in scg: '%s'" % str(self.scg_list))
            return remote_services
        host_names = [utils.normalize_host(name)
                      for name in multi_scg_hosts_names]
        filtered_services = []

        for remote_service in remote_services:
            if utils.normalize_host(remote_service.host) in host_names:
                filtered_services.append(remote_service)

        return filtered_services
