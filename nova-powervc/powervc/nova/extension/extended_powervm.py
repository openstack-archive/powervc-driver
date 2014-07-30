# Copyright 2013 IBM Corp.

"""The Extended Server Attributes API extension."""

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil

authorize = extensions.soft_extension_authorizer('compute',
                                                 'extended_powervm')


class ExtendedPowerVMAttributesController(wsgi.Controller):

    def gen_pvc_key(self, key):
        self.LOCAL_PVC_PREFIX = 'powervm:'
        if key is None:
            return key
        if key.startswith(self.LOCAL_PVC_PREFIX):
            return key
        return self.LOCAL_PVC_PREFIX + key

    def _extend_server(self, context, server, instance):
        metadata = instance['metadata']
        pvc_attrs = ['cpus', 'min_cpus', 'max_cpus', 'cpu_utilization',
                     'min_vcpus', 'max_vcpus',
                     'min_memory_mb', 'max_memory_mb',
                     'root_gb']

        key = "%s:id" % (Extended_powervm.alias)
        if 'pvc_id' in metadata:
            server[key] = metadata['pvc_id']

        key = "%s:health_status" % (Extended_powervm.alias)
        health_status = {}
        att = self.gen_pvc_key('health_status.health_value')
        if att in metadata:
            health_status['health_value'] = metadata[att]
            del metadata[att]
        # TODO:Here can add other health_status property to construct
        # dictionary data
        server[key] = health_status

        for item in pvc_attrs:
            key = "%s:%s" % (Extended_powervm.alias, item)
            att = self.gen_pvc_key(item)
            if att in metadata:
                value = metadata[att]
                server[key] = value
                del metadata[att]

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=ExtendedPowervmTemplate())
            server = resp_obj.obj['server']
            db_instance = req.get_db_instance(server['id'])
            # server['id'] is guaranteed to be in the cache due to
            # the core API adding it in its 'show' method.
            self._extend_server(context, server, db_instance)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=ExtendedPowervmsTemplate())

            servers = list(resp_obj.obj['servers'])
            for server in servers:
                db_instance = req.get_db_instance(server['id'])
                # server['id'] is guaranteed to be in the cache due to
                # the core API adding it in its 'detail' method.
                self._extend_server(context, server, db_instance)


class Extended_powervm(extensions.ExtensionDescriptor):
    """Extended Server Attributes support."""
    name = "ExtendedPowervm"
    alias = "IBM-PVM"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "extended_powervm/api/v1.1")
    updated = "2011-11-03T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = ExtendedPowerVMAttributesController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]


def make_server(elem):
    elem.set('{%s}id' % Extended_powervm.namespace,
             '%s:id' % Extended_powervm.alias)

    elem.set('{%s}cpus' % Extended_powervm.namespace,
             '%s:cpus' % Extended_powervm.alias)
    elem.set('{%s}max_cpus' % Extended_powervm.namespace,
             '%s:max_cpus' % Extended_powervm.alias)
    elem.set('{%s}min_cpus' % Extended_powervm.namespace,
             '%s:min_cpus' % Extended_powervm.alias)
    elem.set('{%s}cpu_utilization' % Extended_powervm.namespace,
             '%s:cpu_utilization' % Extended_powervm.alias)

    elem.set('{%s}min_vcpus' % Extended_powervm.namespace,
             '%s:min_vcpus' % Extended_powervm.alias)
    elem.set('{%s}max_vcpus' % Extended_powervm.namespace,
             '%s:max_vcpus' % Extended_powervm.alias)

    elem.set('{%s}min_memory_mb' % Extended_powervm.namespace,
             '%s:min_memory_mb' % Extended_powervm.alias)
    elem.set('{%s}max_memory_mb' % Extended_powervm.namespace,
             '%s:max_memory_mb' % Extended_powervm.alias)

    elem.set('{%s}root_gb' % Extended_powervm.namespace,
             '%s:root_gb' % Extended_powervm.alias)
    elem.set('{%s}health_status' % Extended_powervm.namespace,
             '%s:health_status' % Extended_powervm.alias)


class ExtendedPowervmTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server', selector='server')
        make_server(root)
        alias = Extended_powervm.alias
        namespace = Extended_powervm.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})


class ExtendedPowervmsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('servers')
        elem = xmlutil.SubTemplateElement(root, 'server', selector='servers')
        make_server(elem)
        alias = Extended_powervm.alias
        namespace = Extended_powervm.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})
