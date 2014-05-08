%global release_name icehouse
%global snapdate 20131118
%global git_revno r169
%global snaptag %{?milestone:%{milestone}}~%{snapdate}.%{git_revno}
%global with_doc %{!?_without_doc:1}%{?_without_doc:0}

Name:            rpmName
Version:         2014.1
Release:         1.2.ibm.bldQualifier
Summary:         IBM PowerVC 

License:         IBM LPP
Source0:         cinder-powervc-%{version}-%{release}.tar.gz

%define srcname  cinder-powervc-%{version}-%{release}

BuildArch:       noarch
BuildRequires:   python


Requires:        openstack-cinder >= %{version} 
Requires:        openstack-common-ibm-powervc 



%description
OpenStack PowerVC Drivers provide integration support for manage-to
the PowerVC hypervisor manager. These components implement drivers
and plug-points into the OpenStack framework to support seamless
operations and resource views from the OpenStack instance running them
to a remote PowerVC hypervisor manager.

%prep


%setup -q -n cinder-powervc-%{version}-%{release}

%build

%pre
usermod -a -G powervc cinder
usermod -a -G cinder powervc

%install
rm -rf %{buildroot}/opt/ibm/openstack/powervc-driver
mkdir -p %{buildroot}/opt/ibm/openstack/powervc-driver
cp -r * %{buildroot}/opt/ibm/openstack/powervc-driver
rm -f %{buildroot}/opt/ibm/openstack/powervc-driver/powervc/__init__.py

# init.d scripts
mkdir -p %{buildroot}/etc/rc.d/init.d
cp %{buildroot}/opt/ibm/openstack/powervc-driver/init/openstack-cinder-powervc %{buildroot}/etc/rc.d/init.d/
rm -Rf %{buildroot}/opt/ibm/openstack/powervc-driver/init

rm -Rf %{buildroot}/opt/ibm/openstack/powervc-driver/etc


# remove test code
rm -Rf %{buildroot}/opt/ibm/openstack/powervc-driver/test
rm -rf %{buildroot}/opt/ibm/openstack/powervc-driver/tools/test-*
rm -rf %{buildroot}/opt/ibm/openstack/powervc-driver/run_tests.sh


%files
%dir /opt/ibm/openstack/powervc-driver
/opt/ibm/openstack/powervc-driver/*
%attr(0755, root, root) /etc/rc.d/init.d/openstack-cinder-powervc


%post
find /opt/ibm/openstack/powervc-driver/powervc -type d -print | xargs -n 1 chmod 755
find /opt/ibm/openstack/powervc-driver/powervc -type f -print | xargs -n 1 chmod 644
find /opt/ibm/openstack/powervc-driver -type d -print | xargs -n 1 chown :powervc
find /opt/ibm/openstack/powervc-driver -type f -print | xargs -n 1 chown :powervc
chmod 755 /opt/ibm/openstack/powervc-driver/bin
chmod 755 /opt/ibm/openstack/powervc-driver/bin/cinder-powervc

%changelog
* Tue Aug 13 2013 Humberto Rivero <hurivero@us.ibm.com> 
- Initial powervc-cinder packaging

* Thu Jul 18 2013 Humberto Rivero <hurivero@us.ibm.com> 
- Initial powervc packaging
