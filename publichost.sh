#! /bin/bash

DNS_SERVER="resolver1.opendns.com"

function resolve_external_ip {
	local ip
	ip=$(dig +short myip.opendns.com "@$DNS_SERVER") || return 1
	[ -z "$ip" ] && return 1
	echo "$ip"
}
function resolve_external_hostname {
	local ip hostname
	ip=$1
	hostname=$(dig +short -x "$ip" "@$DNS_SERVER") || return 1
	[ -z "$hostname" ] && return 1
	# remove last character, which is always a '.'
	echo "${hostname::-1}"
}

if ip=$(resolve_external_ip); then
	host=$(resolve_external_hostname "$ip")
fi

echo "${ip:-(none)}"
echo "${host:-(none)}"
