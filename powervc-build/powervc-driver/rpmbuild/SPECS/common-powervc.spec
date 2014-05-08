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
#URL:             http://rchland.ibm.com
Source0:         common-powervc-%{version}-%{release}.tar.gz

%define srcname  common-powervc-%{version}-%{release}

BuildArch:       noarch
BuildRequires:   python


Requires:     python-glanceclient
Requires:     python-oslo-config
Requires:     python-cinderclient
Requires:     python-keystoneclient
Requires:     python-neutronclient
Requires:     python-novaclient


%description
OpenStack PowerVC Drivers provide integration support for manage-to
the PowerVC hypervisor manager. These components implement drivers
and plug-points into the OpenStack framework to support seamless
operations and resource views from the OpenStack instance running them
to a remote PowerVC hypervisor manager.

%prep


%setup -q -n common-powervc-%{version}-%{release}

%build

%pre
getent group powervc >/dev/null || groupadd -r powervc --gid 291
if ! getent passwd powervc >/dev/null; then
  useradd -u 291 -r -g powervc -G powervc,nobody -d /opt/ibm/openstack/powervc-driver -s /sbin/nologin -c "OpenStack PowerVC Daemons" powervc
fi

%install
rm -rf %{buildroot}/opt/ibm/openstack/powervc-driver
mkdir -p %{buildroot}/opt/ibm/openstack/powervc-driver
cp -r * %{buildroot}/opt/ibm/openstack/powervc-driver

mkdir -p %{buildroot}/usr/lib/python2.6/site-packages
mv %{_specdir}/powervc.pth %{buildroot}/usr/lib/python2.6/site-packages/powervc.pth

# Install config files
install -d -m 755 %{buildroot}%{_sysconfdir}/powervc
mv %{_builddir}/%{srcname}/etc/* %{buildroot}%{_sysconfdir}/powervc/
rm -Rf %{buildroot}/opt/ibm/openstack/powervc-driver/etc

# remove test code
rm -Rf %{buildroot}/opt/ibm/openstack/powervc-driver/test
rm -rf %{buildroot}/opt/ibm/openstack/powervc-driver/tools/test-*
rm -rf %{buildroot}/opt/ibm/openstack/powervc-driver/run_tests.sh

# link python source to site-packages
ln -s /opt/ibm/openstack/powervc-driver/powervc %{buildroot}/usr/lib/python2.6/site-packages/powervc

# service dirs
rm -rf %{buildroot}/var/log/powervc
mkdir -p %{buildroot}/var/log/powervc
rm -rf %{buildroot}/var/run/powervc
mkdir -p %{buildroot}/var/run/powervc
rm -rf %{buildroot}/etc/logrotate.d
mkdir -p %{buildroot}/etc/logrotate.d
cp %{buildroot}/opt/ibm/openstack/powervc-driver/logrotate.d/openstack-powervc-driver %{buildroot}/etc/logrotate.d/
rm -Rf %{buildroot}/opt/ibm/openstack/powervc-driver/logrotate.d

%files
#%defattr(640,root,powervc,640)
%dir %attr(0755, root, powervc) /opt/ibm/openstack
%dir %attr(0755, root, powervc) /opt/ibm/openstack/powervc-driver
/opt/ibm/openstack/powervc-driver/*

#%dir /usr/lib/python2.6/site-packages
/usr/lib/python2.6/site-packages/powervc.pth
/usr/lib/python2.6/site-packages/powervc

%dir %attr(0755, root, root) /etc/powervc
%dir %attr(0755, powervc, root) /var/log/powervc
%dir %attr(0755, powervc, root) /var/run/powervc
%config(noreplace) /etc/logrotate.d/openstack-powervc-driver
%config(noreplace) %attr(0640, root, powervc) %{_sysconfdir}/powervc/powervc.conf

#%config(noreplace) %attr(-, root, powervc) %{_sysconfdir}/powervc/powervc.conf


%post
chmod 755 /opt/ibm/openstack/powervc-driver/doc
chmod 755 /opt/ibm/openstack/powervc-driver/powervc
find /opt/ibm/openstack/powervc-driver -type d -print | xargs -n 1 chmod 755
find /opt/ibm/openstack/powervc-driver -type f -print | xargs -n 1 chmod 644
find /opt/ibm/openstack/powervc-driver -type d -print | xargs -n 1 chown :powervc
find /opt/ibm/openstack/powervc-driver -type f -print | xargs -n 1 chown :powervc
chmod -R 755 /opt/ibm/openstack/powervc-driver/bin


%changelog
* Tue Aug 13 2013 Humberto Rivero <hurivero@us.ibm.com> 
- Initial powervc-common packaging

* Thu Jul 18 2013 Humberto Rivero <hurivero@us.ibm.com> 
- Initial powervc packaging
