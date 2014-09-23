# Copyright 2014 IBM Corp.

from webob import exc
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova.openstack.common.gettextutils import _
from powervc.common import constants as common_constants
from powervc.common import config

config.parse_power_config([], 'nova')

authorize = extensions.extension_authorizer('compute', 'host-maintenance-mode')


class Controller(wsgi.Controller):
    """Controller class to show host maintenance mode and set host maintenance
    mode with evacuation operation
    """
    def __init__(self, *args, **kwargs):
        super(Controller, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()
        self.host_api = compute.HostAPI()
        from powervc.common.client import factory
        self.pvcclient = factory.POWERVC.new_client(
                str(common_constants.SERVICE_TYPES.compute))

    @wsgi.extends
    def show(self, req, id):
        """Describe host-maintenance-mode by hostname."""
        context = req.environ["nova.context"]
        authorize(context)
        host_name = id
        # Get maintenance mode from powervc client
        maintenance_status = self.pvcclient.hypervisors.\
            get_host_maintenance_mode(host_name)

        return maintenance_status

    @wsgi.extends
    def update(self, req, id, body):
        """Update host-maintenance-mode by hostname."""
        context = req.environ["nova.context"]
        authorize(context)

        host_name = id
        maintenance_status_candidate = ["enable", "disable"]
        maintenance_status = body.get("status")
        if not maintenance_status or \
            maintenance_status.lower() not in maintenance_status_candidate:
            raise exc.HTTPBadRequest(_("Malformed request body, status wrong "
                                       "in request body, should be 'enable'"
                                       " or 'disable'"))

        migrate_candidate = ["none", "active-only", "all"]        
        migrate = body.get("migrate", "none")
        if migrate.lower() not in migrate_candidate:
            raise exc.HTTPBadRequest(_("Malformed request body, migrate wrong "
                                       "in request body, should be 'none',"
                                       "active-only, all or empty"))
        # Set maintenance mode from powervc client
        maintenance_update_status = self.pvcclient.hypervisors.\
            update_host_maintenance_mode(host_name, maintenance_status, migrate)
        return maintenance_update_status


class Host_maintenance_mode(extensions.ExtensionDescriptor):
    """Get and enable/disable Host maintenance mode, and evacuate all
    servers for the maintenance mode entered host. 
    """

    name = "Host-maintenance-mode"
    alias = "os-host-maintenance-mode"
    namespace = "http://docs.openstack.org/compute/ext/host_maintenance_mode/"\
                "api/v2"
    updated = "2014-09-15T00:00:00Z"

    def get_resources(self):
        controller = Controller()
        res = extensions.ResourceExtension(Host_maintenance_mode.alias,
                                           controller)
        return [res]
