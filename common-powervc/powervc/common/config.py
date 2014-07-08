# Copyright 2013 IBM Corp.

"""Config file utility

"""
import constants

from oslo.config import cfg
CONF = cfg.CONF


def parse_power_config(argv, base_project, base_prog=None):
    """
    Loads configuration information from powervc.conf as well as a project
    specific file.  Expectation is that all powervc config options will be in
    the common powervc.conf file and the base_project will represent open stack
    component configuration like nova.conf or cinder.conf. A base_prog file
    name can be optionally specified as well. That is a specific file name to
    use from the specified open stack component. This function should only be
    called once, in the startup path of a component (probably as soon as
    possible since many modules will have a dependency on the config options).
    """
    # Ensure that we only try to load the config once. Loading it a second
    # time will result in errors.
    if hasattr(parse_power_config, 'power_config_loaded'):
        return

    if base_project and base_project.startswith('powervc-'):
        default_files = cfg.find_config_files(project='powervc',
                                              prog=base_project)
    else:
        default_files = cfg.find_config_files(project=base_project,
                                              prog=(base_project
                                                    if base_prog is None
                                                    else base_prog))
        default_files.extend(cfg.find_config_files(project='powervc',
                                                   prog='powervc'))
    # reduce duplicates
    default_files = list(set(default_files))
    CONF(argv[1:], default_config_files=default_files)
    parse_power_config.power_config_loaded = True

FILE_OPTIONS = {
    '': [],
    'openstack': [
        # Keystone info
        cfg.StrOpt('auth_url', default='http://localhost:5000/v2.0/'),
        cfg.StrOpt('admin_user'),
        cfg.StrOpt('admin_password', secret=True),
        cfg.StrOpt('admin_tenant_name'),
        cfg.StrOpt('connection_cacert', default=None),
        cfg.BoolOpt('http_insecure', default=False),
        cfg.StrOpt('keystone_version', default="v3"),
        cfg.StrOpt('region_name', default=None),
        cfg.IntOpt('keystone_max_try_times', default=30),
        cfg.IntOpt('keystone_retry_interval', default=2),
        # Hosting OS Qpid connection info
        cfg.StrOpt('qpid_hostname'),
        cfg.IntOpt('qpid_port', default=5672),
        cfg.StrOpt('qpid_username', default='anonymous'),
        cfg.StrOpt('qpid_password', secret=True, default=''),
        cfg.StrOpt('qpid_protocol', default='tcp')],
    'powervc': [
        # Keystone info
        cfg.StrOpt('auth_url', default='http://localhost:5000/v2.0/'),
        cfg.StrOpt('admin_user'),
        cfg.StrOpt('admin_password', secret=True),
        cfg.StrOpt('admin_tenant_name'),
        cfg.StrOpt('connection_cacert', default=None),
        cfg.StrOpt('powervc_default_image_name',
                   default='PowerVC Default Image'),
        cfg.BoolOpt('http_insecure', default=False),
        cfg.StrOpt('keystone_version', default="v3"),
        cfg.IntOpt('expiration_stale_duration', default=3600),
        # Hosting OS Qpid connection info
        cfg.StrOpt('qpid_hostname'),
        cfg.IntOpt('qpid_port', default=5672),
        cfg.StrOpt('qpid_username', default='anonymous'),
        cfg.StrOpt('qpid_password', secret=True, default=''),
        cfg.StrOpt('qpid_protocol', default='tcp'),
        # manager
        cfg.StrOpt('powervc_manager',
                   default='powervc.compute.manager.PowerVCCloudManager'),
        # driver
        cfg.StrOpt('powervc_driver',
                   default='powervc.virt.powervc.driver.PowerVCDriver'),
        cfg.MultiStrOpt('storage_connectivity_group'),
        # Hosting OS staging project name. This project must exist in the
        # hosting OS
        cfg.StrOpt('staging_project_name',
                   default=constants.DEFAULT_STAGING_PROJECT_NAME),
        cfg.StrOpt('staging_user',
                   default=constants.DEFAULT_STAGING_USER_NAME)]
}

for section in FILE_OPTIONS:
    for option in FILE_OPTIONS[section]:
        if section:
            CONF.register_opt(option, group=section)
        else:
            CONF.register_opt(option)
