# Copyright 2013 IBM Corp.

import re
from eventlet import greenthread

import powervc.common.config as cfg
from powervc.common.gettextutils import _
from nova.compute import flavors
from nova import exception
from nova import db
from nova.openstack.common import log as logging
from nova.openstack.common import loopingcall
from powervc.nova.driver.compute import constants

LOG = logging.getLogger(__name__)

CONF = cfg.CONF


def periodic_flavor_sync(ctx, driver, scg_id_list):
        """
        Periodically update the flavors from PowerVC.
        A default time of 300 seconds is specified for the refresh interval.
        if the refresh interval is set to 0, then flavors are not refreshed.
        """
        sync_interval = CONF.powervc.flavor_sync_interval

        if sync_interval is None or sync_interval == 0:
            return

        def flavors_sync(driver, scg_id_list):
            FlavorSync(driver, scg_id_list).synchronize_flavors(ctx)
            LOG.debug('Flavors synchronization completed')

        sync_flavors = loopingcall.FixedIntervalLoopingCall(flavors_sync,
                                                            driver,
                                                            scg_id_list)
        sync_flavors.start(interval=sync_interval, initial_delay=sync_interval)


class FlavorSync():
    """A class that synchorizes the flavors.
    The functionality provided here is called by the manager.
    The driver provided interfaces to the PowerVC.
    """

    def __init__(self, driver, scg_id_list):
        self.driver = driver
        self.prefix = CONF.powervc.flavor_prefix
        self.scg_id_list = scg_id_list

    def synchronize_flavors(self, ctx):
        """
        Get a list of all public flavors from PowerVC.
        If it is in configuration white list,
            and not in black list, insert it.
         if it is already in local tables, ignore it.
        """
        LOG.info(_("Flavors synchronization starts."))
        # Get all public flavors. By default, detail and public is set.
        pvcFlavors = self.driver.list_flavors()
        # Sync flavors in list
        for flavor in pvcFlavors:
            LOG.info(_("Flavor:%s") % str(flavor))
            greenthread.sleep(0)
            # This check is added to eliminate sync of private flavors
            # Can be removed once PowerVC fixes to return only public flavors
            # by default.
            if not(flavor.__dict__.get(constants.IS_PUBLIC)):
                continue

            if (self._check_for_sync(flavor.name)):
                response = self._check_for_extraspecs(flavor)
                if response is not None:
                    self._sync_flavor(ctx, flavor, response[1])
        LOG.info(_("Flavors synchronization ends."))

    def _sanitize(self, opts_list):
        """
        Remove any whitespace only list values
        """
        for opt in opts_list:
            if len(opt.strip()) == 0:
                opts_list.remove(opt)
        return opts_list

    def get_flavors_white_list(self):
        """
        Get the flavors to sync from the powervc conf file
        """
        return self._sanitize(CONF.powervc.flavor_white_list)

    def get_flavors_black_list(self):
        """
        Get the black listed flavors from the powervc conf file
        """
        return self._sanitize(CONF.powervc.flavor_black_list)

    def _check_for_sync(self, fl_name):
        """ Check the white/black lists to determine if sync candidate """
        fl_sync = True
        # Get the list of flavors names to sync.
        fl_wlist = self.get_flavors_white_list()
        fl_blist = self.get_flavors_black_list()

        if (len(fl_wlist) != 0):
            fl_sync = self._regex_comp(fl_name, fl_wlist)
        if (fl_sync and (len(fl_blist) != 0)):
            fl_sync = not(self._regex_comp(fl_name, fl_blist))
        return fl_sync

    def _regex_comp(self, name, flist):
        """
        Make a regex comparison for name in the list
        Return a boolean True if found in the list
        """
        if name in flist:
            return True
        for item in flist:
            p = re.compile(item)
            match = p.match(name)
            if (match is not None):
                return True
        return False

    def _sync_flavor(self, ctx, flavor, extra_specs):
        """
        Insert the flavor with extra specs if not in local database
        """
        flavor_in_local_db = None
        flavor_name = self.prefix + flavor.name
        try:
            flavor_in_local_db = db.flavor_get_by_name(ctx, flavor_name)
        except exception.FlavorNotFoundByName:
            self._insert_pvc_flavor_extraspecs(ctx, flavor, extra_specs)

        # Update the extra_speces of the flavor
        if flavor_in_local_db is not None:
            flavor_id = flavor_in_local_db.get('flavorid', '')
            if (flavor_id is not ''
                    and extra_specs):
                self._update_flavor_extraspecs(ctx,
                                               flavor_id,
                                               extra_specs)

    def _check_for_extraspecs(self, flavor):
        """
        Check for valid extraspecs defined and to be synced.
        The method returns the following values:
        (True, None) - flavor to be synced, and no extra specs defined.
        (True, extraspecs) - flavor to be synced with the extra specs defined.
        None - scg connectivity group defined in extraspecs is not supported,
               and flavor not to be synced.

        Checking for scg to be removed when powervc driver supports multiple
        scgs
        """
        flavor_extraspecs = self.driver.get_flavor_extraspecs(flavor)
        if flavor_extraspecs:
            scg_key = constants.SCG_KEY
            if scg_key in flavor_extraspecs:
                if not self.scg_id_list:
                    return None
                if not flavor_extraspecs[scg_key] in self.scg_id_list:
                    return None
        return (True, flavor_extraspecs)

    def _insert_pvc_flavor_extraspecs(self, context, flavor, extra_specs):
        """ Insert the flavor and extra specs if any """
        flavor_created = self._create_flavor(context, flavor)
        if extra_specs:
            self._update_flavor_extraspecs(context,
                                           flavor_created.get('flavorid'),
                                           extra_specs)

    def _update_flavor_extraspecs(self, context, flavorid, flavor_extraspecs):
        """ Insert the flavor extra specs """
        db.flavor_extra_specs_update_or_create(context,
                                               flavorid,
                                               flavor_extraspecs)

    def _create_flavor(self, context, flavor):
        """ Create and insert the flavor """
        flavor_dict = flavor.__dict__
        name = self.prefix + flavor.name
        flavorid = self.prefix + flavor.id
        memory = flavor.ram
        vcpus = flavor.vcpus
        root_gb = flavor.disk
        ephemeral_gb = flavor_dict.get('OS-FLV-EXT-DATA:ephemeral', 0)
        u_swap = flavor_dict.get('swap', 0)
        rxtx_factor = flavor_dict.get('rxtx_factor', 1.0)
        is_public = flavor_dict.get('os-flavor-access:is_public', True)
        if u_swap == "":
            swap = 0
        else:
            swap = int(u_swap)

        try:
            return flavors.create(name, memory, vcpus, root_gb,
                                  ephemeral_gb=ephemeral_gb,
                                  flavorid=flavorid, swap=swap,
                                  rxtx_factor=rxtx_factor,
                                  is_public=is_public)
        except exception.InstanceExists as err:
            raise err
