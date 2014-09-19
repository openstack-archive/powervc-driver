# Copyright 2013 IBM Corp.

"""
PowerVC Driver ImageManager service
"""

import sys
import time
import hashlib
import Queue
import threading
import itertools
from operator import itemgetter

from powervc.common import config

from nova.openstack.common import service
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova.openstack.common import jsonutils
from glanceclient.v1 import images as v1images
from glanceclient.exc import CommunicationError
from glanceclient.exc import HTTPNotFound

from powervc.common import constants as consts
from powervc.common.exception import StorageConnectivityGroupNotFound
from powervc.common.gettextutils import _
from powervc.common.client import factory as clients
from powervc.glance.common import constants
from powervc.glance.common import config as glance_config
from powervc.common import utils

from powervc.common import messaging

from oslo.messaging.notify import listener
from oslo.messaging import target
from oslo.messaging import transport

CONF = glance_config.CONF

LOG = logging.getLogger(__name__)


class PowerVCImageManager(service.Service):
    """
    The PowerVCImageManager is responsible for initiating the task that
    synchronizes the images between PowerVC and the hosting OS, both at startup
    and periodically. It also starts the image notification event handlers
    which listen for image events from both PowerVC Glance, and the hosting OS
    Glance, and keeps changes synchronized between the two.
    """

    def __init__(self):
        super(PowerVCImageManager, self).__init__()

        # Our Storage Connectivity Group
        self.our_scg_list = []

        # See if out scg is specified. If not, terminate the ImageManager
        # service.
        self._check_scg_at_startup()

        self._staging_cache = utils.StagingCache()

        # The local, and PowerVC updated_at timestamp dicts, and the master
        # image dict are very important. They are used to drive the periodic
        # syncs. They should be kept up to date, but ONLY at the proper time.
        # The updated_at and master_image values should only be set upon
        # the successful completion of image creates, updates, or deletes. Both
        # the PowerVC and local hostingOS changes should complete successfully
        # before setting these values. Failure to do so will result in images
        # out of sync. The keys for all of these dicts are PowerVC image UUIDs
        self.local_updated_at = {}
        self.pvc_updated_at = {}
        self.master_image = {}

        # Flags set when the event handlers are up and running
        self.local_event_handler_running = False
        self.pvc_event_handler_running = False

        # The cached local and PowerVC v1 and v2 glance clients
        self.local_v1client = None
        self.local_v2client = None
        self.pvc_v1client = None
        self.pvc_v2client = None

        # Dicts of events to ignore. These are used to keep events from
        # ping-ponging back and forth between the local hostingOS and PowerVC.
        # The dict is made up of timestamp keys, and event tuple values. The
        # timestamp key is the time that the event tuple is added to the dict.
        # Some events may be missed so these dicts must be purged of expired
        # event tuples periodically.
        self.local_events_to_ignore_dict = {}
        self.pvc_events_to_ignore_dict = {}

        # Summary display counters displayed after syncing
        self._clear_sync_summary_counters()

        # The queue used to synchronize events, and the startup and periodic
        # sync scans
        self.event_queue = Queue.Queue()

        # A dict used to map the PowerVC image UUIDs to local hostingOS image
        # UUIDs
        self.ids_dict = {}

        # The ImageSyncController is used to manage when sync operations occur
        self.image_sync_controller = ImageSyncController(self)

    def start(self):
        """
        Start the PowerVC Driver ImageManager service.

        This will startup image synchronization between PowerVC and the hosting
        OS. The image synchronization will be a period task that will run after
        a given interval.
        """
        self._start_image_sync_task()

    def _start_image_sync_task(self):
        """
        Kick off the image sync task.

        The image sync task will run every 300 seconds (default) and keep the
        hosting OS images in sync with the PowerVC images.
        """
        LOG.debug(_(
            'Starting image sync periodic task with %s second intervals...'),
            CONF['powervc'].image_periodic_sync_interval_in_seconds)

        # Start image synchronization. This will also start the periodic sync.
        self.image_sync_controller.start()

        # Start a thread here to process the event queue
        t = threading.Thread(target=self._process_event_queue)
        t.daemon = True
        t.start()

    def sync_images(self):
        """
        Synchronize the images between PowerVC and the hosting OS. This
        method is typically run as a periodic task so that synchronization
        is done continuously at some specified interval.

        This method initially provides startup synchronization. PowerVC is the
        master. When the synchronization task is done, the PowerVC images
        will be reflected into the hosting OS Glance.

        When the synchronization is complete the image notification
        event handlers will be started if they are not already running.

        After the startup synchronizations runs successfully, subsequent
        synchronizations are done using periodic 2-way synchronization.
        """

        if not self.image_sync_controller.is_startup_sync_done():

            # Add an event to the event queue to start the startup scan.
            self._add_startup_sync_to_queue()
        else:

            # Add an event to the event queue to start the periodic scan.
            # This synchronizes the periodic scans with the image event
            # processing.
            self._add_periodic_sync_to_queue()

    def startup_sync(self):
        """
        Perform the startup sync of images. PowerVC is the master. All active
        images from PowerVC are reflected into the local hosting OS.
        """
        LOG.info(_('Performing startup image synchronization...'))

        # Initialize the sync result value
        sync_result = constants.SYNC_FAILED

        # Save start time for elapsed time calculation
        start_time = time.time()

        # Build a dict of PowerVC images with the UUID as the key.
        # NOTE: If holding all images in memory becomes a problem one
        # option may be to rewrite the code to only get a full image
        # when needed.
        pvc_image_dict = {}

        # Build a dict of hosting OS images that came from PowerVC with the
        # PowerVC UUID as the key. Images from PowerVC will have the property
        # 'powervc_uuid'. If that is not present, ignore
        # NOTE: If holding all images in memory becomes a problem one
        # option may be to rewrite the code to only get a full image
        # when needed.
        local_image_dict = {}

        # Clear the updated_at timestamp dicts, master_image dict and the
        # ids dict in case startup sync is called more than once. These are
        # never cleared again.
        self.local_updated_at.clear()
        self.pvc_updated_at.clear()
        self.master_image.clear()
        self.ids_dict.clear()

        # Initialize stats for summary display
        self._clear_sync_summary_counters()

        # Try catching all exceptions so we don't end our periodic task.
        # If an error occurs during synchronization it is logged
        try:

            # Get the images dict for the hosting OS
            # NOTE: We using the Glance v1 API here. The Glance v2 API will
            # actually list partial/incomplete images. We may want to see which
            # version nova uses when getting images so we don't disagree. If
            # nova use the v2 glance client it may list images which are not
            # complete unless it filters those out. May need more investigation
            # here regarding that.
            local_v1client = self._get_local_v1_client()
            v1local_images = local_v1client.images
            local_image_dict = self._get_local_images_and_ids(v1local_images)

            # Get the images dict from PowerVC. Only get images that are
            # accessible from our Storage Connectivity Group. If the SCG is
            # not found, an exception is raised and the sync will fail here.
            pvc_v1client = self._get_pvc_v1_client()
            v1pvc_images = pvc_v1client.images
            pvc_image_dict = self._get_pvc_images(v1pvc_images)

            # Dump the local image information
            self._dump_image_info(local_image_dict, pvc_image_dict)

            # If there are hostingOS images, check for deletes and updates
            pvc_v2client = self._get_pvc_v2_client()
            local_v2client = self._get_local_v2_client()
            v2local_images = local_v2client.images

            # When catching exceptions during sync operations we will look for
            # CommunicationError, and raise those so we don't waste time
            # trying to process all images when there is a connection failure.
            # Other exceptions should be caught and logged during each
            # operation so we can attempt to process each image before leaving.
            for uuid in local_image_dict.keys():
                local_image = local_image_dict[uuid]
                name = local_image.name
                if uuid not in pvc_image_dict.keys():

                    # It may be possible to have an orphaned snapshot image
                    # in the hostingOS if the PowerVC Driver services
                    # were restarted shortly after an instance capture was
                    # issued. That may appear as a PowerVC image in the
                    # hostingOS which does not yet appear in PowerVC. If
                    # this startup sync is run during that time we will
                    # delete the orphaned snapshot image. If PowerVC ends
                    # up finishing the capture we would then add the
                    # snapshot image a we normally would, and it would have
                    # it's owner value set to the staging project or user id.
                    # If this is a problem in the future consider not deleting
                    # images in the hostingOS which have their powervc_uuid
                    # property set and which have a queued status if they do
                    # not yet exist in PowerVC. This would leave the orphaned
                    # snapshot images in place. If they are not then created
                    # in PowerVC they will continue to be orphaned in the
                    # hostingOS until someone manually deletes them. For now,
                    # we will delete them here.

                    # Remove the image since its not on PowerVC now
                    # Delete the image. Log exceptions here and keep going
                    LOG.info(_('Deleting hosting OS image \'%s\' for PowerVC '
                               'UUID %s'), name, uuid)
                    deleted_image = self._delete_local_image(uuid, local_image,
                                                             v1local_images)
                    if deleted_image is None:
                        LOG.error(_('Local hosting OS image \'%s\' for PowerVC'
                                    ' UUID %s was not deleted during startup '
                                    'image synchronization.'), name, uuid)
                    else:
                        self.local_deleted_count += 1

                        # Clean up the ids_dict
                        if uuid in self.ids_dict.keys():
                            self.ids_dict.pop(uuid)
                else:
                    # Add an extra property named image_topology , which allows
                    # user to select a SCG/Storage Template when booting an VM
                    pvc_image = pvc_image_dict[uuid]
                    if pvc_image:
                        image_topology_prop = \
                            self._format_special_image_extra_property(uuid)
                        image_properties = \
                            self._get_image_properties(pvc_image.to_dict())
                        image_properties[u'image_topology'] = \
                            unicode(image_topology_prop)
                        if 'image_topology' not in \
                            local_image.properties.keys() or \
                                local_image.properties['image_topology'] != \
                                image_properties[u'image_topology']:
                            pvc_image.properties = image_properties
                            pvc_image._info['properties'] = image_properties

                    # Update the image if it has changed. (Right now, always
                    # update it, and update all fields). Update using the
                    # Glance v1 API if possible. Then update other properties
                    # using the Glance v2 PATCH API  Log exceptions here and
                    # keep going
                    LOG.info(_('Updating hosting OS image \'%s\' for PowerVC '
                               'UUID %s'), name, uuid)
                    updated_image = self._update_local_image(
                        uuid, pvc_image_dict[uuid], local_image,
                        v1local_images, v2local_images)

                    # Save updated_at timestamp for the local hostingOS image
                    # to be used during subsequent periodic sync operations
                    if updated_image is None:
                        LOG.error(_('Local hosting OS image \'%s\' for PowerVC'
                                    ' UUID %s was not updated during startup '
                                    'image synchronization.'), name, uuid)
                        self.local_updated_at[uuid] = local_image.updated_at
                    else:
                        self.local_updated_count += 1

                        # Save updated_at timestamp for local hostingOS image
                        # to be used during subsequent periodic sync operations
                        self.local_updated_at[uuid] = updated_image.updated_at

                    # Save updated_at timestamp for PowerVC image to be used
                    # during subsequent periodic sync operations. Also save the
                    # PowerVC image as the master_image used for merging
                    # changes during periodic scan image updates.
                    self.pvc_updated_at[uuid] = pvc_image_dict[uuid].updated_at
                    self.master_image[uuid] = pvc_image_dict[uuid]

            # Add any new active PowerVC images to the hostingOS.
            local_image_owner = self._get_local_staging_owner_id()
            if local_image_owner is None:
                LOG.warning(_("Invalid staging user or project."
                              " Skipping new image sync."))
            else:
                for uuid in pvc_image_dict.keys():
                    if uuid not in local_image_dict.keys():
                        pvc_image = pvc_image_dict[uuid]
                        status = pvc_image.status
                        pvc_name = pvc_image.name

                        # Only sync images from PowerVC that are 'active', and
                        # that are accessible from our Storage Connectivity
                        # Group
                        if status and status == 'active':
                            # Add an extra property named image_topology ,
                            # which allows user to select a SCG/Storage
                            # Template when booting an VM
                            image_topology_prop = \
                                self._format_special_image_extra_property(uuid)
                            image_properties = \
                                self._get_image_properties(pvc_image.to_dict())
                            image_properties[u'image_topology'] = \
                                unicode(image_topology_prop)
                            pvc_image.properties = image_properties
                            pvc_image._info['properties'] = image_properties

                            # Add or activate the local image
                            self._add_or_activate_local_image(
                                pvc_image, local_image_owner,
                                pvc_v2client.http_client.endpoint,
                                v1local_images, v2local_images)
                        else:
                            LOG.debug(_('Image \'%s\' with PowerVC UUID %s not'
                                        ' created during startup image '
                                        'synchronization because the image '
                                        'status is %s'), pvc_name, uuid,
                                      status)

            # All done! Set the startup sync result as passed so subsequent
            # syncs will run the periodic sync
            sync_result = constants.SYNC_PASSED

            # Start the image notification event handlers to process changes if
            # they are not currently running
            self._prepare_for_image_events()

            # Format results for summary display
            stat_l = '{0:d}/{1:d}/{2:d}'.format(self.local_created_count,
                                                self.local_updated_count,
                                                self.local_deleted_count)
            stat_p = '{0:d}/{1:d}/{2:d}'.format(self.pvc_created_count,
                                                self.pvc_updated_count,
                                                self.pvc_deleted_count)
            stats = '(local:{0}, powervc:{1})'.format(stat_l, stat_p)

            # Calculate elapsed time
            end_time = time.time()
            elapsed_time = '{0:.4} seconds'.format(end_time - start_time)
            LOG.info(_('Startup image synchronization is complete. Elapsed '
                       'time: %s %s'), elapsed_time, stats)
        except Exception as e:
            LOG.warning(_('An error occurred during startup image '
                          'synchronization: %s'), e)
            LOG.info(_('Startup image synchronization did not complete '
                       'successfully. It will run again in %s seconds.'),
                     CONF['powervc'].image_sync_retry_interval_time_in_seconds)
        finally:

            # Tell the ImageSyncController that startup sync has ended
            self.image_sync_controller.set_startup_sync_result(sync_result)

    def periodic_sync(self):
        """
        Do a periodic two way sync. First the event handlers need to be
        stopped if they are running. Then the local hosting OS and PowerVC
        event locks are grabbed so that the periodic sync will not start
        until all pending events have been processed.
        """
        try:

            # Perform the periodic sync
            self._perform_periodic_sync()
        finally:

            # Start all event handlers if not running
            self._prepare_for_image_events()

    def _perform_periodic_sync(self):
        """
        Perform the periodic sync of images. A periodic sync of the images is
        done to ensure that any changes that may be missed by image
        notification events processing are still synchronized.

        The PowerVC and local hosting OS images are inspected for changes.
        Adds, deletes, and updates are determined for each server, and then
        applied to the other server. When complete, the PowerVC images on
        each server will be synchronized.
        """
        LOG.info(_('Performing periodic image synchronization...'))

        # Initialize the sync result value
        sync_result = constants.SYNC_FAILED

        # Save start time for elapsed time calculation
        start_time = time.time()

        # Need to stop or disable image event notification processing
        # here in the future.

        # Build a dict of PowerVC images with the UUID as the key
        # NOTE: If holding all images in memory becomes a problem one
        # option may be to rewrite the code to only get a full image
        # when needed.
        pvc_image_dict = {}

        # Build a dict of hosting OS images that came from PowerVC with the
        # PowerVC UUID as the key. Images from PowerVC will have the property
        # 'powervc_uuid'. If that is not present, ignore
        # NOTE: If holding all images in memory becomes a problem one
        # option may be to rewrite the code to only get a full image
        # when needed.
        local_image_dict = {}

        # Initialize stats for summary display
        self._clear_sync_summary_counters()

        # Try catching all exceptions so we don't end our periodic task
        # If an error occurs during synchronization it is logged
        try:

            # Get the images dict for the hosting OS
            local_v1client = self._get_local_v1_client()
            v1local_images = local_v1client.images
            local_image_dict = self._get_local_images_and_ids(v1local_images)

            # Get the images dict from PowerVC. Only get images that are
            # accessible from our Storage Connectivity Group. If the SCG is
            # not found, an exception is raised and the sync will fail here.
            pvc_v1client = self._get_pvc_v1_client()
            v1pvc_images = pvc_v1client.images
            pvc_image_dict = self._get_pvc_images(v1pvc_images)

            # Dump the local image information
            self._dump_image_info(local_image_dict, pvc_image_dict)

            # Get the images to work with for adds, deletes, and updates
            # When catching exceptions during sync operations we will look for
            # CommunicationError, and raise those so we don't waste time
            # trying to process all images when there is a connection failure.
            # Other exceptions should be caught and logged during each
            # operation so we can attempt to process each image before leaving.
            pvc_v2client = self._get_pvc_v2_client()
            local_v2client = self._get_local_v2_client()
            v2local_images = local_v2client.images
            v2pvc_images = pvc_v2client.images

            # Get the image sets from the past run, and the current run
            past_local_image_set = set(self.local_updated_at)
            past_pvc_image_set = set(self.pvc_updated_at)
            cur_local_image_set = set(local_image_dict)
            cur_pvc_image_set = set(pvc_image_dict)

            # We only need to update sync images that are in both PowerVC and
            # the local hosting OS. If an image is missing from either side
            # it will be added or deleted, so no need to try to update it.
            # Do the update syncing first followed by delete, and add syncing.
            # Start the update sync by getting common images on both sides.
            update_candidates = \
                cur_local_image_set.intersection(cur_pvc_image_set)

            # Only update sync images that were updated on either the local
            # hosting OS or on PowerVC. If both images seem to be in sync
            # based on their updated_at values, use the checksum to determine
            # if they are the same, and if they are not, merge them. Also,
            # check for the instance capture snapshot image condition. If the
            # local image status is queued and the PowerVC image status is
            # active force an update from the PowerVC to the local hostingOS to
            # activate the local snapshot image.
            for uuid in update_candidates:
                local_image = local_image_dict[uuid]
                pvc_image = pvc_image_dict[uuid]
                local_updated = self._local_image_updated(uuid, local_image)
                pvc_updated = self._pvc_image_updated(uuid, pvc_image)

                # Add an extra property named image_topology , which allows
                # user to select a SCG/Storage Template when booting an VM
                image_topology_updated = False
                image_topology_prop = \
                    self._format_special_image_extra_property(uuid)
                image_properties = \
                    self._get_image_properties(pvc_image.to_dict())
                image_properties[u'image_topology'] = \
                    unicode(image_topology_prop)
                if 'image_topology' not in local_image.properties.keys() or \
                        local_image.properties['image_topology'] != \
                        image_properties[u'image_topology']:
                    pvc_image.properties = image_properties
                    pvc_image._info['properties'] = image_properties
                    image_topology_updated = True

                local_checksum = \
                    self._get_image_checksum(local_image.to_dict())
                pvc_checksum = self._get_image_checksum(pvc_image.to_dict())

                # See if we need to activate a local queued snapshot image from
                # an instance capture
                if local_image.status == 'queued' and \
                        pvc_image.status == 'active':
                    LOG.info(_('Performing update sync of snapshot image '
                               '\'%s\' from PowerVC to the local hosting OS to'
                               ' activate the image.'), local_image.name)

                    # Update sync PowerVC image to local snapshot image to
                    # activate it
                    updated_image = self._update_local_image(uuid, pvc_image,
                                                             local_image,
                                                             v1local_images,
                                                             v2local_images)
                    if updated_image is None:
                        LOG.error(_('Local hosting OS snapshot image \'%s\' '
                                    'for PowerVC UUID %s was not activated '
                                    'during periodic image synchronization. It'
                                    ' will be activated again during the next '
                                    'periodic image synchronization '
                                    'operation.'), local_image.name, uuid)
                    else:
                        self.local_updated_count += 1

                        # Capture the current update times for use during the
                        # next periodic sync operation. The update times are
                        # stored in a dict with the PowerVC UUID as the keys
                        # and the updated_at image attribute as the values.
                        self.local_updated_at[uuid] = updated_image.updated_at
                        self.pvc_updated_at[uuid] = pvc_image.updated_at

                        # Save the PowerVC image as the master image
                        self.master_image[uuid] = pvc_image
                elif local_updated and pvc_updated:

                    # If the image was updated on the local hostingOS and
                    # on PowerVC since the last periodic scan, then the two
                    # images need to be merged, and both updated with the
                    # result.
                    updated_local_image, updated_pvc_image = \
                        self._update_with_merged_images(uuid, local_image,
                                                        pvc_image,
                                                        v1local_images,
                                                        v2local_images,
                                                        v1pvc_images,
                                                        v2pvc_images)
                    if updated_local_image is not None:
                        self.local_updated_count += 1
                    if updated_pvc_image is not None:
                        self.pvc_updated_count += 1
                elif local_updated:
                    LOG.info(_('Performing update sync of image \'%s\' from '
                               'the local hosting OS to PowerVC'),
                             local_image.name)

                    # To make sure the property image_topology is the newest
                    # between both side
                    if image_topology_updated:
                        old_local_image = local_image
                        local_image.properties['image_topology'] = \
                            pvc_image.properties['image_topology']
                        local_image._info['properties']['image_topology'] = \
                            pvc_image._info['properties']['image_topology']
                        self._update_local_image(uuid, local_image,
                                                 old_local_image,
                                                 v1local_images,
                                                 v2local_images)

                    # Update sync local image to PowerVC
                    updated_image = self._update_pvc_image(uuid, local_image,
                                                           pvc_image,
                                                           v1pvc_images,
                                                           v2pvc_images)

                    if updated_image is None:
                        LOG.error(_('PowerVC image \'%s\' with UUID %s was not'
                                    ' updated during periodic image '
                                    'synchronization. It will be updated again'
                                    ' during the next periodic image '
                                    'synchronization operation.'),
                                  pvc_image.name, uuid)
                    else:
                        self.pvc_updated_count += 1

                        # Capture the current update times for use during the
                        # next periodic sync operation. The update times are
                        # stored in a dict with the PowerVC UUID as the keys
                        # and the updated_at image attribute as the values.
                        self.pvc_updated_at[uuid] = updated_image.updated_at
                        self.local_updated_at[uuid] = local_image.updated_at

                        # Save the PowerVC image as the master image
                        self.master_image[uuid] = pvc_image
                elif pvc_updated:
                    LOG.info(_('Performing update sync of image \'%s\' from '
                               'PowerVC to the local hosting OS'),
                             local_image.name)

                    # Update sync PowerVC image to local
                    updated_image = self._update_local_image(uuid, pvc_image,
                                                             local_image,
                                                             v1local_images,
                                                             v2local_images)
                    if updated_image is None:
                        LOG.error(_('Local hosting OS image \'%s\' for PowerVC'
                                    ' UUID %s was not updated during periodic '
                                    'image synchronization. It will be updated'
                                    ' again during the next periodic image '
                                    'synchronization operation.'),
                                  local_image.name, uuid)
                    else:
                        self.local_updated_count += 1

                        # Capture the current update times for use during the
                        # next periodic sync operation. The update times are
                        # stored in a dict with the PowerVC UUID as the keys
                        # and the updated_at image attribute as the values.
                        self.local_updated_at[uuid] = updated_image.updated_at
                        self.pvc_updated_at[uuid] = pvc_image.updated_at

                        # Save the PowerVC image as the master image
                        self.master_image[uuid] = pvc_image
                elif local_checksum != pvc_checksum:

                    # This is a fail-safe check. This should not happen if the
                    # image updated_at values were handled properly. If we get
                    # here and the image checksum values are different, then
                    # merge the two images together to sync them up, and apply
                    # to both sides
                    LOG.info(_('Image \'%s\' is not in sync. The images from '
                               'the local hosting OS and PowerVC will be '
                               'merged to synchronize them.'),
                             local_image.name)

                    updated_local_image, updated_pvc_image = \
                        self._update_with_merged_images(uuid, local_image,
                                                        pvc_image,
                                                        v1local_images,
                                                        v2local_images,
                                                        v1pvc_images,
                                                        v2pvc_images)
                    if updated_local_image is not None:
                        self.local_updated_count += 1
                    if updated_pvc_image is not None:
                        self.pvc_updated_count += 1
                else:
                    LOG.info(_('Image \'%s\' is in sync'), local_image.name)

            # Find local adds, and deletes
            # Deletes are images in the past that are not in the current
            local_deletes = \
                past_local_image_set.difference(cur_local_image_set)

            # Adds are images in the current that are not in the past
            local_adds = cur_local_image_set.difference(past_local_image_set)

            # Process local adds, and deletes by applying to the PowerVC
            # There should not be any adds from the hosting OS to
            # PowerVC since that is not currently supported. If any are
            # found, log it, and ignore
            for uuid in local_deletes:
                if uuid in pvc_image_dict.keys():
                    pvc_image = pvc_image_dict[uuid]
                    LOG.info(_('Deleting PowerVC image \'%s\' for UUID %s'),
                             pvc_image.name, uuid)
                    deleted_image = self._delete_pvc_image(uuid, pvc_image,
                                                           v1pvc_images)
                    if deleted_image is None:
                        LOG.error(_('PowerVC image \'%s\' with UUID %s was not'
                                    ' deleted during periodic image'
                                    'synchronization.'), pvc_image.name,
                                  uuid)
                    else:
                        self.pvc_deleted_count += 1

                        # Clean up the updated_at time and master_image
                        if uuid in self.pvc_updated_at.keys():
                            self.pvc_updated_at.pop(uuid)
                        if uuid in self.master_image.keys():
                            self.master_image.pop(uuid)

                        # Clean up the updated_at time. Only do this if the
                        # PowerVC image is also gone, else it won't be deleted
                        # during the next periodic sync.
                        if uuid in self.local_updated_at.keys():
                            self.local_updated_at.pop(uuid)

                        # Clean up the ids_dict
                        if uuid in self.ids_dict.keys():
                            self.ids_dict.pop(uuid)
                else:

                    # Clean up the updated_at time. Only do this if the PowerVC
                    # image is also gone, else it won't be deleted during the
                    # next periodic sync.
                    if uuid in self.local_updated_at.keys():
                        self.local_updated_at.pop(uuid)

            # This could happen if an instance capture was started on the
            # hostingOS, which results in a snapshot image on the hostingOS,
            # but there may not be a corresponding snapshot image on PowerVC
            # yet. In that case, log it, and continue. Otherwise, this should
            # not happen. If it does, log a warning, and ignore
            for uuid in local_adds:
                if uuid not in pvc_image_dict.keys():
                    local_image = local_image_dict[uuid]
                    if local_image.status == 'queued':

                        # It is possible that there are images on the hosting
                        # OS that are queued. These would be from instance
                        # captures that are in progress. We will go ahead and
                        # track those, and keep their updated_at timestamp so
                        # they are not treated as an add later on.
                        self.local_updated_at[uuid] = local_image.updated_at
                        self.ids_dict[uuid] = local_image.id

                        # If there is no master_image for this UUID, create
                        # one now. It will be used to merge the PowerVC
                        # image with this one when one is available.
                        if uuid not in self.master_image.keys():
                            self.master_image[uuid] = local_image
                        LOG.debug(_('A new PowerVC snapshot image \'%s\' with '
                                    'PowerVC UUID %s was detected on the local'
                                    ' hosting OS, but it is not yet present on'
                                    ' the PowerVC.'), local_image.name, uuid)
                    else:
                        LOG.warning(_('A new PowerVC image \'%s\' was detected'
                                      ' on the local hosting OS. This is not '
                                      'supported!'), local_image.name)

            # Find PowerVC adds, and deletes
            # Deletes are images in the past that are not in the current
            pvc_deletes = past_pvc_image_set.difference(cur_pvc_image_set)

            # Adds are images in the current that are not in the past
            pvc_adds = cur_pvc_image_set.difference(past_pvc_image_set)

            # Process PowerVC adds, and deletes by applying them to the local
            # hosting OS
            for uuid in pvc_deletes:
                if uuid in local_image_dict.keys():
                    local_image = local_image_dict[uuid]
                    LOG.info(_('Deleting local hosting OS image \'%s\' for '
                               'PowerVC UUID %s'), local_image.name, uuid)
                    deleted_image = self._delete_local_image(uuid, local_image,
                                                             v1local_images)
                    if deleted_image is None:
                        LOG.error(_('Local hosting OS image \'%s\' for PowerVC'
                                    ' UUID %s was not deleted during periodic '
                                    'image synchronization.'),
                                  local_image.name, uuid)
                    else:
                        self.local_deleted_count += 1

                        # Clean up the updated_at time and master_image
                        if uuid in self.local_updated_at.keys():
                            self.local_updated_at.pop(uuid)
                        if uuid in self.master_image.keys():
                            self.master_image.pop(uuid)

                        # Clean up the updated_at time. Only do this if the
                        # local hostingOS image is also gone, else it won't be
                        # deleted during the next periodic sync.
                        if uuid in self.pvc_updated_at.keys():
                            self.pvc_updated_at.pop(uuid)

                        # Clean up the ids_dict
                        if uuid in self.ids_dict.keys():
                            self.ids_dict.pop(uuid)
                else:

                    # Clean up the updated_at time. Only do this if the local
                    # hostingOS image is also gone, else it won't be deleted
                    # during the next periodic sync.
                    if uuid in self.pvc_updated_at.keys():
                        self.pvc_updated_at.pop(uuid)

            # Process PowerVC adds
            local_image_owner = self._get_local_staging_owner_id()
            if local_image_owner is None:
                LOG.warning(_("Invalid staging user or project."
                              " Skipping new image sync."))
            else:
                for uuid in pvc_adds:
                    pvc_image = pvc_image_dict[uuid]
                    if uuid not in local_image_dict.keys():
                        status = pvc_image.status
                        pvc_name = pvc_image.name

                        # Only add images from PowerVC that are 'active', and
                        # that are accessible on our Storage Connectivity Group
                        if status and status == 'active':

                            # Add an extra property named image_topology ,
                            # which allows user to select a SCG/Storage
                            # Template when booting an VM
                            image_topology_prop = \
                                self._format_special_image_extra_property(uuid)
                            image_properties = \
                                self._get_image_properties(pvc_image.to_dict())
                            image_properties[u'image_topology'] = \
                                unicode(image_topology_prop)
                            pvc_image.properties = image_properties
                            pvc_image._info['properties'] = image_properties

                            # Add or activate the local image
                            self._add_or_activate_local_image(
                                pvc_image, local_image_owner,
                                pvc_v2client.http_client.endpoint,
                                v1local_images, v2local_images)
                        else:

                            # PowerVC image which are not in the active state
                            # will not be tracked, and so their updated_at
                            # timestamp will not be stored.
                            LOG.debug(_('Image \'%s\' with UUID %s not created'
                                        ' during periodic image '
                                        'synchronization because the image '
                                        'status is %s'), pvc_name, uuid,
                                      status)

            # All done! Set the periodic sync result as passed so subsequent
            # periodic syncs will run at the specified interval
            sync_result = constants.SYNC_PASSED

            # Format results for summary display
            stat_l = '{0:d}/{1:d}/{2:d}'.format(self.local_created_count,
                                                self.local_updated_count,
                                                self.local_deleted_count)
            stat_p = '{0:d}/{1:d}/{2:d}'.format(self.pvc_created_count,
                                                self.pvc_updated_count,
                                                self.pvc_deleted_count)
            stats = '(local:{0}, powervc:{1})'.format(stat_l, stat_p)

            # Calculate elapsed time
            end_time = time.time()
            elapsed_time = '{0:.4} seconds'.format(end_time - start_time)
            LOG.info(_('Periodic image synchronization is complete. Elapsed '
                       'time: %s %s'), elapsed_time, stats)
        except Exception as e:
            LOG.exception(_('An error occurred during periodic image '
                            'synchronization: %s'), e)
            LOG.info(_('Periodic image synchronization did not complete '
                       'successfully. It will be run again in %s seconds.'),
                     CONF['powervc'].image_sync_retry_interval_time_in_seconds)
        finally:

            # Tell the ImageSyncController that periodic sync has ended
            self.image_sync_controller.set_periodic_sync_result(sync_result)

    def _add_or_activate_local_image(self, pvc_image, local_image_owner,
                                     endpoint, v1local_images, v2local_images):
        """
        Add or activate a local hosting OS image from a PowerVC image.

        This is called when a new local image is to be added. The PowerVC image
        is first checked for the local UUID property. If it exists, the image
        is a snapshot image, and the local UUID property specifies the local
        snapshot image that is queued and is awaiting activation.

        :param: pvc_image The PowerVC image to add or activate on the local
                            hosting OS
        :param: local_image_owner The local image owner id
        :param: endpoint The PowerVC client endpoint to use for the image
                            location
        :param: v1local_images The local hostingOS v1 image manager of image
                                the controller to use
        :param: v2local_images The local hostingOS v2 image controller to use
        """

        # Check here for an existing local image. If one exists for this
        # PowerVC image, just update it. This can happen if an instance capture
        # was performed and a snapshot image was created, and no events were
        # received for the newly created image yet, and the local image doesn't
        # yet contain the powervc_uuid property.
        local_image = None
        pvc_id = pvc_image.id
        pvc_name = pvc_image.name
        props = self._get_image_properties(pvc_image.to_dict())
        if props and consts.LOCAL_UUID_KEY in props.keys():

            # Look for the LOCAL_UUID_KEY in the PowerVC image. If it is found
            # it will be used to get the local image. This should be set when
            # an instance is captured, and a snapshot image is created on the
            # PowerVC.
            local_id = props.get(consts.LOCAL_UUID_KEY)
            if self._local_image_exists(local_id, v1local_images):
                local_image = self._get_image(pvc_id, local_id, pvc_name,
                                              v1local_images, v2local_images)

        # Update the image if it is in the local hosting OS, else add it
        if local_image is not None:
            LOG.info(_('The local hosting OS image \'%s\' with PowerVC UUID %s'
                       ' already exists so it will be updated.'), pvc_name,
                     pvc_id)

            # If this is a snapshot image, it may not have an entry in the ids
            # dict so add one here.
            self.ids_dict[pvc_id] = local_image.id
            LOG.info(_('Performing update sync of snapshot image \'%s\' from '
                       'PowerVC to the local hosting OS to activate the '
                       'image.'), local_image.name)

            # Update sync PowerVC image to local snapshot image to activate it
            updated_image = self._update_local_image(pvc_id, pvc_image,
                                                     local_image,
                                                     v1local_images,
                                                     v2local_images)
            if updated_image is None:
                LOG.error(_('Local hosting OS snapshot image \'%s\' for '
                            'PowerVC UUID %s was not activated during '
                            'image synchronization. It will be activated again'
                            ' during the next image synchronization '
                            'operation.'), local_image.name, pvc_id)
            else:
                self.local_updated_count += 1

                # Capture the current update times for use during the next
                # periodic sync operation. The update times are stored in a
                # dict with the PowerVC UUID as the keys and the updated_at
                # image attribute as the values.
                self.local_updated_at[pvc_id] = updated_image.updated_at
                self.pvc_updated_at[pvc_id] = pvc_image.updated_at

                # Save the PowerVC image as the master image
                self.master_image[pvc_id] = pvc_image
        else:
            LOG.info(_('Creating image \'%s\' on the local hosting OS'),
                     pvc_name)
            new_image = self._add_local_image(pvc_id, pvc_image,
                                              local_image_owner, endpoint,
                                              v1local_images, v2local_images)
            if new_image is None:
                LOG.error(_('Local hosting OS image \'%s\' for PowerVC UUID %s'
                            ' was not created during image synchronization.'),
                          pvc_name, pvc_id)
            else:
                self.local_created_count += 1

                # Capture the current update times for use during the next
                # periodic sync operation. The update times are stored in dicts
                # with the PowerVC UUID as the keys and the updated_at image
                # attribute as the values.
                self.pvc_updated_at[pvc_id] = pvc_image.updated_at
                self.local_updated_at[pvc_id] = new_image.updated_at

                # Save the PowerVC image as the master_image
                self.master_image[pvc_id] = pvc_image

                # Save the ids in the ids_dict
                self.ids_dict[pvc_id] = new_image.id

    def _update_with_merged_images(self, uuid, local_image, pvc_image,
                                   v1local_images, v2local_images,
                                   v1pvc_images, v2pvc_images):
        """
        Both the local hostingOS image, and the PowerVC image have been
        updated. Merge the two images with the master_image to come up
        with the image that will be used to update the local hostingOS,
        and PowerVC.

        If an image first appears on PowerVC and the local hostingOS without
        events, there will be no master_image set. In that case, use the oldest
        image as the master_image, and then merge in the newest image.

        :param: uuid The PowerVC UUID of the image
        :param: local_image The local hostingOS copy of the image
        :param: pvc_image The PowerVC copy of the image
        :param: v1local_images The local hostingOS v1 image manager of image
                                the controller to use
        :param: v2local_images The local hostingOS v2 image controller to use
        :param: v1pvc_images The PowerVC v1 image manager of the image
                                controller to use
        :param: v2pvc_images The PowerVC v2 image controller to use
        :returns: A tuple containing the updated local hostingOS image, and the
                    updated PowerVC image. If a problem was encountered
                    updating either image, None is returned for that image.
        """
        try:
            local_updated_at = self._get_v1_datetime(local_image.updated_at)
            pvc_updated_at = self._get_v1_datetime(pvc_image.updated_at)
            LOG.debug(_('local_updated_at %s, pvc_updated_at %s'),
                      local_updated_at, pvc_updated_at)
        except Exception as e:
            LOG.exception(_('An error occurred determining image '
                            'update time for %s: %s'), local_image.name, e)

        # Updated images to return to the caller
        updated_local_image = None
        updated_pvc_image = None
        if local_updated_at and pvc_updated_at:
            LOG.info(_('Image \'%s\' for PowerVC UUID %s was updated on the '
                       'local hostingOS, and on PowerVC. Attempting to '
                       'merge the changes together and update both with '
                       'the result.'), local_image.name, uuid)

            # If we have a master copy of the image we can merge changes from
            # the local hostingOS and PowerVC. If there is no master copy of
            # the image, use the oldest image as the master copy to merge with.
            if uuid not in self.master_image.keys():
                LOG.debug(_('A master copy of image \'%s\' for PowerVC UUID %s'
                            ' is not available. The oldest image will be the '
                            'master copy used to merge the newer changes'
                            'with.'), local_image.name, uuid)
                if (local_updated_at > pvc_updated_at):
                    LOG.debug(_('The PowerVC image \'%s\' with UUID %s will be'
                                ' the master copy to merge with.'),
                              pvc_image.name, uuid)

                    # The PowerVC image will be the master copy for the merge.
                    # Get a copy of the PowerVC image to use as the master.
                    master_image = self._get_image(uuid, pvc_image.id,
                                                   pvc_image.name,
                                                   v1pvc_images, v2pvc_images)
                else:
                    LOG.debug(_('The local hostingOS image \'%s\' for PowerVC '
                                'UUID %s will be the master copy to merge '
                                'with.'), local_image.name, uuid)

                    # The local hostingOS image will be the master copy for the
                    # Get a copy of the local hostingOS image to use as the
                    # master.
                    master_image = self._get_image(uuid, local_image.id,
                                                   local_image.name,
                                                   v1local_images,
                                                   v2local_images)
            else:
                master_image = self.master_image[uuid]

            # Determine what has changed in the hostingOS and PowerVC images.
            # This is done by first comparing the older image with the master
            # copy of the image, and then the newer image with the master copy
            # of the image. Then any changes are merged into the master copy of
            # the image, and that is used to update sync both the hostingOS and
            # PowerVC images.
            attribute_changes = {}
            property_changes = {}
            deleted_property_keys = []
            if local_updated_at > pvc_updated_at:
                self._get_image_changes(pvc_image, master_image,
                                        attribute_changes, property_changes,
                                        deleted_property_keys)
                self._get_image_changes(local_image, master_image,
                                        attribute_changes, property_changes,
                                        deleted_property_keys)
            else:
                self._get_image_changes(local_image, master_image,
                                        attribute_changes, property_changes,
                                        deleted_property_keys)
                self._get_image_changes(pvc_image, master_image,
                                        attribute_changes, property_changes,
                                        deleted_property_keys)

            # Merge the image attribute and property changes found with a copy
            # of the master image and update sync the master image
            # with the local hostingOS and PowerVC.
            self._merge_image_changes(attribute_changes, property_changes,
                                      deleted_property_keys, master_image)

            # Update both PowerVC and the local hostingOS images with the
            # master copy. The same rule applies here as elsewhere. The
            # updated_at timestamp dicts, and the master_image will not be
            # reset until both updates are successful. That way, if one fails,
            # the merge will be tried again in the next periodic scan. An
            # attempt will first be made to update the local hostingOS image
            # since it is customer facing. If that is successful, the
            # PowerVC image is updated.
            LOG.info(_('Performing update sync of image \'%s\' from merged '
                       'master image to the local hosting OS for PowerVC UUID '
                       '%s'), master_image.name, uuid)

            # Update sync master image to local hostingOS. This merge could be
            # of a PowerVC active snapshot image to a hostingOS queued snapshot
            # image. In that case, the master_image status must be set to
            # active for the hostingOS update to work properly. Modify the
            # image by setting the attribute first, and then the _info dict.
            if pvc_image.status == 'active':
                setattr(master_image, 'status', pvc_image.status)
                master_image._info['status'] = pvc_image.status
            LOG.debug(_('Master image for local: %s'), str(master_image))
            updated_local_image = self._update_local_image(uuid, master_image,
                                                           local_image,
                                                           v1local_images,
                                                           v2local_images)
            if updated_local_image is None:
                LOG.error(_('Local hosting OS image \'%s\' for PowerVC UUID %s'
                            ' was not updated. The PowerVC image was also not '
                            'updated. An attempt to synchronize both will be '
                            'tried again during the next periodic image '
                            'synchronization operation.'), local_image.name,
                          uuid)
            else:
                LOG.info(_('Performing update sync of image \'%s\' from the '
                           'merged master image to PowerVC for PowerVC UUID '
                           '%s'), master_image.name, uuid)

                # Update sync master image to PowerVC
                LOG.debug(_('Master image for pvc: %s'), str(master_image))
                updated_pvc_image = self._update_pvc_image(uuid, master_image,
                                                           pvc_image,
                                                           v1pvc_images,
                                                           v2pvc_images)
                if updated_pvc_image is None:
                    LOG.error(_('PowerVC image \'%s\' with UUID %s was not '
                                'updated, however, the corresponding local '
                                'hostingOS image was updated. An attempt to '
                                'synchronize both will be tried again during '
                                'the next periodic image synchronization '
                                'operation.'), pvc_image.name, uuid)
                else:

                    # Capture the current update times for use during the next
                    # periodic sync operation. The update times are stored in
                    # dicts with the PowerVC UUID as the key and the updated_at
                    # image attribute as the values.
                    self.local_updated_at[uuid] = \
                        updated_local_image.updated_at
                    self.pvc_updated_at[uuid] = updated_pvc_image.updated_at

                    # Save the PowerVC image as the master_image
                    self.master_image[uuid] = updated_pvc_image
        else:

            # There was an error getting the updated_at time for an image.
            # This should not happen, but if it does, sync the PowerVC image
            # to the local hosting OS
            LOG.info(_('Performing update sync of image \'%s\' from PowerVC to'
                       ' the local hosting OS'), local_image.name)

            # Update sync PowerVC image to local hostingOS
            updated_local_image = self._update_local_image(uuid, pvc_image,
                                                           local_image,
                                                           v1local_images,
                                                           v2local_images)
            if updated_local_image is None:
                LOG.error(_('Local hosting OS image \'%s\' for PowerVC UUID %s'
                            ' was not updated during periodic '
                            'synchronization.'), local_image.name, uuid)
            else:

                # Capture the current update times for use during the next
                # periodic sync operation. The update times are stored in dicts
                # with the PowerVC UUID as the keys and the updated_at image
                # attribute as the values.
                self.local_updated_at[uuid] = updated_local_image.updated_at
                self.pvc_updated_at[uuid] = pvc_image.updated_at

                # Save the PowerVC image as the master_image
                self.master_image[uuid] = pvc_image

        # return the updated images to the caller
        return updated_local_image, updated_pvc_image

    def _get_image_changes(self, updated_image, master_image,
                           attribute_changes, property_changes,
                           deleted_property_keys):
        """
        Compare the updated image with the master copy of the image. Look at
        the UPDATE_PARAMS and properties for any changes. Image attributes
        can only be added or updated. Image properties can only be added,
        updated, or deleted. Any image attribute or property changed is
        added to the dict of image changes. Any deleted properties are added
        to the dict of deleted properties.

        This method is first called for the side that is oldest, and then the
        more recent side. If a property is deleted on one side, it will be
        kept if it was updated on the more recent side. The most recent changes
        are used over the older ones.

        When looking for image changes, filter out the appropriate attributes
        and properties using the update filters.

        :param: updated_image The updated image to check for changes against
                                the master copy of the image
        :param: master_image The master copy of the image to compare to
        :param: attribute_changes The dict of image attribute changes.
        :param: property_changes The dict of image property changes.
        :param: deleted_property_keys The list of deleted image property keys.
        """
        updated_image_dict = updated_image.to_dict()
        master_image_dict = master_image.to_dict()

        # Process the image attributes we care about
        for imagekey in updated_image_dict.keys():

            # Only update attributes in UPDATE_PARAMS if they are not in the
            # update param filter list. Also, skip over the properties
            # attribute and process those separately.
            if imagekey in v1images.UPDATE_PARAMS and \
                imagekey not in constants.IMAGE_UPDATE_PARAMS_FILTER and \
                    imagekey != 'properties':
                field_value = updated_image_dict.get(imagekey)
                if field_value is not None:

                    # If the key is not in the master image, add it. If it
                    # is in the master_image, see if it has changed.
                    if imagekey not in master_image_dict.keys():
                        attribute_changes[imagekey] = field_value
                    elif field_value != master_image_dict.get(imagekey):
                        attribute_changes[imagekey] = field_value

        # Process the image properties
        updated_props = self._get_image_properties(updated_image_dict, {})
        master_props = self._get_image_properties(master_image_dict, {})
        for propkey in updated_props.keys():
            if propkey not in constants.IMAGE_UPDATE_PROPERTIES_FILTER:
                prop_value = updated_props.get(propkey)
                if prop_value is not None:

                    # If the property is not in the master image, add it. If it
                    # is in the master_image, see if it has changed.
                    if propkey not in master_props.keys():
                        property_changes[propkey] = prop_value
                    elif prop_value != master_props.get(propkey):

                        # The property has changed. If this property
                        # is in the deleted_properties dict, from a
                        # previous call, remove it. It has been updated
                        # on the other server so keep it for now.
                        property_changes[propkey] = prop_value
                        if propkey in deleted_property_keys:
                            deleted_property_keys.remove(propkey)

        # Detect any deleted properties. Those are properties that are in the
        # master image, but no longer available in the updated image. The
        # filtered properties will not be looked at.
        for propkey in master_props.keys():
            if propkey not in constants.IMAGE_UPDATE_PROPERTIES_FILTER and \
                    propkey not in updated_props.keys():
                deleted_property_keys.append(propkey)

    def _merge_image_changes(self, attribute_changes, property_changes,
                             deleted_property_keys, master_image):
        """
        Go through all of the image attribute and property changes, and
        apply them to the master copy of the image.

        :param: attribute_changes The dict of image attribute changes.
        :param: property_changes The dict of image property changes.
        :param: deleted_property_keys The list of deleted image property keys.
        :param: master_image The master copy of the image to merge
                                changes into
        """
        # Merge the changes into the master_image which is a v1 Image. A v1
        # Image has both attributes and a Resource _info dict. To modify a v1
        # Image we must first set the attribute, followed by the _info dict.
        # The _info dict is important here. It is what is used when updating
        # the image. We will try to update both to be complete, but testing has
        # shown that the setattr does not work as expected here.
        LOG.debug(_('attribute changes: %s'), str(attribute_changes))
        LOG.debug(_('property changes: %s'), str(property_changes))
        LOG.debug(_('deleted properties: %s'), str(deleted_property_keys))
        for key in attribute_changes.keys():
            if key in master_image._info.keys() and hasattr(master_image, key):
                setattr(master_image, key, attribute_changes.get(key))
                master_image._info[key] = attribute_changes.get(key)
            else:

                # This is unexpected so log a warning
                LOG.warning(_('Image attribute \'%s\' was not updated for '
                              'image \'%s\'.'), key, master_image.name)

        # Process image properties
        master_props = self._get_image_properties(master_image._info, {})

        # Process property adds and updates
        for prop_key in property_changes.keys():
            master_props[prop_key] = property_changes.get(prop_key)

        # Process property deletes
        for prop_key in deleted_property_keys:
            if prop_key in master_props.keys():
                master_props.pop(prop_key)

        # Reset the image properties
        master_image.properties = master_props
        master_image._info['properties'] = master_props
        LOG.debug(_('Master image for merge: %s'), str(master_image))

    def _get_image(self, uuid, image_id, image_name, v1images, v2images):
        """
        Get the specified image using the v1 API. If the image has one or more
        large properties, get the v2 image, and fixup the properties of the v1
        image.

        :param: uuid The PowerVC UUID of the image
        :param: image_id The identifier of the image to get
        :param: image_name The name of the image to get. This is optional. It
                            is used for logging.
        :param: v1images The image manager of the image controller to use
        :param: v2images The image controller to use
        :returns: The v1 image specified, or None if the image could not be
                    obtained
        """
        try:
            v1image = v1images.get(image_id)
            props = self._get_image_properties(v1image.to_dict(), {})
            large_props = {}
            for propkey in props.keys():
                propval = props.get(propkey)

                # If the property value is large, read it in with the v2 GET
                # API to make sure we get the whole thing. Setting a limit of
                # MAX_HEADER_LEN_V1/2 seems to work well.
                if propval is not None and len(str(propval)) >= \
                        constants.MAX_HEADER_LEN_V1 / 2:
                    large_props[propkey] = propval
            if large_props:
                v2image = v2images.get(image_id)
                for propkey in large_props.keys():
                    if propkey in v2image.keys():
                        props[propkey] = v2image[propkey]
                self._unescape(props)
            v1image.properties = props
            v1image._info['properties'] = props
            return v1image
        except CommunicationError as e:
            raise e
        except Exception as e:
            LOG.exception(_('An error occurred getting image \'%s\' for '
                            'PowerVC UUID %s: %s'), image_name, uuid, e)
            return None

    def _delete_local_image(self, uuid, image, v1images):
        """
        Delete the specified local image using the v1 API.

        Also, set to ignore any image delete events that may be generated by
        the image delete operation here.

        :param: uuid The PowerVC UUID of the image
        :param: image The v1 image to delete
        :param: v1images The image manager of the image controller to use
        :returns: The deleted v1 image if the delete was successful, else None
        """
        deleted_image = self._delete_image(uuid, image, v1images)
        if deleted_image is not None:
            self._ignore_local_event(constants.IMAGE_EVENT_TYPE_DELETE,
                                     deleted_image.to_dict())
        return deleted_image

    def _delete_pvc_image(self, uuid, image, v1images):
        """
        Delete the specified PowerVC image using the v1 API.

        Also, set to ignore any image delete events that may be generated by
        the image delete operation here.

        :param: uuid The PowerVC UUID of the image
        :param: image The v1 image to delete
        :param: v1images The image manager of the image controller to use
        :returns: The deleted v1 image if the delete was successful, else None
        """
        deleted_image = self._delete_image(uuid, image, v1images)
        if deleted_image is not None:
            self._ignore_pvc_event(constants.IMAGE_EVENT_TYPE_DELETE,
                                   deleted_image.to_dict())
        return deleted_image

    def _delete_image(self, uuid, image, v1images):
        """
        Delete the specified image using the v1 API.

        This method should not be called directly. It should only be called by
        _delete_local_image and _delete_pvc_image.

        :param: uuid The PowerVC UUID of the image
        :param: image The v1 image to delete
        :param: v1images The image manager of the image controller to use
        :returns: The deleted v1 image if the delete was successful, else None
        """
        try:
            deleted_image = image
            v1images.delete(image)
            return deleted_image
        except CommunicationError as e:
            raise e
        except HTTPNotFound:
            LOG.info(_('An attempt was made to delete image \'%s\' for PowerVC'
                       ' UUID %s, but the image was not found.'), image.name,
                     uuid)
            return deleted_image
        except Exception as e:
            LOG.exception(_('An error occurred deleting image '
                            '%s for PowerVC UUID %s: %s'),
                          image.name, uuid, e)
            return None

    def _add_local_image(self, uuid, src_image, image_owner, image_endpoint,
                         v1images, v2images):
        """
        Add an the image represented by the source image using the v1
        and v2 APIs. The local hostingOS image is returned to the caller.

        We currently only add images to the local hosting OS.

        :param: uuid The PowerVC UUID of the image
        :param: src_image The source v1 image to add
        :param: image_owner The id of the image owner
        :param: image_endpoint The endpoint to use for the image location
        :param: v1images The v1 image manager to use for creating
        :param: v2images The v2 image controller to use for patching
        :returns: A tuple containing the added v1 images. The first image
                    returned is from the v1 image create, and the second
                    image returned is from the v2 image PATCH update if any.
        """
        image1, image2 = self._add_image(uuid, src_image, image_owner,
                                         image_endpoint, v1images, v2images)

        # FIXME - Should we also ignore the activate event?
        # FIXME - Do we get an update event for a create/activate?
        # Set to ignore any update events generated by adding the image
        create_event_type = constants.IMAGE_EVENT_TYPE_CREATE
        activate_event_type = constants.IMAGE_EVENT_TYPE_ACTIVATE
        update_event_type = constants.IMAGE_EVENT_TYPE_UPDATE
        if image1 is not None:
            self._ignore_local_event(create_event_type, image1.to_dict())
            self._ignore_local_event(activate_event_type, image1.to_dict())
            self._ignore_local_event(update_event_type, image1.to_dict())
        if image2 is not None:
            self._ignore_local_event(update_event_type, image2.to_dict())
        return image1 if image2 is None else image2

    def _add_image(self, uuid, src_image, image_owner, image_endpoint,
                   v1images, v2images):
        """
        Add an the image represented by the source image using the v1
        and v2 APIs. The local hostingOS image is returned to the caller.

        We currently only add images to the local hosting OS.

        This method should not be called directly. It should only be called by
        _add_local_image.

        :param: uuid The PowerVC UUID of the image
        :param: src_image The source v1 image to add
        :param: image_owner The id of the image owner
        :param: image_endpoint The endpoint to use for the image location
        :param: v1images The v1 image manager to use for creating
        :param: v2images The v2 image controller to use for patching
        :returns: A tuple containing the added v1 images. The first image
                    returned is from the v1 image create, and the second
                    image returned is from the v2 image PATCH update if any.
        """
        try:
            field_dict, update_field_dict = self._get_v1image_create_fields(
                src_image, image_owner, image_endpoint)
            # Community fix needs the property 'checksum' must be set
            field_dict['checksum'] = self._get_image_checksum(
                src_image.to_dict())
            new_image = v1images.create(**field_dict)
            updated_image = None
            if len(update_field_dict) > 0:

                # After creating the image, update it with the
                # remaining attributes and metadata. The v2 API
                # PATCH update will figure out what to add,
                # or replace. Deletes are not possible.
                v2images.update(new_image.id, **update_field_dict)

                # refresh the v1 image to return after the update
                updated_image = self._get_image(uuid, new_image.id,
                                                new_image.name, v1images,
                                                v2images)
            return new_image, updated_image
        except CommunicationError as e:
            raise e
        except Exception as e:
            LOG.exception(_('An error occurred creating image \'%s\' for '
                            'PowerVC UUID %s: %s'), src_image.name, uuid, e)
            return None, None

    def _update_local_image(self, uuid, src_image, tgt_image, v1images,
                            v2images):
        """
        Update the local hostingOS target image with the source image
        attributes and properties. If the update is being used to activate the
        image, or if the image size is changing, the v1 Glance client is used,
        else the v2 Glance client is used.

        :param: uuid The PowerVC UUID of the image
        :param: src_image The source PowerVC v1 image to use for the update
        :param: tgt_image The target local hostingOS v1 image to update
        :param: v1images The v1 image manager to use for updating
        :param: v2images The v2 image controller to use for patching
        :returns: The updated v1 image, or None if the update was not
                    successful.
        """
        if ((src_image.status == 'active' and tgt_image.status == 'queued') or
                (src_image.size != tgt_image.size)):
            return self._v1update_local_image(uuid, src_image, tgt_image,
                                              v1images, v2images)
        else:
            return self._v2update_local_image(uuid, src_image, tgt_image,
                                              v1images, v2images)

    def _update_pvc_image(self, uuid, src_image, tgt_image, v1images,
                          v2images):
        """
        Update the PowerVC target image with the source image attributes and
        properties. If image size is changing, the v1 Glance client is used,
        else the v2 Glance client is used.

        :param: uuid The PowerVC UUID of the image
        :param: src_image The source local hostingOS v1 image to use for the
                            update
        :param: tgt_image The target PowerVC image to update
        :param: v1images The v1 image manager to use for updating.
        :param: v2images The v2 image controller to use for patching
        :returns: The updated v1 image, or None if the update was not
                    successful.
        """
        if src_image.size != tgt_image.size:
            return self._v1update_pvc_image(uuid, src_image, tgt_image,
                                            v1images, v2images)
        else:
            return self._v2update_pvc_image(uuid, src_image, tgt_image,
                                            v1images, v2images)

    def _v1update_local_image(self, uuid, src_image, tgt_image, v1images,
                              v2images):
        """
        Update the local hostingOS target image with the source image
        attributes and properties using the v1 and v2 Glance clients.

        Also, set to ignore any image update events that may be generated by
        the image update operation here.

        :param: uuid The PowerVC UUID of the image
        :param: src_image The source PowerVC v1 image to use for the update
        :param: tgt_image The target local hostingOS v1 image to update
        :param: v1images The v1 image manager to use for updating
        :param: v2images The v2 image controller to use for patching
        :returns: The updated v1 image, or None if the update was not
                    successful.
        """
        image1, image2 = self._v1update_image(uuid, src_image, tgt_image,
                                              v1images, v2images,
                                              constants.LOCAL)

        # Set to ignore any update events generated by updating the image
        add_event_type = constants.IMAGE_EVENT_TYPE_ACTIVATE
        update_event_type = constants.IMAGE_EVENT_TYPE_UPDATE
        if image1 is not None:

            # If this is going to activate an instance capture on the local
            # hostingOS set to ignore the activate, and the update that comes
            # along with every activate.
            if src_image.status == 'active' and tgt_image.status == 'queued':
                self._ignore_local_event(add_event_type, image1.to_dict())
                self._ignore_local_event(update_event_type, image1.to_dict())
            self._ignore_local_event(update_event_type, image1.to_dict())
        if image2 is not None:
            self._ignore_local_event(update_event_type, image2.to_dict())
        return image1 if image2 is None else image2

    def _v1update_pvc_image(self, uuid, src_image, tgt_image, v1images,
                            v2images):
        """
        Update the PowerVC target image with the source image attributes and
        properties using the v1 and v2 Glance clients.

        Also, set to ignore any image update events that may be generated by
        the image update operation here.

        :param: uuid The PowerVC UUID of the image
        :param: src_image The source local hostingOS v1 image to use for the
                            update
        :param: tgt_image The target PowerVC image to update
        :param: v1images The v1 image manager to use for updating
        :param: v2images The v2 image controller to use for patching
        :returns: The updated v1 image, or None if the update was not
                    successful.
        """
        image1, image2 = self._v1update_image(uuid, src_image, tgt_image,
                                              v1images, v2images,
                                              constants.POWER_VC)

        # Set to ignore any update events generated by updating the image
        event_type = constants.IMAGE_EVENT_TYPE_UPDATE
        if image1 is not None:
            self._ignore_pvc_event(event_type, image1.to_dict())
        if image2 is not None:
            self._ignore_pvc_event(event_type, image2.to_dict())
        return image1 if image2 is None else image2

    def _v1update_image(self, uuid, src_image, tgt_image, v1images, v2images,
                        target_type):
        """
        Update the target image with the source image attributes and
        properties using the v1 and v2 Glance clients.

        All image properties will only be updated using the v2 glance client.
        Using the v1 glance client to update properties would result in any
        image properties with null values being removed since those properties
        are not synced.

        The v1 glance client must be used to update an image size attribute.
        The v2 glance client does not support updating the image size.

        This is also called to finalize the snapshot image creation process.
        When an instance is captured on the hostingOS, a snapshot image is
        created on the hostingOS in the queued state, with a powervc_uuid
        value set. When that snapshot image becomes active on PowerVC, the
        hostingOS image is updated with the latest image attributes and
        properties and it's location is set which cause the image's status to
        go active.

        This method should not be called directly. It should only be called by
        _v1update_local_image and _v1update_pvc_image.

        :param: uuid The PowerVC UUID of the image
        :param: src_image The source v1 image to use for the update
        :param: tgt_image The target v1 image to update
        :param: v1images The v1 image manager to use for updating
        :param: v2images The v2 image controller to use for patching
        :param: target_type The target image type (pvc or local)
        :returns: A tuple containing the updated v1 images. The first image
                    returned is from the v1 image update, and the second
                    image returned is from the v2 image PATCH update if any.
        """
        try:
            field_dict, patch_dict, remove_list = \
                self._get_v1image_update_fields(src_image, tgt_image)

            # If the target image is on the hostingOS, and it's status is
            # queued, and the source PowerVC image's status is active, write
            # the location to the target image so that it's status will go
            # active. This will take care of finalizing the snapshot image
            # creation process.
            if target_type == constants.LOCAL and \
                src_image.status == 'active' and \
                    tgt_image.status == 'queued':
                pvc_v2client = self._get_pvc_v2_client()
                field_dict['location'] = self._get_image_location(
                    pvc_v2client.http_client.endpoint, src_image)
            image1 = v1images.update(tgt_image, **field_dict)
            image2 = None
            if len(patch_dict) > 0:

                # Update the properties, and any large image attributes
                v2images.update(tgt_image.id, remove_props=remove_list,
                                **patch_dict)

                # refresh the v1 image to return after the udpate
                image2 = self._get_image(uuid, image1.id, image1.name,
                                         v1images, v2images)
            return image1, image2
        except CommunicationError as e:
            raise e
        except Exception as e:
            LOG.exception(_('An error occurred updating image \'%s\' for '
                            'PowerVC UUID %s: %s'), tgt_image.name, uuid, e)
            return None, None

    def _get_image_location(self, endpoint, v1image):
        """
        Return the image location for the specified image and endpoint.

        :param: endpoint The v2 glance http client endpoint
        :param: v1image The v1 image
        :returns: The image location url
        """
        location = endpoint
        if not location.endswith('/'):
            location += '/'
        location += constants.IMAGE_LOCATION_PATH
        location += v1image.id
        return location

    def _get_v1image_update_fields(self, v1src_image, v1tgt_image):
        """
        Get the attributes and properties for an image update. Filter out
        attributes and properties specified with filter constants.

        All image properties will be separated from the image attributes being
        updated. Image properties should not be updated using the v1 glance
        client. Doing so could remove any image properties with NULL values
        since those properties are not synced.

        :param: v1src_image The v1 image to pull attributes and properties from
                    to be used for a v1 and v2 image update operations.
        :param: v1tgt_image The v1 image that is being updated.
        :returns: A tuple containing with the dict containing the image
                    attribute fields to update using the v1 image update
                    operation, the dict of the image properties to update using
                    the v2 Image PATCH API, as well as the list of image
                    properties to remove.
        """
        field_dict = {}
        patch_dict = {}
        remove_list = None
        image_dict = v1src_image.to_dict()
        src_props = self._get_image_properties(image_dict)
        if src_props is not None:
            tgt_image_dict = v1tgt_image.to_dict()
            tgt_props = self._get_image_properties(tgt_image_dict, {})

            # Add image properties to be patched after filtering out specified
            # properties. Properties with NULL values have already been
            # filtered by _get_image_properties(). Also, find image properties
            # that need to be removed.
            filtered_src_props = self._filter_v1image_properties(src_props)
            filtered_tgt_props = self._filter_v1image_properties(tgt_props)

            # Get the image propeprty key sets
            src_prop_set = set(filtered_src_props)
            tgt_prop_set = set(filtered_tgt_props)

            # Find the added/update properties, and the removed properties
            # Updates are keys in both the source and the target
            updates = src_prop_set.intersection(tgt_prop_set)

            # Adds are keys in the source that are not in the target
            adds = src_prop_set.difference(tgt_prop_set)

            # Deletes are keys in the target that are not in the source.
            deletes = tgt_prop_set.difference(src_prop_set)

            # Get the adds and updates
            for key in adds:
                patch_dict[key] = filtered_src_props[key]

            # Add all update keys if their values are the same or different
            for key in updates:
                patch_dict[key] = filtered_src_props[key]

            # Find the deletes. If there are none, return None
            if deletes:
                remove_list = []
                for key in deletes:
                    remove_list.append(key)

            # Set to not purge the properties in the image when processing the
            # field_dict with the v1 glance client update. That will leave the
            # properties there after the v1 update. The v2 image update will
            # add, update, or remove the properties we care about.
            field_dict['purge_props'] = False
        else:

            # If there are no properties in the source image, force the v1
            # image update to purge all properties.
            field_dict['purge_props'] = True
        for imagekey in image_dict.keys():

            # Only update attributes in UPDATE_PARAMS if they are not in the
            # update param filter list. Also, skip over the properties
            # attribute since all properties were already added to patch_dict
            if imagekey in v1images.UPDATE_PARAMS and \
                    imagekey not in constants.IMAGE_UPDATE_PARAMS_FILTER and \
                    imagekey != 'properties':
                field_value = image_dict.get(imagekey)
                if field_value is not None:
                    if len(str(field_value)) < constants.MAX_HEADER_LEN_V1:
                        field_dict[imagekey] = field_value
                    else:
                        patch_dict[imagekey] = field_value
        return field_dict, patch_dict, remove_list

    def _filter_v1image_properties(self, props):
        """
        Filter the v1 image properties. Only update properties that are not
        None, and are not in the image update properties filter list.

        :param: props The image properties dict to filter
        :returns: Filtered image properties dict
        """
        filtered_props = {}
        if props is not None:
            for propkey in props.keys():
                propvalue = props[propkey]
                if (propkey not in constants.IMAGE_UPDATE_PROPERTIES_FILTER and
                        propvalue is not None):
                    filtered_props[propkey] = propvalue
        return filtered_props

    def _get_v1image_create_fields(self, v1image, owner, pvc_endpoint):
        """
        Get the properties for an image create.

        This only works one way right now. Creating an image is only
        done on the local hostingOS. If that changes in the future, this
        method may need some changes.

        :param: image The v1image to copy
        :param: owner The hosting OS image owner. This should be the
                    staging project or user Id
        :param: pvc_endpoint The PowerVC endpoint to use for the image
                    location
        :returns: The create_field_dict which is a dict of properties to use
                    with the v1 create function, and an update_field_dict
                    which is a dict of the properties to use with a
                    subsequent update of the newly created image.
        """
        create_field_dict = {}
        update_field_dict = {}

        # Remove large properties before processing. They will be added
        # using a v2 update
        image_dict = v1image.to_dict()
        props = self._get_image_properties(image_dict)
        if props is not None:
            update_field_dict = self._remove_large_properties(props)
            image_dict['properties'] = props
        for imagekey in image_dict.keys():
            field_value = image_dict.get(imagekey)
            if field_value is not None:
                if imagekey in v1images.CREATE_PARAMS and \
                        imagekey not in constants.IMAGE_CREATE_PARAMS_FILTER:

                    # Set the hosting OS image owner to the staging project Id
                    if imagekey == 'owner':
                        field_value = owner
                    if len(str(field_value)) < constants.MAX_HEADER_LEN_V1:
                        create_field_dict[imagekey] = field_value
                    else:
                        update_field_dict[imagekey] = field_value

        # We require a 'location' with no actual image data, or the image will
        # remain in the 'queued' state. There may be another way to do this.
        if 'location' not in create_field_dict:
            create_field_dict['location'] = self._get_image_location(
                pvc_endpoint, v1image)

        # Add the PowerVC UUID property
        props = create_field_dict.get('properties', {})
        props[consts.POWERVC_UUID_KEY] = v1image.id
        create_field_dict['properties'] = props
        return create_field_dict, update_field_dict

    def _remove_large_properties(self, properties):
        """
        Remove any properties that are too large to be processed by the v1 APIs
        and return them in a dict to the caller. After removing the single
        properties that are too large the total size of the remaining
        properties are examined. If the total properties size is too large
        to be processed by the v1 APIs, the largest properties are removed
        until the total properties size is within the size allowed. The
        properties passed in are also modified.

        :param: properties. The properties dict to remove large properties
                    from. Large properties are removed from the original
                    properties dict
        :returns: A dict containing properties that are too large to
                    be processed by v1 Image APIs
        """
        too_large_properties = {}
        property_size = {}
        if properties is not None:
            for propkey in properties.keys():
                propvalue = properties.get(propkey)
                if propvalue is not None:
                    if len(str(propvalue)) >= \
                            constants.MAX_HEADER_LEN_V1:
                        too_large_properties[propkey] = properties.pop(propkey)
                    else:
                        property_size[propkey] = len(str(propvalue))

            # The properties that are too large for the v1 API have been
            # removed, but it is still possible that the resulting properties
            # are too large. If that is the case, remove the largest properties
            # until the total properties size is less than the
            # MAX_HEADER_LEN_V1 value.
            if len(str(properties)) >= constants.MAX_HEADER_LEN_V1:
                smaller_props = {}
                for propkey, propsize in sorted(property_size.iteritems(),
                                                key=itemgetter(1)):
                    if propsize and properties.get(propkey) is not None:
                        smaller_props[propkey] = properties.get(propkey)
                        if len(str(smaller_props)) >= \
                                constants.MAX_HEADER_LEN_V1:
                            too_large_properties[propkey] = \
                                properties.pop(propkey)
        return too_large_properties

    def _v2update_local_image(self, uuid, src_image, tgt_image, v1images,
                              v2images):
        """
        Update the local hostingOS target image with the source image
        attributes and properties using the v2 Glance client.

        Also, set to ignore any image update events that may be generated by
        the image update operation here.

        :param: uuid The PowerVC UUID of the image
        :param: src_image The source PowerVC v1 image to use for the update
        :param: tgt_image The target local hostingOS v1 image to update
        :param: v1images The v1 image manager to use for getting image
        :param: v2images The v2 image controller to use for updating
        :returns: The updated v1 image, or None if the update was not
                    successful.
        """
        v1image = self._v2update_image(uuid, src_image, tgt_image, v1images,
                                       v2images, constants.LOCAL)

        # Set to ignore any update events generated by updating the image
        if v1image is not None:
            self._ignore_local_event(constants.IMAGE_EVENT_TYPE_UPDATE,
                                     v1image.to_dict())
        return v1image

    def _v2update_pvc_image(self, uuid, src_image, tgt_image, v1images,
                            v2images):
        """
        Update the PowerVC target image with the source image attributes and
        properties using the v2 Glance client.

        Also, set to ignore any image update events that may be generated by
        the image update operation here.

        :param: uuid The PowerVC UUID of the image
        :param: src_image The source local hostingOS v1 image to use for the
                            update
        :param: tgt_image The target PowerVC image to update
        :param: v1images The v1 image manager to use for getting image
        :param: v2images The v2 image controller to use for updating
        :returns: The updated v1 image, or None if the update was not
                    successful.
        """
        v1image = self._v2update_image(uuid, src_image, tgt_image, v1images,
                                       v2images, constants.POWER_VC)

        # Set to ignore any update events generated by updating the image
        if v1image is not None:
            self._ignore_pvc_event(constants.IMAGE_EVENT_TYPE_UPDATE,
                                   v1image.to_dict())
        return v1image

    def _v2update_image(self, uuid, src_image, tgt_image, v1images, v2images,
                        target_type):
        """
        Update the target image with the source image attributes and properties
        using the v2 Glance client.

        This cannot be called to finalize the snapshot image creation process
        Do not use this v2 update to activate an image. Use the v1 update to
        activate images.

        This method should not be called directly. It should only be called by
        _v2update_local_image and _v2update_pvc_image.

        :param: uuid The PowerVC UUID of the image
        :param: src_image The source v1 image to use for the update
        :param: tgt_image The target v1 image to update
        :param: v1images The v1 image manager to use for getting image
        :param: v2images The v2 image controller to use for updating
        :param: target_type The target image type (pvc or local)
        :returns: The updated v1 image, or None if the update was not
                    successful.
        """
        try:
            attr_dict, remove_list = self._get_v2image_update_fields(src_image,
                                                                     tgt_image)
            image = v2images.update(tgt_image.id, remove_props=remove_list,
                                    **attr_dict)

            # Get the v1 image to return after the update
            v1image = self._get_image(uuid, image['id'], image['name'],
                                      v1images, v2images)
            return v1image
        except CommunicationError as e:
            raise e
        except Exception as e:
            LOG.exception(_('An error occurred updating image \'%s\' for '
                            'PowerVC UUID %s: %s'), tgt_image.name, uuid, e)
            return None

    def _get_v2image_update_fields(self, src_image, tgt_image):
        """
        Get the attributes and properties for a v2 image update. Filter
        out attributes and properties specified with filter constants. Also
        flatten out the properties, converting them into v2 image attibutes.

        :param: src_image The v1 image to pull properties from to be used
                    for a v2 image update operation.
        :param: tgt_image The v1 image to derived removed properties from to be
                    used for a v2 image update operation.
        :returns: A tuple containing with the dict containing the properties
                    that are added or modified, and the list of the property
                    names that are to be removed during the v2 image update
                    operation. If no properties are to be deleted, the
                    remove list will be None
        """

        # Filter out any attributes that should not be updated
        v1src_image_dict = \
            self._filter_v1image_for_v2_update(src_image.to_dict())
        v1tgt_image_dict = \
            self._filter_v1image_for_v2_update(tgt_image.to_dict())

        # Convert v1 image to v2 image
        v2src_image_dict = self._convert_v1_to_v2(v1src_image_dict)
        v2tgt_image_dict = self._convert_v1_to_v2(v1tgt_image_dict)

        # Get the image key sets
        src_image_set = set(v2src_image_dict)
        tgt_image_set = set(v2tgt_image_dict)

        # Find the added/update attributes, and the removed attributes
        # Updates are keys in both the source and the target
        updates = src_image_set.intersection(tgt_image_set)

        # Adds are keys in the source that are not in the target
        adds = src_image_set.difference(tgt_image_set)

        # Deletes are keys in the target that are not in the source.
        deletes = tgt_image_set.difference(src_image_set)

        # Get the adds and updates
        add_update_dict = {}
        for key in adds:
            add_update_dict[key] = v2src_image_dict[key]

        # Add all update keys if their values are the same or different
        for key in updates:
            add_update_dict[key] = v2src_image_dict[key]

        # Find the deletes. If there are none, return None
        if deletes:
            remove_list = []
            for key in deletes:
                remove_list.append(key)
        else:
            remove_list = None

        return add_update_dict, remove_list

    def _filter_v1image_for_v2_update(self, v1image_dict):
        """
        Filter the v1 image dict. for a v2 update. Only update properties that
        are not None, and are in UPDATE_PARAMS, and that are not in the v2
        image params filter list, or the image update properties filter list.

        :param: v1image_dict The v1 image dict to filter
        :returns: A filtered v1 image dict
        """
        filtered_image = {}

        # Process the image attributes we care about
        for imagekey in v1image_dict.keys():

            # Only update attributes in UPDATE_PARAMS if they are not in the
            # update param filter list. Also, skip over the properties
            # attribute and process those separately.
            if imagekey in v1images.UPDATE_PARAMS and \
                imagekey not in constants.v2IMAGE_UPDATE_PARAMS_FILTER and \
                    imagekey != 'properties':
                field_value = v1image_dict.get(imagekey)
                if field_value is not None:
                    filtered_image[imagekey] = field_value

        # Process the image properties
        props = self._get_image_properties(v1image_dict)
        if props is not None:
            for propkey in props.keys():
                if propkey in constants.IMAGE_UPDATE_PROPERTIES_FILTER or \
                        props[propkey] is None:
                    props.pop(propkey)
            filtered_image['properties'] = props
        return filtered_image

    def _convert_v1_to_v2(self, v1image_dict):
        """
        Convert a v1 image update dict to a v2 image update dict. No attribute
        or property filtering is done.

        :returns: The v2 image dict representation of the specified v1 image
                    to be used for a v2 image update
        """
        v2image_dict = {}
        for imagekey in v1image_dict.keys():

            # The v1 is_public attribute should be converted to the v2
            # visibility attribute, and image properties are converted to image
            # attributes
            field_value = v1image_dict.get(imagekey)
            if imagekey == 'is_public':
                v2image_dict['visibility'] = \
                    'public' if field_value else 'private'
            elif imagekey == 'properties':
                props = field_value
                if props is not None:
                    for prop_key in props.keys():
                        v2image_dict[prop_key] = props[prop_key]
            else:
                v2image_dict[imagekey] = field_value
        return v2image_dict

    def _get_local_images_and_ids(self, v1images):
        """
        Get the local hosting OS v1 images, and return in a dict with the
        PowerVC UUIDs as the keys.

        Also populate the ids_dict which is a map of the PowerVC image UUIDs to
        the local hosting OS image UUIDs.

        :param: v1images The image manager used to obtain images from the
                    local hosting OS v1 glance client
        :returns: A dict of the local hosting OS images with the PowerVC UUID
                    as the key and the image as the value
        """
        local_images = {}

        # The v1 API on the hosting OS filters the images with is_public = True
        # Get the public and non-public images.
        params1 = self._get_limit_filter_params()
        params2 = self._get_limit_filter_params()
        params2 = self._get_not_ispublic_filter_params(params2)
        for image in itertools.chain(v1images.list(**params1),
                                     v1images.list(**params2)):

            # Save image in dict if it is from PowerVC
            if consts.POWERVC_UUID_KEY in image.properties.keys():

                # If the image status is not active, only save the image if
                # it's pvc_id is not already known. Some snapshot images
                # which are not 'active' can contain an incorrect pvc_id
                # value. Don't add those images to the list if the image for
                # that pvc_id was already found.
                pvc_id = image.properties[consts.POWERVC_UUID_KEY]
                if image.status != 'active' and pvc_id in local_images.keys():
                    continue
                local_images[pvc_id] = image
                self.ids_dict[pvc_id] = image.id
        return local_images

    def _get_pvc_images(self, v1images):
        """
        Get the PowerVC v1 images, and return in a dict with the PowerVC UUIDs
        as the keys.

        Only the images associated with our Storage Connectivity Group will be
        returned.

        If our Storage Connectivity Group cannot be found at this time, a
        StorageConnectivityGroupNotFound exception is raised.

        :param: v1images The image manager used to obtain images from the
                    PowerVC v1 glance client
        :returns: A dict with the PowerVC UUID as the key and the image as the
                    value. Only images for our Storage Connectivity Group will
                    be returned
        """
        pvc_images = {}

        # Get our SCG if specified, or None
        try:
            self.our_scg_list = self._get_our_scg_list()
        except StorageConnectivityGroupNotFound as e:

            # If the our Storage Connectivity Groups is not found on PowerVC,
            # log the error, and raise the exception to end the startup or
            # periodic sync operation. The startup or periodic sync will go
            # into error retry mode managed by the ImageSyncController until
            # the Storage Connectivity Group is found. If the Storage
            # Connectivity Group goes away during a periodic sync, update and
            # delete event processing will continue to work, but periodic sync
            # will not work again until the Storage Connectivity Group is
            # present. If the Storage Connectivity Group cannot be found during
            # the startup sync, events will not be processed since the startup
            # sync did not finish successfully.
            LOG.error(_('The specified PowerVC Storage Connectivity Group was '
                        'not found. No PowerVC images are available.'))
            raise e

        # We allow testing with our_scg set to None. We just have to comment
        # out the check in __init__() and we can run with no SCG specified for
        # testing purposes. In that case, work with all PowerVC images.
        multi_scg_image_ids = set()
        for scg in self.our_scg_list:
            if scg is not None:
                LOG.info(_('Getting accessible PowerVC images for Storage '
                           'Connectivity Group \'%s\'...'),
                         scg.display_name)

                # Get all of the images for our SCG. If an error occurs, an
                # exception will be raised, the image sync operation will fail,
                # and the sync operation will be retried later.
                scg_image_ids = \
                    utils.get_utils().get_scg_image_ids(scg.id)

                # If no SCG image ids were found, return now.
                # There are no images to retrieve
                if not scg_image_ids:
                    LOG.warning(_('The specified PowerVC Storage Connectivity '
                                  'Group \'%s\' has no images. No PowerVC '
                                  'images are available.'),
                                scg.display_name)
                else:
                    multi_scg_image_ids.update(scg_image_ids)
                    LOG.info(_('Found %s images for Storage Connectivity '
                               'Group \'%s\''), str(len(scg_image_ids)),
                             scg.display_name)

        # The v1 API on PowerVC does not filter the images with is_public =
        # True at this time. Get the public and non-public images. This does
        # not seem to be required for PowerVC, but that could change
        params1 = self._get_limit_filter_params()
        params2 = self._get_limit_filter_params()
        params2 = self._get_not_ispublic_filter_params(params2)
        for image in itertools.chain(v1images.list(**params1),
                                     v1images.list(**params2)):

            # If this image is accessible, add it to the dict
            if not multi_scg_image_ids:
                pvc_images[image.id] = image
            else:
                if image.id in multi_scg_image_ids:
                    pvc_images[image.id] = image
                else:

                    # If the we knew about the image before this, and it is now
                    # being removed due to it not being in the SCG we should
                    # log a warning so the user knows why we are deleting the
                    # image from the hosting OS. If we knew about the image
                    # before, it's UUID would be in the updated_at dict keys.
                    if image.id in self.pvc_updated_at.keys():
                        LOG.warning(_('Image \'%s\' is no longer accessible on'
                                      ' Storage Connectivity Group. It '
                                      'will be removed from the hosting OS.'),
                                    image.name)
                    else:
                        LOG.debug(_('Image \'%s\' is not accessible on Storage'
                                    ' Connectivity Group'), image.name)
        return pvc_images

    def _dump_image_info(self, local_images, pvc_images):
        """
        Dump out the current image information

        :param: local_images A dict of the local hostingOS images
        :param: pvc_images A dict of the PowerVC images
        """
        # Dump the hostingOS image dict
        LOG.debug(_('Local hosting OS image dict: %s'), str(local_images))
        # Dump the PowerVC image dict
        LOG.debug(_('PowerVC image dict: %s'), str(pvc_images))
        # Dump the image ids dict
        LOG.debug(_('Image ids dict: %s'), str(self.ids_dict))
        # Dump the local update_at dict
        LOG.debug(_('Local hosting OS updated_at dict: %s'),
                  str(self.local_updated_at))
        # Dump the PowerVC update_at dict
        LOG.debug(_('PowerVC updated_at dict: %s'), str(self.pvc_updated_at))

    def _local_image_updated(self, uuid, v1image):
        """
        Test whether the local hosting OS image has been updated.

        :param: uuid The PowerVC UUID of the image
        :param: v1image The v1 representation of the image
        returns True if the image has been updated or if there was a problem
                        making the determination.
        """
        if uuid not in self.local_updated_at.keys():
            return True
        past = self.local_updated_at[uuid]
        cur = v1image.updated_at
        if past and cur:
            try:
                past_updated_datetime = self._get_v1_datetime(past)
                cur_updated_datetime = self._get_v1_datetime(cur)
                return past_updated_datetime != cur_updated_datetime
            except Exception as e:
                LOG.exception(_('An error occurred determining image update '
                                'status for %s: %s'), v1image.name, e)
                return True
        else:
            return True

    def _pvc_image_updated(self, uuid, v1image):
        """
        Test whether the PowerVC image has been updated.

        :param: uuid The PowerVC UUID of the image
        :param: v1image The v1 representation of the image
        returns True if the image has been updated or if there was a problem
                        making the determination.
        """
        if uuid not in self.pvc_updated_at.keys():
            return True
        past = self.pvc_updated_at[uuid]
        cur = v1image.updated_at
        if past and cur:
            try:
                past_updated_datetime = self._get_v1_datetime(past)
                cur_updated_datetime = self._get_v1_datetime(cur)
                return past_updated_datetime != cur_updated_datetime
            except Exception as e:
                LOG.exception(_('An error occurred determining image update '
                                'status for %s: %s'), v1image.name, e)
                return True
        else:
            return True

    def _get_v1_datetime(self, v1timestamp):
        """
        Get the datetime for a v1 timestamp formatted string. If the timestamp
        has decimal seconds, truncate it.

        :param: v1timestamp The v1 formatted timestamp string
        """
        if '.' in v1timestamp:
            v1timestamp = v1timestamp.split('.')[0]
        return timeutils.parse_strtime(v1timestamp,
                                       constants.IMAGE_TIMESTAMP_FORMAT)

    def _add_startup_sync_to_queue(self):
        """
        Add an event to the event queue to start the startup sync operation.
        """
        event = {}
        event[constants.EVENT_TYPE] = constants.STARTUP_SCAN_EVENT
        LOG.debug(_('Adding startup sync event to event queue: %s'),
                  str(event))
        self.event_queue.put(event)

    def _add_periodic_sync_to_queue(self):
        """
        Add an event to the event queue to start the periodic sync operation.
        This synchronizes the periodic scans with the image event processing.
        """
        event = {}
        event[constants.EVENT_TYPE] = constants.PERIODIC_SCAN_EVENT
        LOG.debug(_('Adding periodic sync event to event queue: %s'),
                  str(event))
        self.event_queue.put(event)

    def _prepare_for_image_events(self):
        """
        Prepare for image events processing. This should be called after the
        startup sync is successful, and then after every periodic sync
        completes to make sure the image event handlers are running.

        Expired event tuples are also cleard from the local and PowerVC events
        to ignore lists.
        """

        # Remove expired event tuples from the event to ignore dicts
        self._purge_expired_local_events_to_ignore()
        self._purge_expired_pvc_events_to_ignore()

        # Start the image notification event handlers to process changes if
        # they are not currently running
        self._start_local_event_handler()
        self._start_pvc_event_handler()

    def _start_local_event_handler(self):
        """Start the local hosting OS image notification event handler if it's
        not already running.

        The event handler is not started if the qpid_hostname is not specified
        in the configuration.
        """

        # If already running, exit
        if self.local_event_handler_running:
            return

        LOG.debug("Enter _start_local_event_handler method")

        trans = transport.get_transport(config.AMQP_OPENSTACK_CONF)
        targets = [
            target.Target(exchange=constants.IMAGE_EVENT_EXCHANGE,
                          topic=constants.IMAGE_EVENT_TOPIC)
        ]
        endpoint = messaging.NotificationEndpoint(log=LOG)

        endpoint.register_handler(constants.IMAGE_EVENT_TYPE_ALL,
                                  self._local_image_notifications)

        endpoints = [
            endpoint,
        ]

        LOG.debug("Starting to listen...... ")

        local_glance_listener = listener.\
            get_notification_listener(trans, targets, endpoints,
                                      allow_requeue=False)
        messaging.start_notification_listener(local_glance_listener)

        LOG.debug("Exit _start_local_event_handler method")

        self.local_event_handler_running = True

    def _start_pvc_event_handler(self):
        """Start the PowerVC image notification event handler if not already
        running.

        The event handler is not started if the powervc_qpid_hostname is
        not specified in the configuration.
        """

        # If already running, exit
        if self.pvc_event_handler_running:
            return

        LOG.debug("Enter _start_pvc_event_handler method")

        trans = transport.get_transport(config.AMQP_POWERVC_CONF)
        targets = [
            target.Target(exchange=constants.IMAGE_EVENT_EXCHANGE,
                          topic=constants.IMAGE_EVENT_TOPIC)
        ]
        endpoint = messaging.NotificationEndpoint(log=LOG)

        endpoint.register_handler(constants.IMAGE_EVENT_TYPE_ALL,
                                  self._pvc_image_notifications)

        endpoints = [
            endpoint,
        ]

        LOG.debug("Starting to listen...... ")

        pvc_glance_listener = listener.\
            get_notification_listener(trans, targets, endpoints,
                                      allow_requeue=False)
        messaging.start_notification_listener(pvc_glance_listener)

        LOG.debug("Exit _start_pvc_event_handler method")

        self.pvc_event_handler_running = True

    def _process_event_queue(self):
        """
        Process the event queue. When the image notification event handlers are
        called, they place the image events on the event queue to be processed
        synchronously here. When the sync_images method is called periodically,
        it too places an event on the event queue for running the periodic
        scan. This provides synchronization between the event processing and
        the periodic scan.

        The event queue events are a dict made up of the event type, the
        context, and the message.
        """
        while True:
            event = self.event_queue.get()
            try:
                LOG.debug(_('local events to ignore: %s'),
                          str(self.local_events_to_ignore_dict))
                LOG.debug(_('pvc events to ignore: %s'),
                          str(self.pvc_events_to_ignore_dict))
                context = event.get(constants.EVENT_CONTEXT)
                event_type = event.get(constants.EVENT_TYPE)
                ctxt = event.get(constants.REAL_EVENT_CONTEXT)
                real_type = event.get(constants.REAL_EVENT_TYPE)
                payload = event.get(constants.EVENT_PAYLOAD)
                if event_type == constants.LOCAL_IMAGE_EVENT:
                    LOG.debug(_('Processing a local hostingOS image event on '
                                'the event queue: %s'), str(event))
                    self.\
                        _handle_local_image_notifications(context=context,
                                                          ctxt=ctxt,
                                                          event_type=real_type,
                                                          payload=payload,
                                                          )
                elif event_type == constants.PVC_IMAGE_EVENT:
                    LOG.debug(_('Processing a PowerVC image event on '
                                'the event queue: %s'), str(event))
                    self._handle_pvc_image_notifications(context=context,
                                                         ctxt=ctxt,
                                                         event_type=real_type,
                                                         payload=payload,
                                                         )
                elif event_type == constants.PERIODIC_SCAN_EVENT:
                    LOG.debug(_('Processing a periodic sync event on '
                                'the event queue: %s'), str(event))
                    self.periodic_sync()
                elif event_type == constants.STARTUP_SCAN_EVENT:
                    LOG.debug(_('Processing a startup sync event on '
                                'the event queue: %s'), str(event))
                    self.startup_sync()
                else:
                    LOG.debug(_('An unknown event type was found on the event '
                                'queue: %s'), str(event))
            except Exception as e:
                LOG.exception(_('An error occurred processing the image event '
                                'from the event queue: %s'), e)
            finally:
                self.event_queue.task_done()

    def _local_image_notifications(self,
                                   context=None,
                                   ctxt=None,
                                   event_type=None,
                                   payload=None):
        """Place the local image event on the event queue for processing.

        :param: context The security context
        :param: ctxt message context
        :param: event_type message event type
        :param: payload The AMQP message sent from OpenStack (dictionary)
        """
        event = {}
        event[constants.EVENT_TYPE] = constants.LOCAL_IMAGE_EVENT
        event[constants.EVENT_CONTEXT] = context
        event[constants.REAL_EVENT_CONTEXT] = ctxt
        event[constants.REAL_EVENT_TYPE] = event_type
        event[constants.EVENT_PAYLOAD] = payload

        LOG.debug(_('Adding local image event to event queue: %s'), str(event))
        self.event_queue.put(event)

    def _handle_local_image_notifications(self,
                                          context=None,
                                          ctxt=None,
                                          event_type=None,
                                          payload=None,
                                          ):
        """Handle image notification events received from the local hosting OS.
        Only handle update, and delete event types. The activate event
        is processed, but only to add the new image to the update_at dict.

        There is a scheme in place to keep events from ping-ponging back
        and forth. If we are processing an event, we add the expected
        event from PowerVC to the ignore list. Then when that event arrives
        from PowerVC because of this update we will ignore it.

        :param: context The security context
        :param: ctxt message context
        :param: event_type message event type
        :param: payload The AMQP message sent from OpenStack (dictionary)
        """

        v1image_dict = payload
        if event_type == constants.IMAGE_EVENT_TYPE_UPDATE:
            self._process_local_image_update_event(v1image_dict)
        elif event_type == constants.IMAGE_EVENT_TYPE_DELETE:
            self._process_local_image_delete_event(v1image_dict)
        elif event_type == constants.IMAGE_EVENT_TYPE_ACTIVATE:
            self._process_local_image_activate_event(v1image_dict)
        elif event_type == constants.IMAGE_EVENT_TYPE_CREATE:
            self._process_local_image_create_event(v1image_dict)
        else:
            LOG.debug(_("Did not process event: type:'%(event_type)s' type, "
                        "payload:'%(payload)s'"
                        )
                      % (event_type, payload)
                      )

    def _process_local_image_update_event(self, v1image_dict):
        """
        Process a local hostingOS image update event.

        :param: v1image_dict The updated v1 image dict
        """
        LOG.debug(_('Local hosting OS update event received: %s'),
                  str(v1image_dict))

        # Only process PowerVC images
        event_type = constants.IMAGE_EVENT_TYPE_UPDATE
        local_id = v1image_dict.get('id')
        local_name = v1image_dict.get('name')
        props = self._get_image_properties(v1image_dict)
        if props and consts.POWERVC_UUID_KEY in props.keys():

            # Determine if we should ignore this event
            evt = self._get_event(constants.LOCAL, event_type, v1image_dict)
            if self._get_local_event_to_ignore(evt) is not None:
                LOG.debug(_('Ignoring event %s for %s'), str(evt), local_name)
                return
            else:
                LOG.debug(_('Processing event %s for %s'), str(evt),
                          local_name)

            # Also ignore all image update events for images that are not
            # active. Those would most likely be 'queued' images created
            # during the instance capture process. There should be no
            # corresponding image to process on the PowerVC yet.
            if v1image_dict.get('status') != 'active':
                LOG.debug(_('Ignoring image update event for \'%s\' because '
                            'the image is not active.'), local_name)
                return

            # Process the event
            pvc_id = props.get(consts.POWERVC_UUID_KEY)
            try:
                local_v1client = self._get_local_v1_client()
                v1local_images = local_v1client.images
                local_v2client = self._get_local_v2_client()
                v2local_images = local_v2client.images
                local_image = self._get_image(pvc_id, local_id, local_name,
                                              v1local_images, v2local_images)
                if local_image is None:
                    LOG.debug(_('The local image \'%s\' with PowerVC UUID %s '
                                'was not update synchronized because it could '
                                'not be found.'), local_name, pvc_id)
                    return

                # Try processing the local image update
                LOG.info(_('Performing update sync of image \'%s\' from the '
                           'local hosting OS to PowerVC after an image update '
                           'event'), local_image.name)

                # Update sync local image to PowerVC
                pvc_v1client = self._get_pvc_v1_client()
                v1pvc_images = pvc_v1client.images
                pvc_v2client = self._get_pvc_v2_client()
                v2pvc_images = pvc_v2client.images
                pvc_image = self._get_image(pvc_id, pvc_id, local_name,
                                            v1pvc_images, v2pvc_images)

                # Update the image if it is in PowerVC
                if pvc_image is None:
                    LOG.info(_('The PowerVC image \'%s\' with UUID %s was not '
                               'updated because it could not be found.'),
                             local_image.name, pvc_id)
                    return

                # If the PowerVC image has changed, do not update it. This
                # only happens if we lost an event. In that case we need to
                # wait for the periodic scan to merge changes.
                if self._pvc_image_updated(pvc_id, pvc_image):
                    LOG.info(_('The PowerVC image \'%s\' for PowerVC UUID %s '
                               'has changed. Changes between the local '
                               'hostingOS and the PowerVC image will be '
                               'merged during the next periodic scan.'),
                             pvc_image.name, pvc_id)
                    return

                # Perform the image update to PowerVC
                image = self._update_pvc_image(pvc_id, local_image, pvc_image,
                                               v1pvc_images, v2pvc_images)
                if image is None:
                    LOG.error(_('PowerVC image \'%s\' with UUID %s was not '
                                'updated after an image update event.'),
                              pvc_image.name, pvc_id)
                    return

                # NOTE: Do not reset the updated_at values until after both
                # the local hostingOS image and PowerVC image are successfully
                # updated.

                # Since the hostingOS image was updated, update the entry
                # in the update_at dict so the change isn't processed
                # during a periodic scan
                if pvc_id in self.local_updated_at.keys():
                    self.local_updated_at[pvc_id] = local_image.updated_at

                # Attempt to update the entry for this image in the PowerVC
                # updated_at dict so that it is not processed during a
                # periodic sync due to this update.
                if pvc_id in self.pvc_updated_at.keys():
                    self.pvc_updated_at[pvc_id] = image.updated_at

                # Set the new master image
                self.master_image[pvc_id] = image
                LOG.info(_('Completed update sync of image \'%s\' from the '
                           'local hosting OS to PowerVC after an image update '
                           'event'), local_image.name)
            except Exception as e:
                LOG.exception(_('An error occurred processing the local '
                                'hosting OS image update event: %s'), e)

    def _process_local_image_delete_event(self, v1image_dict):
        """
        Process a local hostingOS image delete event.

        :param: v1image_dict The deleted v1 image dict
        """
        LOG.debug(_('Local hosting OS delete event received: %s'),
                  str(v1image_dict))

        def clean_up(uuid):
            """
            Clean up the update_at and master_image copy for the deleted image
            with the specified idenfitier. Also clean up the ids_dict.

            :param: uuid The PowerVC UUID of the deleted image
            """
            if uuid in self.pvc_updated_at.keys():
                self.pvc_updated_at.pop(uuid)
            if uuid in self.master_image.keys():
                self.master_image.pop(uuid)
            if uuid in self.ids_dict.keys():
                self.ids_dict.pop(uuid)

            # Since the hostingOS image was deleted, remove the entry from
            # the update_at dict so the change isn't processed during a
            # periodic scan. Only do this if the PowerVC image is also
            # deleted, or the PowerVC image will not be deleted during
            # the next periodic scan.
            if uuid in self.local_updated_at.keys():
                self.local_updated_at.pop(uuid)

        # Only process PowerVC images
        event_type = constants.IMAGE_EVENT_TYPE_DELETE
        local_name = v1image_dict.get('name')
        props = self._get_image_properties(v1image_dict)
        if props and consts.POWERVC_UUID_KEY in props.keys():

            # Determine if we should ignore this event
            evt = self._get_event(constants.LOCAL, event_type, v1image_dict)
            if self._get_local_event_to_ignore(evt) is not None:
                LOG.debug(_('Ignoring event %s for %s'), str(evt), local_name)
                return
            else:
                LOG.debug(_('Processing event %s for %s'), str(evt),
                          local_name)

            # Also ignore all image delete events for images that are not
            # active. Those would most likely be 'queued' images created
            # during the instance capture process. There should be no
            # corresponding image to process on the PowerVC yet.
            if v1image_dict.get('status') != 'active':
                LOG.debug(_('Ignoring image delete event for \'%s\' because '
                            'the image is not active.'), local_name)
                return

            # Process the event
            pvc_id = props.get(consts.POWERVC_UUID_KEY)
            try:

                # Try processing the local image delete
                LOG.info(_('Performing delete sync of image \'%s\' from the '
                           'local hosting OS to PowerVC after an image delete '
                           'event'), local_name)

                # Delete sync local image to PowerVC
                pvc_v1client = self._get_pvc_v1_client()
                v1pvc_images = pvc_v1client.images
                pvc_v2client = self._get_pvc_v2_client()
                v2pvc_images = pvc_v2client.images
                pvc_image = self._get_image(pvc_id, pvc_id, local_name,
                                            v1pvc_images, v2pvc_images)

                # Delete the image if it is in PowerVC
                if pvc_image is None:
                    LOG.info(_('The PowerVC image \'%s\' with UUID %s was not '
                               'deleted because it could not be found.'),
                             local_name, pvc_id)

                    # Since the PowerVC image was deleted, remove the entry
                    # from the update_at dict so the change isn't processed
                    # during a periodic scan. Also delete the master_image
                    # copy.
                    clean_up(pvc_id)
                    return

                # Perform the image delete to PowerVC
                image = self._delete_pvc_image(pvc_id, pvc_image, v1pvc_images)
                if image is None:
                    LOG.error(_('PowerVC image \'%s\' with UUID %s could not '
                                'be deleted after an image delete event.'),
                              pvc_image.name, pvc_id)
                    return

                # Add delete to event ignore list so we don't process it
                # again try to delete the local hosting OS image again.
                # Only do this if event handling is running.
                self._ignore_pvc_event(event_type, image.to_dict())

                # Since the PowerVC image was deleted, remove the entry
                # from the update_at dict so the change isn't processed
                # during a periodic scan Also delete the master_image
                # copy.
                clean_up(pvc_id)
                LOG.info(_('Completed delete sync of image \'%s\' from the '
                           'local hosting OS to PowerVC after an image delete '
                           'event'), local_name)
            except Exception as e:
                LOG.exception(_('An error occurred processing the local '
                                'hosting OS image delete event: %s'), e)

    def _process_local_image_activate_event(self, v1image_dict):
        """
        Process a local hostingOS image activate event. All that is required
        is to add the new image to the update_at dict and make sure an entry is
        in the ids_dict to map the image UUIDs.

        :param: v1image_dict The activated v1 image dict
        """
        LOG.debug(_('Local hosting OS activate event received: %s'),
                  str(v1image_dict))

        # Only process PowerVC images
        local_name = v1image_dict.get('name')
        props = self._get_image_properties(v1image_dict)
        if props and consts.POWERVC_UUID_KEY in props.keys():

            # Determine if we should ignore this event
            evt = self._get_event(constants.LOCAL,
                                  constants.IMAGE_EVENT_TYPE_ACTIVATE,
                                  v1image_dict)
            if self._get_local_event_to_ignore(evt) is not None:
                LOG.debug(_('Ignoring event %s for %s'), str(evt), local_name)
                return
            else:
                LOG.debug(_('Processing event %s for %s'), str(evt),
                          local_name)

            # Add the new image to the updated_at dict so this add isn't
            # processed during a periodic sync. This may already be there,
            # but go ahead and update it anyway. The only way these can
            # occur is for a new image that was created by a sync operation,
            # or by an update of a snapshot image, setting the location
            # value to activate it. In both cases, the PowerVC image is
            # already there. There is no real add here to process here.
            pvc_id = props.get(consts.POWERVC_UUID_KEY)
            self.local_updated_at[pvc_id] = v1image_dict.get('updated_at')

            # Add an entry into the ids_dict
            self.ids_dict[pvc_id] = v1image_dict.get('id')
            LOG.debug(_('Completed processing of image activate event for '
                        'image \'%s\' for PowerVC UUID %s'), local_name,
                      pvc_id)

    def _process_local_image_create_event(self, v1image_dict):
        """
        Process a local hostingOS image create event. All that is required
        is to add the new image to the update_at dict and make sure an entry is
        in the ids_dict to map the image UUIDs. We will get this event on the
        local hostingOS during an instance capture.

        :param: v1image_dict The created v1 image dict
        """
        LOG.debug(_('Local hosting OS create event received: %s'),
                  str(v1image_dict))

        # Only process PowerVC images
        local_name = v1image_dict.get('name')
        props = self._get_image_properties(v1image_dict)
        if props and consts.POWERVC_UUID_KEY in props.keys():

            # Determine if we should ignore this event
            evt = self._get_event(constants.LOCAL,
                                  constants.IMAGE_EVENT_TYPE_CREATE,
                                  v1image_dict)
            if self._get_local_event_to_ignore(evt) is not None:
                LOG.debug(_('Ignoring event %s for %s'), str(evt), local_name)
                return
            else:
                LOG.debug(_('Processing event %s for %s'), str(evt),
                          local_name)

            # Add the new image to the updated_at dict so this add isn't
            # processed during a periodic sync. This may already be there,
            # but go ahead and update it anyway. The only way these can
            # occur is for a new image that was created by a sync operation,
            # or by an update of a snapshot image, setting the location
            # value to activate it. In both cases, the PowerVC image is
            # already there. There is no real add here to process here.
            pvc_id = props.get(consts.POWERVC_UUID_KEY)

            # If the pvc_id is already known, this is probably the initial
            # snapshot image from an instance capture. It will contain the
            # pvc_id from the original image used to create the instance
            # being captured. In that case, don't do the rest of the
            # processing here.
            if pvc_id not in self.local_updated_at.keys():
                self.local_updated_at[pvc_id] = v1image_dict.get('updated_at')

                # Add an entry into the ids_dict
                self.ids_dict[pvc_id] = v1image_dict.get('id')
                LOG.debug(_('Completed processing of image create event for '
                            'image %s for PowerVC UUID %s'), local_name,
                          pvc_id)
            else:
                LOG.debug(_('Did not process image create event for image '
                            '\'%s\'. The PowerVC UUID is not known.'),
                          local_name)

    def _pvc_image_notifications(self,
                                 context=None,
                                 ctxt=None,
                                 event_type=None,
                                 payload=None):
        """Place the PowerVC image event on the event queue for processing.

        :param: context The security context
        :param: ctxt message context
        :param: event_type message event type
        :param: payload The AMQP message sent from OpenStack (dictionary)
        """

        event = {}
        event[constants.EVENT_TYPE] = constants.PVC_IMAGE_EVENT
        event[constants.EVENT_CONTEXT] = context
        event[constants.REAL_EVENT_CONTEXT] = ctxt
        event[constants.REAL_EVENT_TYPE] = event_type
        event[constants.EVENT_PAYLOAD] = payload

        LOG.debug(_('Adding PowerVC image event to event queue: %s'),
                  str(event))
        self.event_queue.put(event)

    def _handle_pvc_image_notifications(self,
                                        context=None,
                                        ctxt=None,
                                        event_type=None,
                                        payload=None,
                                        ):
        """Handle image notification events received from PowerVC.
        Only handle activate, update, and delete event types.

        There is a scheme in place to keep events from ping-ponging back
        and forth. If we are processing an event, we add the expected
        event from the local hosting OS to the ignore list. Then when
        that event arrives from the hosting OS because of this update we
        will ignore it.

        :param: context The security context
        :param: ctxt message context
        :param: event_type message event type
        :param: payload The AMQP message sent from OpenStack (dictionary)
        """

        v1image_dict = payload
        if event_type == constants.IMAGE_EVENT_TYPE_UPDATE:
            self._process_pvc_image_update_event(v1image_dict)
        elif event_type == constants.IMAGE_EVENT_TYPE_DELETE:
            self._process_pvc_image_delete_event(v1image_dict)
        elif event_type == constants.IMAGE_EVENT_TYPE_ACTIVATE:
            self._process_pvc_image_activate_event(v1image_dict)
        else:
            LOG.debug(_("Did not process event: type:'%(event_type)s' type, "
                        "payload:'%(payload)s'"
                        )
                      % (event_type, payload)
                      )

    def _process_pvc_image_update_event(self, v1image_dict):
        """
        Process a PowerVC image update event.

        :param: v1image_dict The updated v1 image dict
        """
        LOG.debug(_('PowerVC update event received: %s'), str(v1image_dict))
        event_type = constants.IMAGE_EVENT_TYPE_UPDATE
        pvc_id = v1image_dict.get('id')
        pvc_name = v1image_dict.get('name')

        # Determine if we should ignore this event
        evt = self._get_event(constants.POWER_VC, event_type, v1image_dict)
        if self._get_pvc_event_to_ignore(evt) is not None:
            LOG.debug(_('Ignoring event %s for %s'), str(evt), pvc_name)
            return
        else:
            LOG.debug(_('Processing event %s for %s'), str(evt), pvc_name)

        # Process the event
        try:
            pvc_v1client = self._get_pvc_v1_client()
            v1pvc_images = pvc_v1client.images
            pvc_v2client = self._get_pvc_v2_client()
            v2pvc_images = pvc_v2client.images
            pvc_image = self._get_image(pvc_id, pvc_id, pvc_name,
                                        v1pvc_images, v2pvc_images)
            if pvc_image is None:
                LOG.debug(_('The PowerVC image \'%s\' with UUID %s was not '
                            'update synchronized because it could not be '
                            'found.'), pvc_name, pvc_id)
                return

            # Try processing the PowerVC image update
            LOG.info(_('Performing update sync of image \'%s\' from PowerVC to'
                       ' the local hosting OS after an image update event'),
                     pvc_image.name)

            # Update sync PowerVC image to the local hosting OS
            local_v1client = self._get_local_v1_client()
            v1local_images = local_v1client.images
            local_v2client = self._get_local_v2_client()
            v2local_images = local_v2client.images
            local_image = self._get_local_image_from_pvc_id(pvc_id, pvc_name,
                                                            v1local_images,
                                                            v2local_images)

            # Update the image if it is in the local hosting OS
            if local_image is None:
                LOG.info(_('The local hosting OS image \'%s\' with PowerVC '
                           'UUID %s was not updated because it could not be '
                           'found.'), pvc_image.name, pvc_id)
                return

            # If the PowerVC image has changed, do not update it. This only
            # happens if we lost an event. In that case we need to wait for
            # the periodic scan to merge changes.
            if self._local_image_updated(pvc_id, local_image):
                LOG.info(_('The local hostingOS image \'%s\' for PowerVC UUID '
                           '%s has changed. Changes between the local '
                           'hostingOS and the PowerVC image will be merged '
                           'during the next periodic scan.'), local_image.name,
                         pvc_id)
                return

            # Perform the image update to the local hosting OS
            image = self._update_local_image(pvc_id, pvc_image, local_image,
                                             v1local_images, v2local_images)
            if image is None:
                LOG.error(_('Local hosting OS image \'%s\' for PowerVC UUID %s'
                            ' was not updated after an image update event.'),
                          local_image.name, pvc_id)
                return

            # NOTE: Do not reset the updated_at values until after both the
            # local hostingOS image and PowerVC image are successfully updated.

            # Since the PowerVC image was updated, update the entry in the
            # update_at dict so the change isn't processed during a periodic
            # scan
            if pvc_id in self.pvc_updated_at.keys():
                self.pvc_updated_at[pvc_id] = pvc_image.updated_at

            # Attempt to update the entry for this image in the local
            # updated_at dict so that it is not processed during a periodic
            # sync due to this update.
            if pvc_id in self.local_updated_at.keys():
                self.local_updated_at[pvc_id] = image.updated_at

            # Set the new master image
            self.master_image[pvc_id] = pvc_image
            LOG.info(_('Completed update sync of image \'%s\' from PowerVC to '
                       'the local hosting OS after an image update event'),
                     pvc_image.name)
        except Exception as e:
            LOG.exception(_('An error occurred processing the PowerVC image '
                            'update event: %s'), e)

    def _process_pvc_image_delete_event(self, v1image_dict):
        """
        Process a PowerVC image delete event.

        :param: v1image_dict The deleted v1 image dict
        """
        LOG.debug(_('PowerVC delete event received: %s'), str(v1image_dict))

        def clean_up(uuid):
            """
            Clean up the update_at and master_image copy for the deleted image
            with the specified idenfitier. Also clean up the ids_dict.

            :param: uuid The PowerVC UUID of the deleted image
            """
            if uuid in self.local_updated_at.keys():
                self.local_updated_at.pop(uuid)
            if uuid in self.master_image.keys():
                self.master_image.pop(uuid)
            if uuid in self.ids_dict.keys():
                self.ids_dict.pop(uuid)

            # Since the PowerVC image was deleted, remove the entry from the
            # update_at dict so the change isn't processed during a periodic
            # scan. Only do this if the local hostingOS image was also deleted,
            # or it will not be deleted during the next periodic scan.
            if uuid in self.pvc_updated_at.keys():
                self.pvc_updated_at.pop(uuid)

        event_type = constants.IMAGE_EVENT_TYPE_DELETE
        pvc_id = v1image_dict.get('id')
        pvc_name = v1image_dict.get('name')

        # Determine if we should ignore this event
        evt = self._get_event(constants.POWER_VC, event_type, v1image_dict)
        if self._get_pvc_event_to_ignore(evt) is not None:
            LOG.debug(_('Ignoring event %s for %s'), str(evt), pvc_name)
            return
        else:
            LOG.debug(_('Processing event %s for %s'), str(evt), pvc_name)

        # Process the event
        try:

            # Try processing the local hosting OS image update
            LOG.info(_('Performing delete sync of image \'%s\' from PowerVC to'
                       ' the local hosting OS after an image delete event'),
                     pvc_name)

            # Delete sync PowerVC image to the local hosting OS
            local_v1client = self._get_local_v1_client()
            v1local_images = local_v1client.images
            local_v2client = self._get_local_v2_client()
            v2local_images = local_v2client.images
            local_image = self._get_local_image_from_pvc_id(pvc_id, pvc_name,
                                                            v1local_images,
                                                            v2local_images)

            # Delete the image if it is in the local hosting OS
            if local_image is None:
                LOG.info(_('The local hosting OS image \'%s\' with PowerVC '
                           'UUID %s was not deleted because it could not be '
                           'found.'), pvc_name, pvc_id)

                # Since the local hostingOS image was deleted, remove the entry
                # from the update_at dict so the change isn't processed during
                # a periodic scan. Also delete the master_image copy.
                clean_up(pvc_id)
                return

            # Perform the image delete to the local hosting OS
            image = self._delete_local_image(pvc_id, local_image,
                                             v1local_images)
            if image is None:
                LOG.error(_('Local hosting OS image \'%s\' for PowerVC UUID %s'
                            ' could not be deleted after an image delete '
                            'event.'), local_image.name, pvc_id)
                return

            # Add delete to event ignore list so we don't process it again try
            # to delete the local hosting OS image again. Only do this if event
            # handling is running.
            self._ignore_local_event(event_type, image.to_dict())

            # Since the local hostingOS image was deleted, remove the entry
            # from the update_at dict so the change isn't processed during a
            # periodic scan. Also delete the master_image copy
            clean_up(pvc_id)
            LOG.info(_('Completed delete sync of image \'%s\' from PowerVC to '
                       'the local hosting OS after an image delete event'),
                     pvc_name)
        except Exception as e:
            LOG.exception(_('An error occurred processing the PowerVC image '
                            'delete event: %s'), e)

    def _process_pvc_image_activate_event(self, v1image_dict):
        """
        Process a PowerVC image activate event.

        :param: v1image_dict The activated v1 image dict
        """
        LOG.debug(_('PowerVC activate event received: %s'),
                  str(v1image_dict))
        pvc_id = v1image_dict.get('id')
        pvc_name = v1image_dict.get('name')

        # Process the event
        try:
            pvc_v1client = self._get_pvc_v1_client()
            v1pvc_images = pvc_v1client.images
            pvc_v2client = self._get_pvc_v2_client()
            v2pvc_images = pvc_v2client.images
            pvc_image = self._get_image(pvc_id, pvc_id, pvc_name,
                                        v1pvc_images, v2pvc_images)

            # Nothing to do if the image was not found
            if pvc_image is None:
                LOG.debug(_('The PowerVC image \'%s\' with UUID %s was not '
                            'add synchronized because it could not be found.'),
                          pvc_name, pvc_id)
                return

            # The first image update event after an activate will not have
            # the config strategy if the image has one. That is written after
            # the image is created using the glance v2 PATCH API. We do not
            # want to process the first update event after the create if it
            # has the same checksum value as the activate event. If that
            # update event is not added to the ignore list, the result could
            # be the event ping-pong effect. Image update events with and
            # without the config strategy will go back and forth between
            # the local hostingOS and PowerVC.
            self._ignore_pvc_event(constants.IMAGE_EVENT_TYPE_UPDATE,
                                   pvc_image.to_dict())

            # Nothing to do if the image is not accesible
            if not self._image_is_accessible(pvc_image):
                LOG.debug(_('The PowerVC image \'%s\' with UUID %s was not '
                            'add synchronized because it is not accessible.'),
                          pvc_name, pvc_id)
                return

            # Try processing the PowerVC image add
            LOG.info(_('Performing add sync of image \'%s\' from PowerVC to '
                       'the local hosting OS after an image activate event'),
                     pvc_image.name)

            # Add sync PowerVC image to the local hosting OS
            local_v1client = self._get_local_v1_client()
            v1local_images = local_v1client.images
            local_v2client = self._get_local_v2_client()
            v2local_images = local_v2client.images

            # No need to add the ACTIVATE event to the event ignore since the
            # local hosting OS does not process them. This could change in a
            # future release.

            # Check to see if this PowerVC image is already in the local
            # hostingOS. This would be the case if an instance capture was
            # initiated on the local hostingOS, and a queued snapshot image was
            # created. If the image is already on the local hostingOS, simply
            # update it.
            props = self._get_image_properties(v1image_dict)
            if props and consts.LOCAL_UUID_KEY in props.keys():

                # Look for the LOCAL_UUID_KEY in the PowerVC image. If it is
                # found it will be used to get the local image. This should be
                # set when an instance is captured, and a snapshot image is
                # created on the PowerVC.
                local_id = props.get(consts.LOCAL_UUID_KEY)
                if self._local_image_exists(local_id, v1local_images):
                    local_image = self._get_image(pvc_id, local_id, pvc_name,
                                                  v1local_images,
                                                  v2local_images)
                else:
                    local_image = None
            else:

                # If the LOCAL_UUID_KEY is missing, check for a local image
                # with the PowerVC UUID of the image event.
                local_image = self._get_local_image_from_pvc_id(pvc_id,
                                                                pvc_name,
                                                                v1local_images,
                                                                v2local_images)

            # Update the image if it is in the local hosting OS, else add it
            if local_image is not None:
                LOG.info(_('The local hosting OS image \'%s\' with PowerVC '
                           'UUID %s already exists so it will be updated.'),
                         pvc_image.name, pvc_id)

                # If this is a snapshot image, it may not have an entry in the
                # ids_dict so add one here.
                self.ids_dict[pvc_id] = local_image.id

                # If the PowerVC image has changed, do not update it. This only
                # happens if we lost an event. In that case we need to wait for
                # the periodic scan to merge changes. If the image is queued,
                # it should be updated anyway since this is the local hostingOS
                # snapshot image of an instance capture.
                if local_image.status != 'queued' and \
                        self._local_image_updated(pvc_id, local_image):
                    LOG.info(_('The local hostingOS image \'%s\' for PowerVC '
                               'UUID %s has changed. Changes between the local'
                               ' hostingOS and the PowerVC image will be '
                               'merged during the next periodic scan.'),
                             local_image.name, pvc_id)
                    return

                # Perform the image update to the local hosting OS
                image = self._update_local_image(pvc_id, pvc_image,
                                                 local_image, v1local_images,
                                                 v2local_images)
                if image is None:
                    LOG.error(_('Local hosting OS image \'%s\' for PowerVC '
                                'UUID %s could not be updated after an image '
                                'create event.'), local_image.name, pvc_id)
                    return

                # NOTE: Do not reset the updated_at values until after both the
                # local hostingOS image and PowerVC image are successfully
                # updated.

                # Update the entry for this image in the local updated_at dict
                # so that it is not processed during a periodic sync due to
                # this update.
                self.local_updated_at[pvc_id] = image.updated_at
            else:

                # Perform the image add to the local hosting OS
                local_image_owner = self._get_local_staging_owner_id()
                if local_image_owner is None:
                    LOG.warning(_("Invalid staging user or project."
                                  " Skipping new image sync."))
                    return
                else:
                    pvc_v2client = self._get_pvc_v2_client()
                    image = self._add_local_image(
                        pvc_id, pvc_image, local_image_owner,
                        pvc_v2client.http_client.endpoint, v1local_images,
                        v2local_images)
                    if image is None:
                        LOG.error(_('Local hosting OS image \'%s\' for PowerVC'
                                    'UUID %s could not be created after an '
                                    'image create event.'), pvc_image.name,
                                  pvc_id)
                        return

                # NOTE: Do not set the updated_at values until after both the
                # local hostingOS image and PowerVC image are successfully
                # added.

                # Add the new local image to the updated_at dict so this add
                # isn't processed as an add durng a periodic sync
                self.local_updated_at[pvc_id] = image.updated_at

                # Add an entry into the ids_dict
                self.ids_dict[pvc_id] = image.id

            # Add the new image to the updated_at dict so this add isn't
            # processed as an add during a periodic sync
            self.pvc_updated_at[pvc_id] = v1image_dict.get('updated_at')

            # A new image was added. Add that image to the master_image dict
            # for use in the periodic scan later. It is OK to do it here and
            # not wait for an ACTIVATE event in the local hostingOS. It will
            # only be used if the there is an image for the UUID on hoth
            # servers.
            self.master_image[pvc_id] = pvc_image
            LOG.info(_('Completed add sync of image \'%s\' from PowerVC to the'
                       ' local hosting OS after an image activate event'),
                     pvc_image.name)
        except Exception as e:
            LOG.exception(_('An error occurred processing the PowerVC image '
                            'create event: %s'), e)

    def _ignore_local_event(self, event_type, v1image_dict):
        """
        Set to ignore a local image event.

        Whenever we perform an add, update, or delete operation on an image
        that operation should prepare the event handlers to ignore any
        events generated by that operation. This will prevent image events
        from ping-ponging between sides.

        :param: event_type: The type of event to ignore
        :param: v1image_dict: The v1 image dict of the image the event will be
                                generated for.
        """
        if self.local_event_handler_running:
            evt = self._get_event(constants.LOCAL, event_type, v1image_dict)
            self.local_events_to_ignore_dict[time.time()] = evt
            LOG.debug(_('Set to ignore event %s for %s'), str(evt),
                      v1image_dict.get('name'))

    def _ignore_pvc_event(self, event_type, v1image_dict):
        """
        Set to ignore a PowerVC image event.

        Whenever we perform an add, update, or delete operation on an image
        that operation should prepare the event handlers to ignore any
        events generated by that operation. This will prevent image events
        from ping-ponging between sides.

        :param: event_type: The type of event to ignore
        :param: v1image_dict: The v1 image dict of the image the event will be
                                generated for.
        """
        if self.pvc_event_handler_running:
            evt = self._get_event(constants.POWER_VC, event_type, v1image_dict)
            self.pvc_events_to_ignore_dict[time.time()] = evt
            LOG.debug(_('Set to ignore event %s for %s'), str(evt),
                      v1image_dict.get('name'))

    def _get_event(self, side, event_type, v1image_dict):
        """
        Get an image event for the image, and event type.

        :param: side The side to ignore the event on, This is either LOCAL or
                        POWER_VC.
        :param: event_type: The type of event to ignore
        :param: v1image_dict: The v1 image dict of the image the event will be
                                generated for.
        :returns: The image event representation
        """
        checksum = self._get_image_checksum(v1image_dict)
        return (side, event_type, v1image_dict.get('id'), checksum)

    def _get_image_checksum(self, v1image_dict):
        """
        Calculate and return the md5 checksum of the parts of the specified
        v1image that that can be updated.

        :param: v1image_dict The dict of the v1 image
        :returns: The calculated md5 checksum value for the image
        """
        md5 = hashlib.md5()

        # Process the UPDATE_PARAMS attributes that are not filtered
        for attr in sorted(v1image_dict.keys()):
            if attr in v1images.UPDATE_PARAMS and \
                attr not in constants.IMAGE_UPDATE_PARAMS_FILTER and \
                    attr != 'properties':
                value = v1image_dict.get(attr)
                if value is not None:
                    md5.update(str(value))

        # Process the properties that are not filtered
        props = self._get_image_properties(v1image_dict, {})
        for propkey in sorted(props.keys()):
            if propkey not in constants.IMAGE_UPDATE_PROPERTIES_FILTER:
                prop_value = props.get(propkey)
                if prop_value is not None:
                    md5.update(str(prop_value))

        # Return the md5 checksum value of the image attributes and properties
        return md5.hexdigest()

    def _get_local_staging_owner_id(self):
        """
        If the local staging owner id has not been obtained, get it and store
        for use later.

        An image owner can be either a tenant id or a user id depending on the
        configuration value owner_is_tenant. If owner_is_tenant is True, get
        the staging project id and use that as the owner. If owner_is_tenant
        is False, get the staging user id and use that as the owner.

        :returns: The local hostingOS staging owner id or None if the staging
        user or project have been incorrectly configured or are unavailable.
        """
        if not self._staging_cache.is_valid:
            LOG.warning(_("Invalid staging user or project"))
            return None

        user_id, project_id = \
            self._staging_cache.get_staging_user_and_project()

        if CONF.owner_is_tenant:
            return project_id
        else:
            return user_id

    def _local_image_exists(self, uuid, v1local_images):
        """
        Determine if a local image with the specified uuid exists without
        raising an error if it does not.

        :param: uuid The local image UUID
        :param: v1local_images The image manager of the image controller to use
        :returns: True if the local image exists, else False
        """
        if uuid is None:
            return False
        if uuid in self.ids_dict.values():
            return True
        params1 = self._get_limit_filter_params()
        params2 = self._get_limit_filter_params()
        params2 = self._get_not_ispublic_filter_params(params2)
        v1images = itertools.chain(v1local_images.list(**params1),
                                   v1local_images.list(**params2))
        for image in v1images:
            if image is not None and image.id == uuid:
                return True
        return False

    def _get_local_image_from_pvc_id(self, pvc_id, pvc_name, v1local_images,
                                     v2local_images):
        """
        Find the local hostingOS v1 image with the given PowerVC UUID.

        :param: pvc_id The PowerVC UUID
        :param: pvc_name The image name
        :param: v1local_images The image manager of the image controller to use
        :param: v2local_images The image controller to use
        """
        if pvc_id is None:
            return None
        local_image = None
        if pvc_id in self.ids_dict.keys():
            local_id = self.ids_dict[pvc_id]
            if local_id is not None:
                local_image = self._get_image(pvc_id, local_id, pvc_name,
                                              v1local_images, v2local_images)

        # If the imageId was not known or it was not found, look again through
        # all local hostingOS images
        if local_image is None:
            params1 = self._get_limit_filter_params()
            params2 = self._get_limit_filter_params()
            params2 = self._get_not_ispublic_filter_params(params2)
            local_image = \
                self._get_v1image_from_pvc_id(pvc_id, itertools.chain(
                    v1local_images.list(**params1),
                    v1local_images.list(**params2)))

        # Save for next time
        if local_image is not None:
            self.ids_dict[pvc_id] = local_image.id
        return local_image

    def _get_v1image_from_pvc_id(self, pvc_id, v1images):
        """
        Look through all v1 local hostingOS images for the image that has the
        given PowerVC image UUID.

        :param: pvc_id The PowerVC image id
        :param: v1images The image manager used to obtain images from the v1
                            glance client
        :returns: The image for the specified PowerVC id or None if not found.
       """
        for image in v1images:
            if image is not None:
                props = image.properties
                if props and consts.POWERVC_UUID_KEY in props.keys():
                    uuid = props.get(consts.POWERVC_UUID_KEY)
                    if uuid == pvc_id:
                        return image
        return None

    def _get_local_v1_client(self):
        """
        Get a local v1 glance client if not already created.

        :returns: The glance v1 client for the local hostingOS
        """
        if self.local_v1client is None:
            self.local_v1client = clients.LOCAL.get_client(
                str(consts.SERVICE_TYPES.image), 'v1')
        return self.local_v1client

    def _get_local_v2_client(self):
        """
        Get a local v2 glance client if not already created.

        :returns: The glance v2 client for the local hostingOS
        """
        if self.local_v2client is None:
            self.local_v2client = clients.LOCAL.get_client(
                str(consts.SERVICE_TYPES.image), 'v2')
        return self.local_v2client

    def _get_pvc_v1_client(self):
        """
        Get a PowerVC v1 glance client if not already created.

        :returns: The glance v1 client for PowerVC
        """
        if self.pvc_v1client is None:
            self.pvc_v1client = clients.POWERVC.get_client(
                str(consts.SERVICE_TYPES.image), 'v1')
        return self.pvc_v1client

    def _get_pvc_v2_client(self):
        """
        Get a PowerVC v2 glance client if not already created.

        :returns: The glance v2 client for PowerVC
        """
        if self.pvc_v2client is None:
            self.pvc_v2client = clients.POWERVC.get_client(
                str(consts.SERVICE_TYPES.image), 'v2')
        return self.pvc_v2client

    def _get_limit_filter_params(self, params=None):
        """
        Build up the image manager list filter params for filters for
        image limit if it is specified. This is used for the v1 API to work
        around a bug that the glance has with DB2. This may not be necessary
        on all versions of OpenStack.

        :param: params The existing parameters if any. The default is None
        :returns: The image mananger list filter params dict for setting
                    the the glance limit argument
        """
        if params is None:
            params = {}
            filters = {}
        else:
            filters = params.get('filters', {})
        filters['limit'] = CONF['powervc'].image_limit
        params['filters'] = filters
        return params

    def _get_not_ispublic_filter_params(self, params=None):
        """
        Build up the image manager list filter params for filters for
        is_public=False. This is used for the v1 API to get the non-public
        images. This may not be necessary on all versions of OpenStack.

        :param: params The existing parameters if any. The default is None
        :returns: The image mananger list filter params dict for setting
                    is_public=False
        """
        if params is None:
            params = {}
            filters = {}
        else:
            filters = params.get('filters', {})
        filters['is_public'] = False
        params['filters'] = filters
        return params

    def _check_scg_at_startup(self):
        """
        If the Storage Connectivity Groups are not specified, terminate the
        ImageManager service here. If the Storage Connectivity Group is not
        found at startup, keep running. It may appear later.
        """
        scg_not_found = False
        try:

            # Cache the scg if it is specified, and found on PowerVC
            self.our_scg_list = utils.get_utils().get_our_scg_list()
        except StorageConnectivityGroupNotFound:

            # If we get this exception, our_scg will be None, but we know
            # the scg was specified because it was not found on PowerVC.
            # That is accceptable.
            scg_not_found = True

        # If our_scg is None and we didn't get a
        # StorageConnectivityGroupNotFound exception, then the SCG is not
        # specified so the ImageManager service must terminate.
        if not self.our_scg_list and not scg_not_found:
            LOG.error(_('Glance-powervc service terminated. No Storage '
                        'Connectivity Group specified.'))
            sys.exit(1)

    def _get_our_scg_list(self):
        """
        If a SCG name or id is specified in our configuration, see if the scg
        exists. If it does not exist an exception is raised. If it exists, the
        scg for the name or id specified is returned. If no SCG name or id is
        specified, None is returned for the scg.

        :returns: The StorageConnectivityGroup object if found, else None. If a
        specified scg is not found, a :exc:'StorageConnectivityGroupNotFound'
        exception is raised.
        """
        our_scg_list = utils.get_utils().get_our_scg_list()
        if our_scg_list:
            LOG.debug(_('Only images found in the PowerVC Storage Connectivity'
                        ' Group \'%s\' will be used.'),
                      str([scg.display_name for scg in our_scg_list]))
        else:
            LOG.debug(_('No Storage Connectivity Group is specified in the '
                        'configuration settings, so all PowerVC images will '
                        'be used.'))
        return our_scg_list

    def _image_is_accessible(self, image):
        """
        Determine whether the specified image is accessible. To be accessible,
        the image must belong to our storage conectivity group.

        If our_scg was found, the image must belong to that scg. If the scg was
        not specified, then the image is considered accessible.

        If an error occurs while getting the SCGs for an image, and exception
        is raised. The caller should expect that an exception may occur.

        :param: image The v1 image
        :returns: True if the specified image is accessible
        """
        if image is None:
            return False
        if self.our_scg_list is not None:
            our_scg_id_list = [our_scg.id for our_scg in self.our_scg_list]

            # Get all of the SCGS for the image. If an error occurs, an
            # exception will be raised, and the current operation will fail.
            # The caller should catch the exception and continue.
            scgs = utils.get_utils().get_image_scgs(image.id)
            LOG.debug(_('Image \'%s\': Storage Connectivity Groups: %s'),
                      image.name, str(scgs))
            for scg in scgs:
                if scg.id in our_scg_id_list:
                    return True
            LOG.debug(_('Image \'%s\' is not accessible on Storage '
                        'Connectivity Group \'%s\''), image.name,
                      str([our_scg.display_name
                           for our_scg in self.our_scg_list]))
            return False
        else:
            return True

    def _get_local_event_to_ignore(self, evt):
        """
        Get the specified local event tuple to ignore from the
        local_events_to_ignore_dict. If the event tuple is found in the dict,
        remove it, and return it to the caller, else return None.

        :param: evt The event tuple to get from the local_events_to_ignore_dict
        :returns: The event tuple if found, else None
        """
        for evt_time in sorted(self.local_events_to_ignore_dict.keys()):
            if evt == self.local_events_to_ignore_dict[evt_time]:
                return self.local_events_to_ignore_dict.pop(evt_time)

    def _get_pvc_event_to_ignore(self, evt):
        """
        Get the specified PowerVC event tuple to ignore from the
        pvc_events_to_ignore_dict. If the event tuple is found in the dict,
        remove it, and return it to the caller, else return None.

        :param: evt The event tuple to get from the pvc_events_to_ignore_dict
        :returns: The event tuple if found, else None
        """
        for evt_time in sorted(self.pvc_events_to_ignore_dict.keys()):
            if evt == self.pvc_events_to_ignore_dict[evt_time]:
                return self.pvc_events_to_ignore_dict.pop(evt_time)

    def _purge_expired_local_events_to_ignore(self):
        """
        Remove expired local hostingOS event tuples from the
        local_events_to_ignore_dict. The event tuple expiration time is defined
        by the constant EVENT_TUPLE_EXPIRATION_PERIOD_IN_HOURS.
        """
        cur_time = time.time()
        for evt_time in sorted(self.local_events_to_ignore_dict.keys()):
            if cur_time - evt_time >= (
                constants.EVENT_TUPLE_EXPIRATION_PERIOD_IN_HOURS *
                    constants.SECONDS_IN_HOUR):
                self.local_events_to_ignore_dict.pop(evt_time)
            else:
                break

    def _purge_expired_pvc_events_to_ignore(self):
        """
        Remove expired PowerVC event tuples from the pvc_events_to_ignore_dict.
        The event tuple expiration time is defined by the constant
        EVENT_TUPLE_EXPIRATION_PERIOD_IN_HOURS.
        """
        cur_time = time.time()
        for evt_time in sorted(self.pvc_events_to_ignore_dict.keys()):
            if cur_time - evt_time >= (
                constants.EVENT_TUPLE_EXPIRATION_PERIOD_IN_HOURS *
                    constants.SECONDS_IN_HOUR):
                self.pvc_events_to_ignore_dict.pop(evt_time)
            else:
                break

    def _clear_sync_summary_counters(self):
        """
        Clear the counters used for the sync summary display
        """
        self.local_created_count = 0
        self.local_updated_count = 0
        self.local_deleted_count = 0
        self.pvc_created_count = 0
        self.pvc_updated_count = 0
        self.pvc_deleted_count = 0

    def _unescape(self, props):
        """
        Unescape any HTML/XML entities in certain image properties.

        :param: props The image properties
        """
        if props is not None:
            for key in props.keys():
                if key in constants.IMAGE_UNESCAPE_PROPERTIES:
                    if props[key]:
                        propVal = props[key].replace("&lt;", "<")
                        props[key] = propVal.replace("&gt;", ">")

    def _get_image_properties(self, v1image_dict, default_props=None):
        """
        Get the image properties from a v1 image dict. The properties may
        contain HTML/XML escaped entities so unescape any we suspect could
        be there before returning. Any properties with null values are also
        filtered. There is no need to process/sync any properties that have
        a null value. Having a null value should mean the same thing as the
        property not existing.

        This method should always be called to get the properties from a v1
        image before modifying them or using them do perform an image update.

        :param: v1image_dict A v1 image dict
        :param: default_props The default value to use for the properties if
                                they are not found in the v1 image dict. The
                                default is None
        :returns: The properties from the v1 image with certain properties
                    unescaped if found. Returns None if no properties are found
        """
        filtered_props = None
        if v1image_dict is not None:
            props = v1image_dict.get('properties', default_props)
            if props is not None:
                filtered_props = {}
                for prop in props.keys():
                    if props[prop] is not None:
                        filtered_props[prop] = props[prop]
                self._unescape(filtered_props)
        return filtered_props

    def _format_special_image_extra_property(self, imageUUID):
        """
        Format one special extra image property , named "image_topology" ,
         which is used for UI to select an available Storage Connectivity
        Groups or Storage template.

        :param: imageUUID that selected to boot a VM
        :returns:
        """
        if imageUUID is None:
            return []
        image_topology = []
        image_scg_list = utils.get_utils().get_image_scgs(imageUUID, True)
        available_image_scg_list = \
            utils.get_utils().filter_out_available_scgs(image_scg_list)
        for scg in available_image_scg_list:
            scg_topology = {}
            scg_topology['scg_id'] = scg.id
            scg_topology['display_name'] = scg.display_name

            scg_hosts = scg.host_list
            available_hosts = []
            for host in scg_hosts:
                host_info = \
                    utils.get_utils().get_hypervisor_by_name(host['name'])
                if host_info is None:
                    break
                else:
                    host_prop_dict = {}
                    host_prop_dict['host_name'] = \
                        host_info.__dict__['service']['host']
                    host_prop_dict['host_display_name'] = \
                        host_info.__dict__['service']['host_display_name']
                    available_hosts.append(host_prop_dict)
            if available_hosts:
                scg_topology['host_list'] = available_hosts

            scg_storage_templates = \
                utils.get_utils().get_scg_accessible_storage_templates(scg.id)
            available_storage_templates = []
            for storage_template in scg_storage_templates:
                storage_template_dict = {}
                storage_template_dict['id'] = storage_template.id
                storage_template_dict['name'] = storage_template.name
                available_storage_templates.append(storage_template_dict)
            if available_storage_templates:
                scg_topology['storage_template_list'] = \
                    available_storage_templates

            image_topology.append(scg_topology)

        json_image_topology = jsonutils.dumps(image_topology)
        return json_image_topology


class ImageSyncController():
    """
    The ImageSyncController starts the next image startup or periodic sync when
    appropriate. Startup sync will run first. It will run every minute by
    default until it completes successfully. After that, it will run the
    periodic sync every five mintues by default. If the periodic sync does not
    complete successfully, it is run every minute by default until it completes
    successfully, and then it resumes running every five minutes. This allows
    for retries due to communications errors to occur more frequently.

    The elpased time to wait from the end of one sync to the start of another
    is determined by whether the previous sync operation passed, or failed. If
    it failed, the time to wait is specified by retry_interval_in_seconds. If
    the previous sync operation passed, the time to wait is specified by
    image_periodic_sync_interval_in_seconds. Those values default to 60
    seconds, and 300 seconds respectfully, but can be set by the user in the
    powervc.conf file.
    """

    def __init__(self, image_manager):
        self.image_manager = image_manager
        self.started = False
        self.sync_running = False
        self.startup_sync_completed = False
        self.startup_sync_result = constants.SYNC_FAILED
        self.periodic_sync_result = constants.SYNC_FAILED
        self.elapsed_time_in_seconds = 0
        self.next_sync_time_in_seconds = 0
        self.periodic_sync_interval_in_seconds = \
            CONF['powervc'].image_periodic_sync_interval_in_seconds
        self.retry_interval_in_seconds = \
            CONF['powervc'].image_sync_retry_interval_time_in_seconds
        self.sync_check_interval_in_seconds = \
            constants.IMAGE_SYNC_CHECK_INTERVAL_TIME_IN_SECONDS

    def start(self):
        """
        Start the ImageSyncController. This will start the Startup Sync
        operation, and then start a timer which will call an internal method
        used to detemine when the next sync operation should begin.

        Startup sync will repeat with a delay in between until it completes
        successfully. After that, periodic sync will run at the configured
        interval. If a periodic sync fails for a communications error, it will
        repeat with a delay in between runs until it completes successfully.
        """
        if not self.started:
            self.started = True

            # Start by doing a startup sync
            self.sync_running = True
            self.image_manager.sync_images()

            # Start a threadgroup timer here to wake up the ImageSyncController
            # every second by default, and call _sync_images(). That method
            # will determine when the next sync should be run.
            self.image_manager.tg.add_timer(
                self.sync_check_interval_in_seconds, self._sync_images)

    def set_startup_sync_result(self, result):
        """
        This should be called when startup sync ends to set it's result.

        :param: result The startup sync result code of SYNC_PASSED or
                        SYNC_FAILED
        """
        self.startup_sync_result = result
        if self.startup_sync_result == constants.SYNC_PASSED:
            self.startup_sync_completed = True
            self.next_sync_time_in_seconds = \
                self.periodic_sync_interval_in_seconds
        else:
            self.next_sync_time_in_seconds = self.retry_interval_in_seconds
        self.sync_running = False

    def is_startup_sync_done(self):
        """
        Determine if startup sync has completed successfully.

        :returns: True if startup sync has completed successfully, else False.
        """
        return self.startup_sync_completed

    def set_periodic_sync_result(self, result):
        """
        This should be called when periodic sync ends to set it's result.

        :param: result The periodic sync result code of SYNC_PASSED or
                        SYNC_FAILED
        """
        self.periodic_sync_result = result
        if self.periodic_sync_result == constants.SYNC_PASSED:
            self.next_sync_time_in_seconds = \
                self.periodic_sync_interval_in_seconds
        else:
            self.next_sync_time_in_seconds = self.retry_interval_in_seconds
        self.sync_running = False

    def _sync_images(self):
        """
        This is called by the timer every one second by default. If a sync
        operation is currently running, it will do nothing and return. If a
        sync operation is not running, it will determine the elapsed time
        since the end of the last sync operation. If that elapsed time has
        reached the predetermined amount, a sync operation will be initiated.
        """
        # If a sync operation is running, do nothing
        if self.sync_running:
            return

        # If the time is right, call image_manager.sync_images()
        self.elapsed_time_in_seconds += self.sync_check_interval_in_seconds
        if self.elapsed_time_in_seconds >= self.next_sync_time_in_seconds:
            self.elapsed_time_in_seconds = 0
            self.sync_running = True
            self.image_manager.sync_images()
