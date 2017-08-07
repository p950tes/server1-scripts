#! /bin/bash

DNS_SERVER="resolver1.opendns.com"

IPFILE="${HOME}/.var/externalip"
HOSTFILE="${HOME}/.var/externalhost"

IP="(none)"
HOST="(none)"

VAR_IP=`dig +short myip.opendns.com @${DNS_SERVER}`

if [ $? -eq 0 -o -n "$IP" ]; then
	IP="${VAR_IP}"
	
	VAR_HOST=`dig +short -x ${IP} @${DNS_SERVER}`
	
	if [ $? -eq 0 -a -n "$VAR_HOST" ]; then
		# remove last character
		HOST="${VAR_HOST::-1}"
	fi
fi

echo "$IP"
echo "$VAR_HOST"
exit 0

