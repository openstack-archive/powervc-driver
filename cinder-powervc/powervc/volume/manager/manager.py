# Copyright 2013, 2014 IBM Corp.

# from cinderclient.v1 import client
import cinder.db.sqlalchemy.models
import sys
import time
import logging

from oslo.config import cfg
from cinder import db
from cinder import context
from cinder import service as taskservice
from cinder.openstack.common import service
from cinder.openstack.common import log
from cinder import quota
from powervc.common import config
from powervc.common.gettextutils import _
from powervc.volume.manager import constants
from powervc.volume.driver import service as pvcservice
from powervc.common import utils
from powervc.common.client import delegate as ctx_delegate

from powervc.common import messaging

CONF = config.CONF
LOG = log.getLogger(__name__)
QUOTAS = quota.QUOTAS

volume_sync_opts = [
    cfg.IntOpt('volume_sync_interval',
               default=20,
               help=_('Volume periodic sync interval specified in '
                      'seconds.')),
    cfg.IntOpt('full_volume_sync_frequency',
               default=30,
               help=_('How many volume sync intervals between full volume '
                      'syncs. Only volumes known to be out of sync are '
                      'synced on the interval except after this many '
                      'intervals when all volumes are synced.')),
    cfg.IntOpt('volume_type_sync_interval',
               default=20,
               help=_('Volume type periodic sync interval specified in '
                      'seconds.')),
    cfg.IntOpt('full_volume_type_sync_frequency',
               default=30,
               help=_('How many volume type sync intervals between full volume'
                      ' type syncs. Only volumes known to be out of sync are '
                      'synced on the interval except after this many '
                      'intervals when all volumes are synced.')),
]

CONF.register_opts(volume_sync_opts, group='powervc')


class PowerVCCinderManager(service.Service):

    """
    Manages the synchronization of volume types and volumes
    TODO
    """

    def __init__(self):
        '''
        Constructor
        '''
        super(PowerVCCinderManager, self).__init__()
        self._load_power_config(sys.argv)

        self._service = pvcservice.PowerVCService()

        ctx = self._get_context()

        self._staging_cache = utils.StagingCache()

        if not utils.get_utils().validate_scgs():
            LOG.error(_('Cinder-powervc service terminated, Invalid Storage'
                        ' Connectivity Group specified.'))
            sys.exit(1)

        # Keep track of whether or not we need to sync all volume types on the
        # next volume type sync interval.
        self.full_volume_type_sync_required = False
        self.full_volume_sync_required = False
        self.sync_volume_types = {}
        self.sync_volumes = {}

        # Delete volums first!
        # It will try delete un-referred volume-types
        self._synchronize_volumes(ctx)
        self._synchronize_volume_types(ctx)

        # Uncomment line below to start cinder-volume along with cinder-powervc
#        self.start_volume_service()

        # Listen for out-of-band PowerVC changes
        self._create_powervc_listeners(ctx)

        # Set up periodic polling to sync instances
        self._start_periodic_volume_type_sync(ctx)
        self._start_periodic_volume_sync(ctx)

    def _get_context(self):
        # lazy import factory to avoid connect to env when load manager
        from powervc.common.client import factory
        keystone = factory.LOCAL.keystone
        orig_ctx = context.get_admin_context()
        orig_ctx.project_id = keystone.tenant_id
        orig_ctx.user_id = keystone.user_id

        return ctx_delegate.context_dynamic_auth_token(orig_ctx, keystone)

    def _load_power_config(self, argv):
        """
        Loads the powervc config.
        """
        # Cinder is typically started with the --config-file option.
        # This prevents the default config files from loading since
        # the olso config code will only load those
        # config files as specified on the command line.
        # If the cinder is started with the
        # --config-file option then append our powervc.conf file to
        # the command line so it gets loaded as well.
        for arg in argv:
            if arg == '--config-file' or arg.startswith('--config-file='):
                argv[len(argv):] = ["--config-file"] + \
                    [cfg.find_config_files(project='powervc',
                                           prog='powervc')[0]]
                break

        config.parse_power_config(argv, 'cinder')
        CONF.log_opt_values(LOG, logging.INFO)

    def start_volume_service(self):
        """
        Creates and starts a cinder-volume service
        """
        if CONF.enabled_backends:
            for backend in CONF.enabled_backends:
                host = "%s@%s" % (CONF.host, backend)
                self.volume_service = \
                    taskservice.Service.create(host=host,
                                               service_name=backend)
        else:
            self.volume_service = \
                taskservice.Service.create(binary='cinder-volume')
        self.volume_service.start()

    def _create_powervc_listeners(self, ctx):
        """Listen for out-of-band changes made in PowerVC.

        This method creates the listner to the PowerVC AMQP broker and
        sets up handlers so that any changes made directly in PowerVC are
        reflected in the local OS.

        :param: ctx The security context
        """
        LOG.debug("Enter _create_powervc_listeners method")

        endpoint = messaging.NotificationEndpoint(log=LOG, sec_context=ctx)

        # Volume type creation
        LOG.debug(_("Register event handler for %s event ")
                  % constants.EVENT_VOLUME_TYPE_CREATE)
        endpoint.register_handler(constants.EVENT_VOLUME_TYPE_CREATE,
                                  self._handle_powervc_volume_type_create)

        # Volume type deletion
        LOG.debug(_("Register event handler for %s event ")
                  % constants.EVENT_VOLUME_TYPE_DELETE)
        endpoint.register_handler(constants.EVENT_VOLUME_TYPE_DELETE,
                                  self._handle_powervc_volume_type_delete)

        # Volume type extra spec changes
        LOG.debug(_("Register event handler for %s event ")
                  % constants.EVENT_VOLUME_TYPE_EXTRA_SPECS_UPDATE)
        endpoint.register_handler([
            constants.EVENT_VOLUME_TYPE_EXTRA_SPECS_UPDATE],
            self._handle_powervc_volume_type_extra_spec_update)

        LOG.debug(_("Register event handler for %s event ")
                  % constants.EVENT_VOLUME_CREATE_END)
        endpoint.register_handler([constants.EVENT_VOLUME_CREATE_END],
                                  self._handle_powervc_volume_create)

        LOG.debug(_("Register event handler for %s event ")
                  % constants.EVENT_VOLUME_IMPORT_END)
        endpoint.register_handler([constants.EVENT_VOLUME_IMPORT_END],
                                  self._handle_powervc_volume_create)

        LOG.debug(_("Register event handler for %s event ")
                  % constants.EVENT_VOLUME_DELETE_END)
        endpoint.register_handler([constants.EVENT_VOLUME_DELETE_END],
                                  self._handle_powervc_volume_delete)

        LOG.debug(_("Register event handler for %s event ")
                  % constants.EVENT_VOLUME_UPDATE)
        endpoint.register_handler([constants.EVENT_VOLUME_UPDATE],
                                  self._handle_powervc_volume_update)

        LOG.debug(_("Register event handler for %s event ")
                  % constants.EVENT_VOLUME_ATTACH_END)
        endpoint.register_handler([constants.EVENT_VOLUME_ATTACH_END],
                                  self._handle_powervc_volume_update)

        LOG.debug(_("Register event handler for %s event ")
                  % constants.EVENT_VOLUME_DETACH_END)
        endpoint.register_handler([constants.EVENT_VOLUME_DETACH_END],
                                  self._handle_powervc_volume_update)

        endpoints = [
            endpoint,
        ]

        LOG.debug("Starting to listen...... ")
        messaging.start_listener(config.AMQP_POWERVC_CONF,
                                 constants.AMQP_EXCHANGE,
                                 constants.AMQP_TOPIC,
                                 endpoints)
        LOG.debug("Exit _create_powervc_listeners method")

    def _periodic_volume_type_sync(self, context, vol_type_ids=None):
        """
        Called to synchronize volume type after initial boot. This does almost
        the same thing as the synchronize that happens on boot except this
        function will check that the instance states meet certain requirements
        before adding, removing, or updating them locally.

        :param: context The security context
        :param: instance_ids List of PowerVC volume type IDs to sync
        """
        LOG.info(_("Starting volume type synchronization..."))
        # Some counters to record instances modified
        count_new_vol_types = 0
        count_updated_vol_types = 0
        count_deleted_vol_types = 0

        # If a list of volume type IDs is passed in then this is a targeted
        # sync operation and not a full sync.
        is_full_sync = not vol_type_ids

        # If this is a full sync then reset the marked instances map, otherwise
        # just remove instances we are about to update. Do this up front so
        # that we minimize the likelihood of losing any instances that might
        # get marked during the sync operation.
        if is_full_sync:
            self.sync_vol_types = {}
        else:
            for vol_type_id in vol_type_ids:
                del self.sync_vol_types[vol_type_id]

        # Get both lists from local DB and PowerVC
        pvc_vol_types = {}
        local_vol_types = {}
        if is_full_sync:
            pvc_vol_types = self._service.list_volume_types()
            local_vol_types = self._get_all_local_pvc_volume_types(context)
        else:
            pvc_vol_types = [self._service.get_volume_type(x)
                             for x in vol_type_ids]

        # Sync. from PowerVC to local nova DB, to insert new instances and
        # update existing instances.
        for index, pvc_vol_type in enumerate(pvc_vol_types):
            """
            """
            # If we are syncing a set of given PowerVC volume type IDs then we
            # first check if the PowerVC volume type exists. If it doesn't then
            # we attempt to delete the local corresponding volume type and move
            # on.
            if not is_full_sync and pvc_vol_type is None:
                matched_vol_types = self._get_local_volume_type_by_pvc_id(
                    context, vol_type_ids[index])
                for local_vol_type in matched_vol_types:
                    if self._unregister_volume_types(
                            context, local_vol_type.get('id')):
                        count_deleted_vol_types += 1
                continue

            # Convert PowerVC instance object to dictionary
            pvc_volume_type = pvc_vol_type.__dict__
            matched_vol_types = self._get_local_volume_type_by_pvc_id(
                context, pvc_volume_type.get('id'))

            # If not found locally then try to add the new instance
            if len(matched_vol_types) == 0:
                if self._insert_pvc_volume_type(context, pvc_volume_type):
                    count_new_vol_types += 1
                continue

            if len(matched_vol_types) > 1:
                LOG.warning('More than one local volume type matches one '
                            'PowerVC volume type: %s' %
                            (pvc_volume_type.get('id')))
            local_vol_type = matched_vol_types[0]

            # Local instance exists so try to update it
            if self._sync_existing_volume_type(
                    context, local_vol_type, pvc_volume_type):
                count_updated_vol_types += 1

        # Sync. from local nova DB to PowerVC, to remove invalid instances
        # that are not in PowerVC anymore. This only happens during a full
        # sync of all instances.
        for local_vol_type in local_vol_types:
            if not self._is_valid_pvc_volume_type(context,
                                                  local_vol_types[
                                                      local_vol_type],
                                                  pvc_vol_types):
                if self._unregister_volume_types(
                        context, local_vol_types[local_vol_type].get('id')):
                    count_deleted_vol_types += 1

        LOG.info("""
                    *******************************
                    Volume type sync. is complete.
                    Full sync: %(full_sync)s
                    [ %(insert)s inserted,
                      %(update)s updated,
                      %(delete)s deleted ]
                    *******************************
                 """ %
                 {'full_sync': is_full_sync,
                  'insert': count_new_vol_types,
                  'update': count_updated_vol_types,
                  'delete': count_deleted_vol_types})

    def _start_periodic_volume_type_sync(self, context):
        """
        Initialize the periodic syncing of instances from PowerVC into the
        local OS. The powervc_instance_sync_interval config property determines
        how often the sync will occur, and the
        powervc_full_instance_sync_frequency config property determines the
        number of marked instance sync operations between full instance syncs.

        :param: context The security context
        """
        # Enforce some minimum values for the sync interval properties
        # TODO: Minimum values should at least be documented
        conf_sync = CONF.powervc.volume_type_sync_interval
        conf_full_sync = CONF.powervc.full_volume_type_sync_frequency
        sync_interval = conf_sync if conf_sync > 10 else 10
        full_sync_frequency = conf_full_sync if conf_full_sync > 2 else 2
        self._volume_type_sync_counter = 0

        def sync():
            """Called on the volume type sync intervals"""
            self._volume_type_sync_counter += 1

            try:
                # Check if it's time to do a full sync
                if self.full_volume_type_sync_required or \
                        self._volume_type_sync_counter == full_sync_frequency:
                    self.full_volume_type_sync_required = False
                    self._volume_type_sync_counter = 0
                    LOG.debug('Syncing all volume type on interval')
                    self._periodic_volume_type_sync(context)
                    return

                # If there are no marked instances to sync stop here
                vol_type_ids = self.sync_volume_types.keys()
                if len(vol_type_ids) == 0:
                    return

                LOG.debug('Syncing marked volume types')
                self._periodic_volume_type_sync(context, type_ids=vol_type_ids)
            except Exception as e:
                LOG.exception(_("Error occurred during volume type "
                                "synchronization: %s"), str(e))
                LOG.info(_("Volume type synchronization will occur at the "
                           "next scheduled interval."))

        self.tg.add_timer(sync_interval, sync)

    def _handle_powervc_volume_type_create(self,
                                           context=None,
                                           ctxt=None,
                                           event_type=None,
                                           payload=None):
        """Handle instance create messages sent from PowerVC.

        :param: context The security context
        :param: ctxt message context
        :param: event_type message event type
        :param: payload The AMQP message sent from OpenStack (dictionary)
        """

        vol_type = payload.get('volume_types')
        if(vol_type is None):
            LOG.warning("Null volume type in volume.create notification")
            return

        pvc_vol_type_id = vol_type.get('id')
        if(pvc_vol_type_id is None):
            LOG.warning("Null volume type id in volume.create notification")
            return

        # Check for matching local instance
        matched_vol_types = self.\
            _get_local_volume_type_by_pvc_id(context, pvc_vol_type_id)
        # If the instance already exists locally then ignore
        if len(matched_vol_types) > 0:
            LOG.debug('Volume type already exists locally')
            return

        # Filter out the vol-type in scg that is not specified in powervc.conf
        extra_specs = getattr(vol_type, 'extra_specs', {})
        # condition 1: volume-type has no extra_specs, add
        if not extra_specs:
            LOG.info(_("No extra_specs in storage template, just add"))
            self._insert_pvc_volume_type(context, vol_type)
        else:
            volume_backend_name = (extra_specs.
                                   get('capabilities:volume_backend_name', ''))
            # condition 2: extra_specs has no volume_backend_name, return
            if not volume_backend_name:
                LOG.info(_('No volume_backend_name specified' +
                         ' return'))
                return

            accessible_storage_providers = utils.get_utils().\
                get_multi_scg_accessible_storage_providers(None, None)
            if not accessible_storage_providers:
                LOG.info(_("No accessible_storage_providers, return"))
                return

            # condition 3: extra_specs's volume_backend_name ==
            # accessible_storage_provider's storage_hostname, add
            for storage_provider in accessible_storage_providers:
                storage_hostname = getattr(storage_provider,
                                           'storage_hostname', '')
                if volume_backend_name == storage_hostname:
                    self._insert_pvc_volume_type(context, vol_type)

    def _handle_powervc_volume_type_delete(self,
                                           context=None,
                                           ctxt=None,
                                           event_type=None,
                                           payload=None):
        """Handle instance delete messages sent from PowerVC.

        :param: context The security context
        :param: ctxt message context
        :param: event_type message event type
        :param: payload The AMQP message sent from OpenStack (dictionary)
        """

        vol_type = payload.get('volume_types')
        if(vol_type is None):
            LOG.warning("Null volume type, ignore volume.create notification")
            return

        pvc_vol_type_id = vol_type.get('id')
        if(pvc_vol_type_id is None):
            LOG.warning("Null volume type id, ignore volume.create")
            return

        # Check for matching local instance
        matched_vol_types = self.\
            _get_local_volume_type_by_pvc_id(context, pvc_vol_type_id)
        # If the instance does not exist then ignore
        if len(matched_vol_types) == 0:
            LOG.debug('Volume type does not exist locally')
            return
        # Remove the instance from the local OS
        self._unregister_volume_types(context, pvc_vol_type_id)

    def _handle_powervc_volume_type_extra_spec_update(self,
                                                      context=None,
                                                      ctxt=None,
                                                      event_type=None,
                                                      payload=None):
        """Handle instance state changes sent from PowerVC. This includes
        instance update and all other state changes caused by events like
        power on, power off, resize, live migration, and snapshot.

        :param: context The security context
        :param: ctxt message context
        :param: event_type message event type
        :param: payload The AMQP message sent from OpenStack (dictionary)
        """

        pvc_vol_type_id = payload.get('type_id')
        if(pvc_vol_type_id is None):
            LOG.debug('Null volume type id, ignore extra specs update')
            return

        # Get the matching local instance
        matched_vol_types = self.\
            _get_local_volume_type_by_pvc_id(context, pvc_vol_type_id)

        # If the instance does not exist locally then ignore
        if len(matched_vol_types) == 0:
            LOG.debug('Volume type does not exist locally')
            # defer the insert to periodical check
            return

        # Warn if more than one local instance matches the PowerVC instance
        if len(matched_vol_types) > 1:
            LOG.warning('More than one volume types in DB '
                        'match one PowerVC instance: %s' % (pvc_vol_type_id))
            # TODO: We should do something about this but scheduling a sync
            # won't help since that does nothing to remove duplicate local
            # instances.

        # Get the PowerVC instance so we can compare it to the local instance
        local_vol_type = matched_vol_types[0]
        pvc_volume_type = self._service.get_volume_type(pvc_vol_type_id)

        # Warn if PowerVC instance is not found
        if pvc_volume_type is None:
            LOG.warning('PowerVC volume type could not be found: %s' %
                        (pvc_vol_type_id))
            return

        self._sync_existing_volume_type(context,
                                        local_vol_type,
                                        pvc_volume_type.__dict__)

    def _synchronize_volumes(self, context):
        """
        Synchronize volumes
        """
        local_volumes = self._get_all_local_volumes(context)
        pvc_volumes = self._service.get_volumes()

        self._synchronize_volumes_ex(context, local_volumes, pvc_volumes)

    def _delete_unused_volume_types(self, context,
                                    local_volume_types,
                                    pvc_volume_types):
        """
        Delete volume-types that not in current powervc
        """
        if local_volume_types is None:
            local_volume_types = self._get_all_local_pvc_volume_types(context)
        if pvc_volume_types is None:
            pvc_volume_types = self._service.list_volume_types()

        count_deleted_volume_types = 0
        for local_volume_type in local_volume_types:
            if not self._is_valid_pvc_volume_type(context,
                                                  local_volume_types[
                                                      local_volume_type],
                                                  pvc_volume_types):
                # If it is not valid in pvc, also delete form the local.
                self._unregister_volume_types(context,
                                              local_volume_types[
                                                  local_volume_type].
                                              get('id'))
                count_deleted_volume_types += 1
        return count_deleted_volume_types

    def _synchronize_volume_types(self, context):
        """
        Synchronize volume types
        """
        # Some counters to record instances modified.
        count_new_volume_types = 0
        count_updated_volume_types = 0

        local_volume_types = self._get_all_local_pvc_volume_types(context)
        pvc_volume_types = self._service.list_volume_types()

        # Sync. from local nova DB ---> PowerVC,
        # to remove invalid instances that are not in pvc anymore.
        count_deleted_volume_types = (
            self._delete_unused_volume_types(context,
                                             local_volume_types,
                                             pvc_volume_types))

        # Sync. from PowerVC ---> local nova DB,
        # to insert new instances and update existing instances
        for volume_type in pvc_volume_types:
            # Convert an object to dictionary,
            # because some filed names has spaces.
            pvc_volume_type = volume_type.__dict__
            matched_volume_types = self.\
                _get_matched_volume_type_by_pvc_id(
                    local_volume_types,
                    pvc_volume_type.get('id'))
            if len(matched_volume_types) == 0:
                # Not found
                self._insert_pvc_volume_type(context, pvc_volume_type)
                count_new_volume_types += 1
            else:
                # Found
                if len(matched_volume_types) > 1:
                    LOG.warning("More than one volume type in DB match "
                                "one PowerVC volume type: "
                                + pvc_volume_type.get('id'))
                self._sync_existing_volume_type(context,
                                                matched_volume_types[0],
                                                pvc_volume_type)
                count_updated_volume_types += 1

        LOG.info("""
                    *******************************
                    Initial volume type sync. is complete.
                    [ %(insert)s inserted,
                      %(update)s updated,
                      %(delete)s deleted ]
                    *******************************
                 """ %
                 {'insert': count_new_volume_types,
                  'update': count_updated_volume_types,
                  'delete': count_deleted_volume_types})

    def _get_all_local_pvc_volume_types(self, context):
        """ Get all local volume types that are mapped from PowerVC"""
        all_types = db.volume_type_get_all(context)
        filters = []
        # Filter out non-powervc volume types
        for each in all_types:
            name = all_types[each]['name']
            if(not name.startswith(constants.LOCAL_PVC_VOLUME_TYPE_PREFIX)):
                filters.append(name)

        for name in filters:
            del all_types[name]

        return all_types

    def _get_local_volume_type_by_pvc_id(self, context, pvcid):
        """ Get a local instance by a PowerVC uuid."""
        local_volume_types = self._get_all_local_pvc_volume_types(context)
        return self._get_matched_volume_type_by_pvc_id(
            local_volume_types, pvcid)

    def _get_matched_volume_type_by_pvc_id(self, local_volume_types, pvcid):
        """ Get a local instance by a PowerVC uuid."""
        matches = []
        for item in local_volume_types:
            volume_type_id = local_volume_types[item].get('id')
            if(volume_type_id == pvcid):
                matches.append(local_volume_types[item])
        return matches

    def _mask_pvc_volume_type_name(self,
                                   pvc_volume_type_name,
                                   storage_backend):
        if pvc_volume_type_name is None:
            return pvc_volume_type_name

        if storage_backend is None:
            storage_backend = ''

        return constants.LOCAL_PVC_VOLUME_TYPE_PREFIX + \
            storage_backend + ':' + pvc_volume_type_name

    def _insert_pvc_volume_type(self, context, pvc_volume_type):
        storage_backend = ''
        extra_specs = pvc_volume_type.get('extra_specs')
        if(extra_specs is None):
            extra_specs = {}
        elif ('capabilities:volume_backend_name' in extra_specs):
            storage_backend = \
                extra_specs['capabilities:volume_backend_name']
        # Overwrite the volume backend name
        extra_specs['capabilities:volume_backend_name'] = \
            constants.POWERVC_VOLUME_BACKEND

        volume_type = {
            'id': pvc_volume_type.get('id'),
            'name': self._mask_pvc_volume_type_name(
                pvc_volume_type.get('name'), storage_backend),
            'extra_specs': extra_specs
        }
        ret = None
        try:
            ret = db.volume_type_create(context, volume_type)
        except Exception as e:
            ret = None
            LOG.debug(_("Failed to create volume type %s , Exception: %s")
                      % (volume_type['name'], e))
        return ret

    def _sync_existing_volume_type(self, context,
                                   local_volume_type, pvc_volume_type):
        if local_volume_type is None or pvc_volume_type is None:
            return False
        extra_specs = pvc_volume_type.get('extra_specs')
        if(extra_specs is None):
            extra_specs = {}
        # overwrite the volume backend name
        extra_specs['capabilities:volume_backend_name'] = \
            constants.POWERVC_VOLUME_BACKEND

        try:
            db.volume_type_extra_specs_update_or_create(
                context, local_volume_type.get('id'),
                extra_specs)
        except Exception as e:
            LOG.debug(_("Failed to update volume type %s , Exception: %s")
                      % (local_volume_type.get('id'), e))
            return False

        return True

    def _unregister_volume_types(self, ctx, vol_type_id):
        """
        Unregister the volume type from the local database. This does not use
        the Cinder API which would send an RPC to have the instance deleted.
        The instance has already been removed from PowerVC so we just send our
        own notifications locally and remove it from the database.
        """
        # If the instance does not exist then ignore
        if vol_type_id is None:
            LOG.debug('Volume type does not exist locally')
            return False

        try:
            db.volume_type_destroy(ctx, vol_type_id)
        except Exception as e:
            LOG.debug(_("Failed to delete volume type %s , Exception: %s")
                      % (vol_type_id, e))
            return False

        return True

    def _is_valid_pvc_volume_type(self, context,
                                  local_volume_type, pvc_volume_types):
        found = False
        for volume_type in pvc_volume_types:
            pvc_vol_type = volume_type.__dict__
            if (local_volume_type.get('id') == pvc_vol_type.get('id')):
                found = True
                break
        return found

    def _handle_powervc_volume_create(self,
                                      context=None,
                                      ctxt=None,
                                      event_type=None,
                                      payload=None):
        """Handle volume create messages sent from PowerVC.

        :param: context The security context
        :param: ctxt message context
        :param: event_type message event type
        :param: payload The AMQP message sent from OpenStack (dictionary)
        """

        pvc_volume_id = payload.get('volume_id')
        # wait 15sec to avoid time window that will create duplicated volume
        time.sleep(15)

        # If the volume already exists locally then ignore
        local_volume = self._get_local_volume_by_pvc_id(context, pvc_volume_id)
        if local_volume is not None:
            LOG.debug('Volume already exists locally')
            return

        volume = self._service.get_volume_by_id(pvc_volume_id)
        if volume is not None:
            volume_id = volume.__dict__.get("id")
            scg_accessible_volumes = self._service.get_volumes()
            for accessible_volume in scg_accessible_volumes:
                accessible_volume_id = accessible_volume.__dict__.get("id")
                if(accessible_volume_id == volume_id):
                    self._insert_pvc_volume(context, volume.__dict__)
                    return

        LOG.debug('Volume not accessible, ignored!')
        return

    def _handle_powervc_volume_delete(self,
                                      context=None,
                                      ctxt=None,
                                      event_type=None,
                                      payload=None):
        """Handle volume create messages sent from PowerVC.

        :param: context The security context
        :param: ctxt message context
        :param: event_type message event type
        :param: payload The AMQP message sent from OpenStack (dictionary)
        """
        # wait 15sec to avoid time window that will duplicated delete volume
        time.sleep(15)
        pvc_volume_id = payload.get('volume_id')

        # If the volume does not already exist locally then ignore
        local_volume = self._get_local_volume_by_pvc_id(context, pvc_volume_id)
        if local_volume is None:
            LOG.debug('Volume is non-existent locally, ignore delete handle')
            return

        self._unregister_volumes(context, local_volume)

    def _handle_powervc_volume_update(self,
                                      context=None,
                                      ctxt=None,
                                      event_type=None,
                                      payload=None):
        """Handle volume create messages sent from PowerVC.

        :param: context The security context
        :param: ctxt message context
        :param: event_type message event type
        :param: payload The AMQP message sent from OpenStack (dictionary)
        """

        pvc_volume_id = payload.get('volume_id')

        local_volume = self._get_local_volume_by_pvc_id(context, pvc_volume_id)
        if local_volume is None:
            LOG.debug('Volume is non-existent locally, ignore update handle')
            return

        pvc_volume = self._service.get_volume_by_id(pvc_volume_id)
        if pvc_volume is not None:
            self._sync_existing_volume(context,
                                       local_volume,
                                       pvc_volume.__dict__)
        else:
            LOG.debug('Tried to add newly created volume but it could not '
                      'be found in PowerVC')

    def _get_all_local_volumes(self, context):
        local_pvc_volumes = []
        try:
            db_matches = db.volume_get_all(context,
                                           marker=None,
                                           limit=None,
                                           sort_key='created_at',
                                           sort_dir='desc')
            for local_volume in db_matches:
                if self._get_pvc_id_from_local_volume(local_volume)is not None:
                    local_pvc_volumes.append(local_volume)
        except Exception as e:
            local_pvc_volumes = None
            LOG.debug(_('Failed to get all local volumes, \
                        Exception: %s') % (e))

        return local_pvc_volumes

    def _get_local_volume_by_pvc_id(self, context, pvc_id, is_map=True):
        """ Get a local volume by volume id."""
        ret_volume = None
        if pvc_id is None:
            return ret_volume

        if is_map is False:
            try:
                ret_volume = db.volume_get(context, pvc_id)
            except Exception:
                ret_volume = None
                LOG.debug(_('Volume %s could not be found.') % pvc_id)
        else:
            all_local_volumes = None
            try:
                all_local_volumes = self._get_all_local_volumes(context)
            except:
                all_local_volumes = None

            if all_local_volumes is not None:
                for volume in all_local_volumes:
                    temp = self._get_pvc_id_from_local_volume(volume)
                    if temp == pvc_id:
                        ret_volume = volume
                        break

        return ret_volume

    def _get_local_volume_type_by_id(self,
                                     context,
                                     volume_type_id,
                                     inactive=False):
        """ Get a local volume type by volume id."""
        ret_volume_type = None
        try:
            ret_volume_type = db.api.volume_type_get(context=context,
                                                     id=volume_type_id)
        except Exception as e:
            ret_volume_type = None
            LOG.debug(_("Failed to get local volume type by id [%s]. \
                        Exception: %s") % (volume_type_id, e))

        return ret_volume_type

    def _get_local_volume_type_by_name(self,
                                       context,
                                       volume_type_name,
                                       inactive=False):
        ret_volume_type = None
        if volume_type_name is None:
            return ret_volume_type

        try:
            ret_volume_type = db.api.volume_type_get_by_name(context,
                                                             volume_type_name)
        except Exception as e:
            ret_volume_type = None
            LOG.debug(_("Failed to get local volume type by name [%s]. \
                    Exception: %s") % (volume_type_name, e))

        return ret_volume_type

    def _exist_local_volume_type(self,
                                 context,
                                 volume_type_id,
                                 searchInactive):
        """ Check if exist volume type by volume type id ."""
        if volume_type_id is None:
            return False

        volume_type = self._get_local_volume_type_by_id(context,
                                                        volume_type_id,
                                                        False)
        if volume_type is not None:
            return True

        if searchInactive is True:
            volume_type = self._get_local_volume_type_by_id(context,
                                                            volume_type_id,
                                                            True)
            if volume_type is not None:
                return True

        return False

    def _get_matched_volume_by_pvc_id(self, local_volumes, pvcid):
        """ Get a local instance by a PowerVC uuid."""
        matches = []
        if local_volumes is None or pvcid is None:
            return matches

        for item in local_volumes:
            volume_id = self._get_pvc_id_from_local_volume(item)
            if(volume_id == pvcid):
                matches.append(item)
        return matches

    def _is_valid_pvc_volume(self, context,
                             local_volume, pvc_volumes):
        found = False

        for volume in pvc_volumes:
            pvc_volume = volume.__dict__
            local_volume_id = self._get_pvc_id_from_local_volume(local_volume)
            if (local_volume_id == pvc_volume.get('id')):
                found = True
                break

        return found

    def _sync_existing_volume(self, context, local_volume, pvc_volume):
        ret = False
        if local_volume is None or pvc_volume is None:
            LOG.debug('Local volume or PVC volume is none and ignore it')
            return ret

        if not self._staging_cache.is_valid:
            LOG.warning(_("Staging user or project invalid."
                          " Skipping volume sync."))
            return ret

        values = self._get_values_from_volume(context,
                                              pvc_volume,
                                              local_volume)

        try:
            db.volume_update(context, local_volume.get('id'), values)
            ret = True
        except Exception as e:
            ret = False
            LOG.debug(_("Failed to update volume [%s] existed. Exception: %s")
                      % (local_volume.get('display_name'), e))

        return ret

    def _unregister_volumes(self, context, local_volume):
        """
        Unregister the volume from the local database. This does not use
        the Cinder API which would send an RPC to have the instance deleted.
        The instance has already been removed from PowerVC so we just send our
        own notifications locally and remove it from the database.
        """
        ret = False
        volume_id = local_volume.get('id')
        volume_name = local_volume.get('display_name')
        volume_size = local_volume.get('size')
        if volume_id is None:
            LOG.debug('Volume id is none and ignore it')
            return ret

        try:
            # check first if the volume to be deleted existed.
            volume_to_be_deleted = db.volume_get(context, volume_id)
            if volume_to_be_deleted:
                db.volume_destroy(context, volume_id)
                # update the quotas
                reserve_opts = {'volumes': -1,
                                'gigabytes': -volume_size}
                reservations = QUOTAS.reserve(context,
                                              **reserve_opts)
                LOG.info(_("Start to deduct quota of volume: %s, size: %s") %
                         (volume_name, volume_size))
                QUOTAS.commit(context, reservations)
                ret = True
        except Exception as e:
            ret = False
            LOG.debug(_("Failed to delete local volume %s, Exception: %s")
                      % (volume_id, e))

        return ret

    def _insert_pvc_volume(self, context, volume):
        """ Create one volume"""
        if volume is None:
            LOG.debug("Volume is None, cannot insert it")
            return

        volume_info = volume
        volume_type = volume_info.get('volume_type')
        volume_display_name = volume_info.get('display_name')

        if volume_type is None or volume_type == 'None':
            LOG.debug(_("Volume type is None for volume: %s")
                      % volume_display_name)
        else:
            LOG.debug("Check if exist volume type in local hosting OS, \
                        only including active")
            pvc_volume_type = None
            try:
                pvc_volume_type = self._service \
                                      .get_volume_type_by_name(volume_type)
            except Exception as e:
                LOG.debug(_("Failed to get volume type from "
                            "PowerVC by name [%s]. Exception: %s")
                          % (volume_type, e))

            if pvc_volume_type is not None:
                dict_pvc_volume_type = pvc_volume_type.__dict__

                exist_volume_type = self.\
                    _exist_local_volume_type(context,
                                             dict_pvc_volume_type.get("id"),
                                             False)
                if exist_volume_type is False:
                    LOG.debug(_('''Volume type [%s] is non-existent,
                                insert into hosting OS''') % volume_type)

                    try:
                        self._insert_pvc_volume_type(context,
                                                     dict_pvc_volume_type)
                    except Exception:
                        LOG.debug("Failed to insert volume type")
                    LOG.debug("Insert volume type successfully")
                else:
                    LOG.debug(_("Volume type [%s] existed") % volume_type)

        values = self._get_values_from_volume(context, volume)

        if values is None:
            LOG.warning(_("Staging user or project invalid."
                          " Skipping volume sync."))
            return None
        else:
            try:
                local_volume = db.volume_create(context, values)
                # update the instances that attach this volume
                volume_name = local_volume.get('name')
                volume_size = local_volume.get('size')
                reserve_opts = {'volumes': 1,
                                'gigabytes': volume_size}
                LOG.info(_("Start to reserve quota of volume: %s, size: %s") %
                         (volume_name, volume_size))
                reservations = QUOTAS.reserve(context,
                                              **reserve_opts)
                QUOTAS.commit(context, reservations)
            except Exception as e:
                LOG.debug(_("Failed to create volume %s. Exception: %s")
                          % (str(values), str(e)))
                return None

        LOG.debug(_("Create volume %s successfully") % values)

    def _get_values_from_volume(self, context, volume, local_volume=None):
        if volume is None:
            return None

        project_id = None
        user_id = None

        if local_volume is None:
            user_id, project_id = \
                self._staging_cache.get_staging_user_and_project()
            if user_id is None:
                LOG.warning(_("Staging user or project invalid."))
                return None
        else:
            project_id = local_volume.get('project_id')
            user_id = local_volume.get('user_id')

        metadata = volume.get('metadata')
        if metadata is None:
            metadata = {}

        metadata[constants.LOCAL_PVC_PREFIX + 'os-vol-tenant-attr:tenant_id']\
            = volume.get('os-vol-tenant-attr:tenant_id')

        health_value = None
        health_status = volume.get('health_status')
        if health_status is not None:
            health_value = health_status.get('health_value')
        metadata[constants.LOCAL_PVC_PREFIX + 'health_status.health_value']\
            = health_value

        metadata[constants.LOCAL_PVC_PREFIX + 'os-vol-host-attr:host'] \
            = volume.get('os-vol-host-attr:host')
        metadata[constants.LOCAL_PVC_PREFIX + 'id'] \
            = volume.get('id')

        # Get volume type id
        volume_type_id = None
        volume_type_name = volume.get('volume_type')
        if(volume_type_name is not None and volume_type_name != 'None'):
            storage_backend = volume.get('os-vol-host-attr:host')
            local_volume_type_name = self._mask_pvc_volume_type_name(
                volume_type_name, storage_backend)
            if local_volume_type_name is not None:
                volume_type = self.\
                    _get_local_volume_type_by_name(context,
                                                   local_volume_type_name)
                if volume_type is not None:
                    volume_type_id = volume_type.get('id')

        # Get attachment information
        attachments = volume.get('attachments')
#         attach_time = None
        attach_status = None
        attached_host = None
        mountpoint = None
        instance_uuid = None
        if attachments is not None and len(attachments) > 0:
            attach_status = 'attached'
            attach = attachments[0]
            attached_host = attach.get('host_name')
            mountpoint = attach.get('device')
            # Here instance_uuid also can be assigned metadata['instance_uuid']
            # metadata['instance_uuid'] equal to attach['server_id']
            instance_uuid = attach.get('server_id')

        instance_uuid = self._get_local_instance_id(instance_uuid)

        bootable = 0
        if volume.get('bootable') == 'true':
            bootable = 1

        host = CONF.host
        if CONF.enabled_backends is not None and\
                constants.BACKEND_POWERVCDRIVER in CONF.enabled_backends:
            host = "%s@%s" % (CONF.host, constants.BACKEND_POWERVCDRIVER)
        disp_name = volume.get('display_name') or volume.get('name')
        LOG.debug(_("volume disp_name: %s") % disp_name)
        values = {'display_name': disp_name,
                  'display_description': volume.get('display_description'),
                  #        'volume_type_id': volume_type_id,
                  #                   'id': volume['id'],
                  'status': volume.get('status'),
                  'host': host,
                  'size': volume.get('size'),
                  'availability_zone': volume.get('availability_zone'),
                  'bootable': bootable,
                  'snapshot_id': volume.get('snapshot_id'),
                  'source_volid': volume.get('source_volid'),
                  'metadata': metadata,
                  'project_id': project_id,
                  'user_id': user_id,
                  'attached_host': attached_host,
                  'mountpoint': mountpoint,
                  'instance_uuid': instance_uuid,
                  'attach_status': attach_status
                  }

        if(volume_type_id is not None):
            values['volume_type_id'] = volume_type_id

        return values

    def _start_periodic_volume_sync(self, context):
        """
        Initialize the periodic syncing of instances from PowerVC into the
        local OS. The powervc_instance_sync_interval config property determines
        how often the sync will occur, and the
        powervc_full_instance_sync_frequency config property determines the
        number of marked instance sync operations between full instance syncs.

        :param: context The security context
        """
        # Enforce some minimum values for the sync interval properties
        # TODO: Minimum values should at least be documented
        conf_sync = CONF.powervc.volume_sync_interval
        conf_full_sync = CONF.powervc.full_volume_sync_frequency
        sync_interval = conf_sync if conf_sync > 10 else 10
        full_sync_frequency = conf_full_sync if conf_full_sync > 2 else 2
        self._volume_sync_counter = 0

        def sync():
            """Called on the volume sync intervals"""
            self._volume_sync_counter += 1

            try:
                local_volumes = None
                is_full_sync = True
                # Check if it's time to do a full sync
                if self.full_volume_sync_required or \
                        self._volume_sync_counter == full_sync_frequency:
                    self.full_volume_sync_required = False
                    self._volume_sync_counter = 0
                    local_volumes = self._get_all_local_volumes(context)
                    LOG.debug('Syncing all volume on interval')
                else:
                    # If there are no marked volumes to sync stop here
                    if len(self.sync_volumes) == 0:
                        return
                    is_full_sync = False
                    local_volumes = self.sync_volumes
                    LOG.debug('Syncing marked volumes')

                pvc_volumes = self._service.get_volumes()
                self._synchronize_volumes_ex(context, local_volumes,
                                             pvc_volumes, is_full_sync)
            except Exception as e:
                LOG.exception(_("Error occurred during volume "
                                "sychronization: %s."), e)
                LOG.info(_("Volume synchronization will occur at the next "
                           "scheduled interval."))

        self.tg.add_timer(sync_interval, sync)

    def _synchronize_volumes_ex(self,
                                context,
                                local_volumes,
                                pvc_volumes,
                                is_full_sync=True):
        """
        Synchronize volumes
        """
        LOG.info(_("Volume synchronization started..."))
        if pvc_volumes is None:
            pvc_volumes = []

        if local_volumes is None:
            local_volumes = []

        count_created_volumes = 0
        count_updated_volumes = 0
        count_deleted_volumes = 0

        # Local ---> Powervc
        # First Delete local unused volumes
        for local_volume in local_volumes:
            if not self._is_valid_pvc_volume(context,
                                             local_volume,
                                             pvc_volumes):
                # If it is not valid in pvc, also delete form the local.
                self._unregister_volumes(context, local_volume)
                count_deleted_volumes += 1

        # Try delete unused volume-types
        # parameter None will force to get inf from local and powervc
        deleted_volume_types = (
            self._delete_unused_volume_types(context,
                                             local_volume_types=None,
                                             pvc_volume_types=None))
        LOG.info(' Delete %i unused volume-types when sync volumes'
                 % deleted_volume_types)

        # Powervc ---> Local
        for volume in pvc_volumes:
            pvc_volume = volume.__dict__
            matched_volumes = self._get_matched_volume_by_pvc_id(
                local_volumes,
                pvc_volume.get('id'))
            if len(matched_volumes) == 0:
                self._insert_pvc_volume(context, pvc_volume)
                count_created_volumes += 1
            else:
                if len(matched_volumes) > 1:
                    LOG.warning("More than one volume in DB match "
                                "one PowerVC volume: " + pvc_volume.get('id'))
                    # TODO: We should do something about this but scheduling
                    # a sync won't help since that does nothing to remove
                    # duplicate local volumes.
                self._sync_existing_volume(context,
                                           matched_volumes[0],
                                           pvc_volume)
                count_updated_volumes += 1

        LOG.info("""
                    *******************************
                    Volume sync. is complete.
                    Full sync: %(full_sync)s
                    [ %(insert)s inserted,
                      %(update)s updated,
                      %(delete)s deleted ]
                    *******************************
                 """ %
                 {'full_sync': is_full_sync,
                  'insert': count_created_volumes,
                  'update': count_updated_volumes,
                  'delete': count_deleted_volumes})

    def _get_local_instance_id(self, pvc_instance_id, is_map=True):
        ret_instance_id = pvc_instance_id
        if is_map is False:
            return ret_instance_id

        if pvc_instance_id is None:
            return ret_instance_id

        from powervc.common.constants import SERVICE_TYPES
        # lazy import factory to avoid connect to env when load manager
        from powervc.common.client import factory
        novaclient = factory.LOCAL.get_client(str(SERVICE_TYPES.compute))
        local_instances = novaclient.manager.list_all_servers()
        for inst in local_instances:
            metadata = inst._info['metadata']
            meta_pvc_id = None
            if 'pvc_id' in metadata:
                meta_pvc_id = metadata['pvc_id']

            if meta_pvc_id == pvc_instance_id:
                ret_instance_id = inst._info['id']
                break

        return ret_instance_id

    def _get_pvc_id_from_local_volume(self, local_volume, is_map=True):
        ret_pvc_id = None

        if local_volume is None:
            return ret_pvc_id

        if is_map is False:
            ret_pvc_id = local_volume.get('id')
        else:
            id_key = constants.LOCAL_PVC_PREFIX + 'id'
            if isinstance(local_volume, cinder.db.sqlalchemy.models.Volume):
                metadata = local_volume.get('volume_metadata')
                for item in metadata:
                    if id_key == item['key']:
                        ret_pvc_id = item['value']
                        break
            elif isinstance(local_volume, dict):
                metadata = local_volume.get('metadata')
                if metadata is not None and id_key in metadata:
                    ret_pvc_id = metadata[id_key]

        return ret_pvc_id
