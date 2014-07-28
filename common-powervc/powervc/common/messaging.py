# Copyright 2013 IBM Corp.

"""
This module contains Qpid connection utilities that can be used to connect
to a Qpid message broker and listen for notifications.

Examples:

  # Import common messaging module
  from powervc.common import messaging

  # Connect to host OS Qpid broker and handle instance update notifications.
  conn = messaging.LocalConnection(
                              reconnect_handler=self.handle_qpid_reconnect)
  listener = conn.create_listener('nova', 'notifications.info')
  listener.register_handler('compute.instance.update',
                            self._handle_instance_update)
  conn.start()

  # Connect to PowerVC Qpid broker and handle two event types with a single
  # handler function.
  conn = messaging.PowerVCConnection()
  listener = conn.create_listener('nova', 'notifications.info')
  listener.register_handler(['compute.instance.create.start',
                     'compute.instance.create.end'],
                     self._handle_instance_create)
  conn.start()

  # Connect to PowerVC Qpid broker and handle any instance notifications.
  conn = messaging.PowerVCConnection()
  listener = conn.create_listener('nova', 'notifications.info')
  listener.register_handler('compute.instance.*',
                            self._handle_instance_notifications)
  conn.start()
"""

import sys
import threading
import traceback
import fnmatch
import json

from time import sleep

from qpid.messaging import Connection
from qpid.messaging.exceptions import ConnectionError

from oslo.config import cfg

from powervc.common.gettextutils import _

CONF = cfg.CONF


def log(log, level, msg):
    """
    Log a message.

    :param: log The log to write to.
    :param: level The logging level for the message
    :param: msg The message to log
    """
    if not log:
        return
    if level == 'critical':
        log.critical(msg)
    elif level == 'error':
        log.error(msg)
    elif level == 'warn':
        log.warn(msg)
    elif level == 'info':
        log.info(msg)
    elif level == 'debug':
        log.debug(msg)


class QpidConnection(object):
    """
    This class represents a connection to a Qpid broker. A QpidConnection must
    be created in order to send or receive AMQP messages using a Qpid broker.
    """

    def __init__(self, url, username, password, transport='tcp',
                 reconnection_interval=60, reconnect_handler=None,
                 context=None, log=None):
        """
        Create a new connection to a Qpid message broker in order to send or
        receive AMQP messages.

        :param: url URL for the Qpid connection, e.g. 9.10.49.164:5672
        :param: username Qpid username
        :param: password Qpid password
        :param: transport Transport mechanism, one of tcp, tcp+tls,
                    or ssl (alias for tcp+tls).
        :param: reconnection_interval Interval in seconds between reconnect
                    attempts.
        :param: reconnect_handler The function to call upon reconnecting to
                    the Qpid broker after connection was lost and
                    then reestablished. This function will be called after the
                    connections is reestablished but before the listeners are
                    started up again. It is not passed any parameters.
        :param: context The security context
        :param: log The logging module used for logging messages. If not
                    provided then no logging will be done.
        """
        self.url = url
        self.username = username
        self.password = password
        self.context = context
        self.log = log.getLogger(__name__) if log else None
        self.transport = transport
        self.reconnection_interval = reconnection_interval
        self.reconnect_handler = reconnect_handler
        self._listeners = []
        self._is_connected = False

    def create_listener(self, exchange, topic):
        """
        Create a new listener on the given exchange for the given topic.

        :param: exchange The name of the Qpid exchange, e.g. 'nova'
        :param: topic The topic to listen for, e.g. 'notifications.info'
        :returns: A new QpidListener that will listen for messages on the
                  given exchange and topic.
        """
        listener = QpidListener(self, exchange, topic)
        self._listeners.append(listener)
        return listener

    def start(self, is_reconnect=False):
        """
        Initiate the Qpid connection and start up any listeners.

        :param: is_reconnect True if this method is called as part of a
                             reconnect attempt, False otherwise
        :raise: ConnectionError if a connection cannot be established
        """
        # If the Qpid broker URL is not specified (or just the hostname is not
        # specified) then we can't make a connection.
        if not self.url or self.url.startswith(':'):
            log(self.log, 'warn', _('Qpid broker not specified, cannot start '
                                    'connection.'))
            return

        if not self._is_connected:
            self.conn = Connection(self.url, username=self.username,
                                   password=self.password,
                                   transport=self.transport)
            try:
                self.conn.open()
            except ConnectionError as e:
                log(self.log, 'critical', _('Cannot connect to Qpid message '
                                            'broker: %s') % (e.message))
                # close this connection when encounter connection error
                # otherwise, it will leave an ESTABLISHED connection
                # to qpid server forever.
                if self.conn is not None:
                    self.conn.close()
                raise e

            self._is_connected = True

            if is_reconnect and self.reconnect_handler:
                self.reconnect_handler()

            for listener in self._listeners:
                listener._start(self.conn)

            log(self.log, 'info', _('Connected to Qpid message broker: '
                                    '%s@%s') % (self.username, self.url))

    def _reconnect(self):
        """
        Attempt to reconnect to the Qpid message broker in intervals until the
        connection comes back.
        """
        self.conn = None

        class ReconnectionThread(threading.Thread):
            def __init__(self, qpid_connection):
                super(ReconnectionThread, self).__init__(
                    name='ReconnectionThread')
                self.qpid_connection = qpid_connection

            def run(self):
                while not self.qpid_connection._is_connected:
                    try:
                        self.qpid_connection.start(is_reconnect=True)
                    except ConnectionError:
                        sleep(self.qpid_connection.reconnection_interval)
                        pass

        reconnection_thread = ReconnectionThread(self)
        reconnection_thread.start()

    def set_reconnect_handler(self, reconnect_handler):
        """
        Set the function to call upon reconnecting to the Qpid broker after
        connection is lost and then reestablished.

        :param: reconnect_handler The function to call upon reconnecting.
        """
        self.reconnect_handler = reconnect_handler


class PowerVCConnection(QpidConnection):
    """
    This class represents a connection to the PowerVC Qpid broker as defined
    in the configuration property files.
    """

    def __init__(self, reconnect_handler=None, context=None, log=None):
        """
        Create a new connection to the PowerVC Qpid message broker in order
        to send or receive AMQP messages.

        :param: reconnect_handler The function to call upon reconnecting to
                    the Qpid broker after connection was lost and
                    then reestablished. This function will be called after the
                    connection is reestablished but before the listeners are
                    started up again. It is not passed any parameters.
        :param: context The security context
        :param: log The logging module used for logging messages. If not
                    provided then no logging will be done.
        """
        if CONF.powervc.qpid_protocol == 'ssl':
            transport = 'ssl'
        else:
            transport = 'tcp'
        super(PowerVCConnection,
              self).__init__('%s:%d' % (CONF.powervc.qpid_hostname,
                                        CONF.powervc.qpid_port),
                             CONF.powervc.qpid_username,
                             CONF.powervc.qpid_password,
                             reconnect_handler=reconnect_handler,
                             context=context, log=log,
                             transport=transport)


class LocalConnection(QpidConnection):
    """
    This class represents a connection to the local OS Qpid broker as defined
    in the configuration property files.
    """

    def __init__(self, reconnect_handler=None, context=None, log=None):
        """
        Create a new connection to the local OS Qpid message broker in order
        to send or receive AMQP messages.

        :param: reconnect_handler The function to call upon reconnecting to
                    the Qpid broker after connection was lost and
                    then reestablished. This function will be called after the
                    connection is reestablished but before the listeners are
                    started up again. It is not passed any parameters.
        :param: context The security context
        :param: log The logging module used for logging messages. If not
                    provided then no logging will be done.
        """
        if CONF.openstack.qpid_protocol == 'ssl':
            transport = 'ssl'
        else:
            transport = 'tcp'
        super(LocalConnection,
              self).__init__('%s:%d' % (CONF.openstack.qpid_hostname,
                                        CONF.openstack.qpid_port),
                             CONF.openstack.qpid_username,
                             CONF.openstack.qpid_password,
                             reconnect_handler=reconnect_handler,
                             context=context, log=log,
                             transport=transport)


class QpidListener(object):
    '''
    This class is used to listen for AMQP message notifications. It should
    probably not be instantiated directly. First create a QpidConnection and
    then add a QpidListener to the connection using the
    QpidConnection.create_listener() method.
    '''

    def __init__(self, qpid_connection, exchange, topic):
        """
        Create a new QpidListener object to listen for AMQP messages.

        :param: qpid_connection The QpidConnection object used for connecting
                                to the Qpid message broker.
        :param: exchange The name of the Qpid exchange, e.g. 'nova'
        :param: topic The topic to listen for, e.g. 'notifications.info'
        """
        self.qpid_connection = qpid_connection
        self.exchange = exchange
        self.topic = topic
        self._handler_map = {}
        self._count_since_acknowledge = 0

    def register_handler(self, event_type, handler):
        """
        Register a handler function for one or more message notification event
        types. The handler function will be called when a message is
        received that matches the event type. The handler function will be
        passed two arguments: the security context and a dictionary containing
        the message attributes. The message attributes include: event_type,
        timestamp, message_id, priority, publisher_id, payload.

        The following wildcards are allowed when registering an event type
        handler (see the documentation for fnmatch):

          *        matches everything
          ?        matches any single character
          [seq]    matches any character in seq
          [!seq]   matches any character not in seq

        For example, registering the following event type handler will cause
        the handler function to be called for any event type starting with
        'compute.instance.'.

          listener = conn.register_handler('compute.instance.*',
                                           self.handle_instance_messages)

        If a single notification event type matches multiple registered
        handlers, each matching handler will be called. The order in which the
        handlers are called is not guaranteed. If the execution order is
        important for the multiple handlers of a single event type then ensure
        that only a single handler will be called for the event type and
        perform the multiple operations in the single handler.

        :param: event_type The event type or list of event types to associate
                           with the handler
        :param: handler The handler function to handle a message with the given
                        event type
        """
        if not isinstance(event_type, list):
            event_type = [event_type]
        for et in event_type:
            self._handler_map[et] = handler

    def unregister_handler(self, event_type):
        """
        Stop handling the given message notification event type.

        :param: event_type The event type to unregister
        """
        try:
            self._handler_map.pop(event_type)
        except KeyError:
            log(self.qpid_connection.log, 'warn',
                _('There is no handler for this event type: %s') % event_type)

    def _start(self, connection):
        """
        Start listening for messages. This method should probably not be called
        directly. After creating a QpidConnection and adding listeners using
        the create_listener() method, use the QpidConnection.start() method to
        start listening for messages. The QpidConnection will start up all of
        the listeners.

        :param: connection The qpid.messaging.endpoints.Connection object used
                           to establish the connection to the message broker.
        """
        self.session = connection.session('%s/%s' %
                                          (self.exchange, self.topic))
        addr_opts = {
            "create": "always",
            "node": {
                "type": "topic",
                "x-declare": {
                    "durable": True,
                    "auto-delete": True
                },
            },
        }

        connection_info = "%s / %s ; %s" % (self.exchange, self.topic,
                                            json.dumps(addr_opts))
        self.receiver = self.session.receiver(connection_info)
        log(self.qpid_connection.log, 'debug',
            _('QpidListener session info: %s') % (json.dumps(connection_info)))

        """
        A listener blocks while it waits for the next message on the queue,
        so we initiate a thread to run the listening function.
        """
        t = threading.Thread(target=self._listen)
        t.start()

    def _has_more_messages(self):
        '''
        Determine if there are any new messages in the queue.

        :returns: True if there are messages on the queue, False otherwise
        '''
        return bool(self.receiver)

    def _next_message(self):
        '''
        Wait for the next message on the queue.

        :returns: The raw message object from the message queue
        '''
        return self.receiver.fetch()

    def _acknowledge(self):
        '''
        Acknowledge a message has been received.
        '''
        self.session.acknowledge(sync=False)

    def _get_handlers(self, event_type):
        """
        Get a list of all the registered handlers that match the given event
        type.
        """
        handlers = []
        for event_type_pattern in self._handler_map:
            if fnmatch.fnmatch(event_type, event_type_pattern):
                handlers.append(self._handler_map.get(event_type_pattern))
        return handlers

    def _dispatch(self, message):
        '''
        Dispatch a message to its specific handler.

        :param: message A dictionary containing the OpenStack message
                        notification attributes (event_type, timestamp,
                        message_id, priority, publisher_id, payload)
        '''
        event_type = message.get('event_type')
        handlers = self._get_handlers(event_type)
        log_ = self.qpid_connection.log
        self._count_since_acknowledge += 1

        try:
            if handlers:
                log(log_, 'debug', _('Dispatching message to handlers'))
                log(log_, 'info', _('Qpid listener received '
                                    'message of event type: %s'
                                    % message['event_type']))
                for handler in handlers:
                    handler(self.qpid_connection.context, message)
        except Exception, e:
            log(log_, 'error', _('Error handling message: %s: %s. Message: '
                                 '%s.') % (Exception, e, message))

            # Print stack trace
            exc_type, exc_value, exc_traceback = sys.exc_info()
            log(log_, 'error', _('error type %s') % (exc_type))
            log(log_, 'error', _('error object %s') % (exc_value))
            log(log_, 'error', ''.join(traceback.format_tb(exc_traceback)))
        finally:
            if self._count_since_acknowledge > 100:
                self._count_since_acknowledge = 0
                self._acknowledge()

    def _resolve_message(self, raw_message):
        '''
        Resolves the given raw message obtained from the Qpid message queue
        into a message that can be dispatched to a handler function.

        :param: raw_message A raw message obtained from the Qpid message
                            queue
        :returns: A dictionary containing the following keys:
            event_type, timestamp, message_id, priority, publisher_id, payload
        '''
        content_type = raw_message.content_type
        if content_type == 'application/json; charset=utf8':
            content = json.loads(raw_message.content)
        elif content_type == 'amqp/map':
            content = raw_message.content
        else:
            log(self.qpid_connection.log,
                'warn',
                _('Qpid listener received unsupported message: '
                  '%s\nwith content_type %s') % (raw_message.content,
                                                 content_type))
            return None
        message = dict()
        for attr in ['event_type', 'timestamp', 'message_id', 'priority',
                     'publisher_id', 'payload']:
            message[attr] = content.get(attr)
        log(self.qpid_connection.log, 'debug', _('Qpid listener received '
                                                 'message: %s') % (message))
        return message

    def _listen(self):
        '''
        Handle messages when they arrive on the message queue.
        '''
        while True:
            try:
                if self._has_more_messages():
                    raw_message = self._next_message()
                    message = self._resolve_message(raw_message)
                    if message is None:
                        continue
                    self._dispatch(message)
                else:
                    break
            except ConnectionError, e:
                log(self.qpid_connection.log, 'warn',
                    _("Connection error: %s") % (e))
                self.qpid_connection._is_connected = False
                self.qpid_connection._reconnect()
                break
            except Exception, e:
                log(self.qpid_connection.log, 'warn',
                    _("Unknown error happens for event listener: %s") % (e))
