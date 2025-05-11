#!/bin/bash

function clean {
	sed 's/^[^A-Z]*//g' | sed -r 's/\s+/ /g' | sed 's/:\s*/:/g'
}

jails=$(fail2ban-client status | clean | grep "Jail list" | cut -d':' -f2 | sed 's/,//g')

echo "Jails: $jails"

for jail in $jails; do
	echo -e "\033[0;31m$jail\033[0m"
	status=$(fail2ban-client status $jail | clean)
	num_banned=$(echo "$status" | grep "Currently banned" | cut -d':' -f2)
	echo " * Banned: $num_banned"
	if [ "$num_banned" -gt 0 ]; then
		banned=$(echo "$status" | grep "Banned IP list" | cut -d':' -f2-)
		echo " * IP(s): $banned"
	fi
	echo 
done

echo "View status of a jail: fail2ban-client status {jail}"
echo "To unban someone: fail2ban-client set {jail} unbanip {ip}"

