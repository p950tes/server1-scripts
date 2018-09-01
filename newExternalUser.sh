#!/bin/bash

# Set the script to exit on error
set -e

user=${1}

while [ -z "$user" ]; do
	printf "Enter username: "
	read user
done

groups="media software www-external sftp-external"

addcmd="useradd -g sftp-external -d /srv/sftp -s /usr/sbin/nologin $user"
echo -e "Creating user\n$addcmd"
$addcmd

echo -e "\nAdding user to groups"

for group in $groups; do
	cmd="usermod -a -G $group $user"
	echo "$cmd"
	$cmd
done

echo -e "\nSetting user password"

while ! passwd "$user"; do
	echo "Setting password failed, try again."
done

