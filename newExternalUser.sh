#!/bin/bash

function ensureRoot {
	if [ "$EUID" -ne 0 ]; then
		echo "Error: root permissions are required" 1>&2
		exit 1
	fi
}
function addUser {
	addcmd="useradd -g sftp-external -d /srv/sftp -s /usr/sbin/nologin $USER"
	echo -e "Creating user\n$addcmd"
	$addcmd
}
function addUserToGroups {
	echo -e "\nAdding user to groups"
	groups="media software www-external sftp-external"
	
	for group in $groups; do
		cmd="usermod -a -G $group $USER"
		echo "$cmd"
		$cmd
	done
}
function setUserPassword {
	echo -e "\nSetting user password"
	numtries=0
	while ! passwd "$USER"; do
		echo "Setting password failed, try again."
		numtries=$((numtries + 1))
		if [ $numtries -gt 3 ]; then 
		   echo "Giving up, please set password for user $USER manually using passwd"
		   exit 1
	   fi
	done
}

ensureRoot

USER=${1}

while [ -z "$USER" ]; do
	printf "Enter username: "
	read USER
done

addUser
addUserToGroups

setUserPassword

