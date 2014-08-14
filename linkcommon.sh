# Copyright 2013 IBM Corp.

#!/bin/sh
#
# This script is for link powervc common code to each powervc modules.
#

target="common-powervc/powervc/common"
pushd .
cd $target && target=`pwd`
popd

declare -a components
declare -a linktopaths

components=(
    nova
    cinder
    glance
    neutron
);

pvc="powervc"


for ((i=0; i<${#components[@]}; i++));
do
    linktopaths[$i]="${components[$i]}-$pvc/$pvc"
    if [[ $1 == '-del' ]]; then
        rm ${linktopaths[$i]}/common
    else
        ln -s $target ${linktopaths[$i]}
    fi
done;

