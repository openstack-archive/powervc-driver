# Copyright 2013 IBM Corp.

from novaclient import base
from novaclient import exceptions
from novaclient.openstack.common import gettextutils
from novaclient import utils

_ = gettextutils._


class HostMaintenanceResource(base.Resource):
    def __repr__(self):
        return "<Host maintenance: %s>" % self.hypervisor_hostname


class HostMaintenanceManager(base.Manager):
    resource_class = HostMaintenanceResource

    def update(self, host_name, status, migrate=None, target_host=None):
        """
        Update status, migrate or target host when put a hypervisor
        into maintenance mode.
        """
        if "enable" == status:
            body = {'status': status, 'migrate': migrate,
                    'target_host': target_host}
        else:
            body = {'status': status}
        return self._update("/os-host-maintenance-mode/%s" % host_name,
                            body)

    def get(self, host_name):
        url = "/os-host-maintenance-mode/%s" % host_name
        _resp, body = self.api.client.get(url)
        # set host name for response body to form a object
        if body:
            body["hypervisor_hostname"] = host_name
        source_obj = {}
        source_obj['hypervisor_maintenance'] = body
        source_obj['hypervisor_hostname'] = host_name
        obj = self.resource_class(self, source_obj, loaded=True)
        self._write_object_to_completion_cache(obj)
        return obj


@utils.arg('host',
           metavar='<host>',
           help='Name of a host.')
@utils.arg('--set-status', choices=["enable", "disable"],
           metavar="<enable|disable>",
           help='To enable or disable the host maintenance mode.')
@utils.arg('--migrate', choices=["active-only", "all", "none"],
           metavar="<all|active-only|none>",
           help='Which kinds of instances to migrate.')
@utils.arg('--target-host',
           metavar='<target host>',
           help='Which service host instances would be migrated to.')
def do_host_maintenance(cs, args):
    """Enable maintenance mode for a hypervisor."""
    if not args.set_status:
        if args.migrate or args.target_host:
            raise exceptions.CommandError(_("Need to set --set-status "
                                            "to 'enable' when --migrate "
                                            "or --target-host specified."))
        else:
            return _show_maintenance_status(cs, args.host)

    if "disable" == args.set_status.lower():
        if args.migrate or args.target_host:
            raise exceptions.CommandError(_("No need to specify migrate or "
                                            "target-host when disabling the "
                                            "host maintenance mode."))

    hv = cs.host_maintenance.update(args.host,
                                    args.set_status,
                                    args.migrate,
                                    args.target_host)

    host = HostMaintenanceResource(HostMaintenanceManager,
                                   hv.hypervisor_maintenance)
    utils.print_list([host], ['hypervisor_hostname', 'status',
                              'migrate', 'target-host'])


def _show_maintenance_status(cs, host):
    hv = cs.host_maintenance.get(host)
    host = HostMaintenanceResource(HostMaintenanceManager,
                                   hv.hypervisor_maintenance)

    utils.print_list([host], ['hypervisor_hostname', 'maintenance_status',
                              'maintenance_migration_action'])
