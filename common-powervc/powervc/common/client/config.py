COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

from powervc.common import config
from powervc.common import netutils

CONF = config.CONF

# http client opts from config file normalized
# to keystone client form
OS_OPTS = None
PVC_OPTS = None


def _build_base_http_opts(config_section, opt_map):
    configuration = CONF[config_section]
    opt_map['tenant_name'] = configuration['admin_tenant_name']
    opt_map['username'] = configuration['admin_user']
    opt_map['password'] = configuration['admin_password']
    opt_map['cacert'] = configuration['connection_cacert']
    opt_map['insecure'] = configuration['http_insecure']
    if opt_map['insecure'] is False:
        opt_map['auth_url'] = netutils.hostname_url(configuration['auth_url'])
    else:
        opt_map['auth_url'] = configuration['auth_url']
    return opt_map


# init client opts for powervc and openstack only once
if OS_OPTS is None:
    OS_OPTS = _build_base_http_opts('openstack', {})
    #support mulitple region on local openstack
    OS_OPTS['region_name'] = CONF['openstack']['region_name']
if PVC_OPTS is None:
    PVC_OPTS = _build_base_http_opts('powervc', {})
