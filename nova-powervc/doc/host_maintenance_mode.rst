New Host Maintenance mode restAPI documentation for PowerVC Driver
===================================
Included documents:

- How to call restAPI to enable/disable the Host Maintenance mode

Where is the source code:

  Source code is located in powervc/nova/extension/host_maintenance_mode.py

How to enable the restAPI:

  This restAPI will be automatically linked to nova-api extension: 
  "nova/api/openstack/compute/contrib/host_maintenance_mode.py" after PowerVC installation.

How to verify if the restAPI is installed properly:

  # nova list-extensions | grep maintenance
  The result should be like the following:
  | Host-maintenance-mode      | Get and enable/disable Host maintenance mode, and evacuate all...

How to get the Host Maintenance mode:

  Method: Get
  URL: /v2/{tenant-id}/os-host-maintenance-mode/{host_name}
  Request parameters:
  	1. tenant-id: The tenant ID in a multi-tenancy cloud.
  	2. host_name: The name of a host.
  Sample:
  	/v2/ae1c0ea86c95432d95995617022e4c96/os-host-maintenance-mode/789522X_067E30B

How to enable the Host Maintenance mode:

  Method: Put
  URL: /v2/{tenant-id}/os-host-maintenance-mode/{host_name}
  Request parameters:
  	1. tenant-id: The tenant ID in a multi-tenancy cloud.
  	2. host_name: The name of a host.
  Request Body:
  	{
  		"status":"enable",
  		"migrate":"active-only"/"none"
  	}
  Request Body Description:
  	1. Set "status" to "enable" to enable the Host Maintenance mode.
  	2. Set "migrate" to "active-only" that could evacuate all the VMs to another host during the process.
  	   Set "migrate" to "none" or just ignore this parameter that will not evacuate VMs.

How to disable the Host Maintenance mode:

  Method: Put
  URL: /v2/{tenant-id}/os-host-maintenance-mode/{host_name}
  Request parameters:
  	1. tenant-id: The tenant ID in a multi-tenancy cloud.
  	2. host_name: The name of a host.
  Request Body:
  	{
  		"status":"disable"
  	}
  Request Body Description:
  	1. Set "status" to "disable" to enable the Host Maintenance mode.
