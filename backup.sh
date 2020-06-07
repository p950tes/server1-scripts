#! /bin/bash

BACKUPDISK="/mnt/backup-disk"
BACKUPDIR="$BACKUPDISK/backup/"

SOURCES="/mnt/data-disk /etc /home /root"

EXCLUDE_FILE="/etc/backup-custom/exclude"

ON_SUCCESS_UNMOUNT_BACKUP=true

function ensureRoot {
	if [ "$EUID" -ne 0 ]; then
		echo "Has to be run as root"
		exit 1
	fi
}

function verifyBackup {

	echo "Checking if backup disk [${BACKUPDISK}] is mounted."
	if ! mountpoint -q $BACKUPDISK; then
		echo "Backup disk not mounted, attempting to mount..."
	
		if mount $BACKUPDISK; then
			echo "Backup disk successfully mounted at ${BACKUPDISK}."
		else
			echo "Failed to mount backup disk"
			exit 1
		fi
	fi

	# Validate that the directory exists
	validateDirectory "$BACKUPDIR"
}

function validateSources {
	for dir in $SOURCES; do
		validateDirectory "$dir"
	done
}
function validateDirectory {
	if [ ! -d "$1" ]; then
		echo "Directory $1 does not exist!"
		exit 1
	fi
}

function addModifier {
	if [ ! -z "$MODIFIERS" ]; then
		MODIFIERS+=" "
	fi
	MODIFIERS+="$1"
}
function buildBackupCommand {
	addModifier "--archive"
	addModifier "--acls"
	addModifier "--verbose"
	addModifier "--human-readable"
	addModifier "--delete-delay"
	addModifier "--progress"
	addModifier "--exclude-from ${EXCLUDE_FILE}"

	BACKUP_COMMAND="rsync ${MODIFIERS} ${SOURCES} ${BACKUPDIR}"
}
function getBackupSize {
	du -sb "$BACKUPDIR" | awk '{print $1}'
}
function formatBytes {
	echo "$(echo "$1" | numfmt --to=iec-i)B"
}
function unmountBackup {
	if $ON_SUCCESS_UNMOUNT_BACKUP; then
		echo "Unmounting ${BACKUPDISK}..."
		umount $BACKUPDISK
	fi
}
function confirm {
	response="no"
	while [ ! -z "$response" ]; do
		read -p "Press [Enter] to continue. " response
	done
}


####################
##	 EXECUTION 
####################

# Ensure that user is root
ensureRoot

# Parse arguments
while [[ $# -gt 0 ]]; do
	case $1 in
		--test)
			addModifier "--dry-run"
			ON_SUCCESS_UNMOUNT_BACKUP=false
			;;
		--no-unmount)
			ON_SUCCESS_UNMOUNT_BACKUP=false
			;;
	esac
	shift 1
done

# Check if directories exist.
validateSources

buildBackupCommand

echo -e "-----------------------------------" 
echo -e "---------- SYSTEM BACKUP ----------" 
echo -e "-----------------------------------" 

echo -e "SOURCES:\t $SOURCES"
echo -e "DESTINATION:\t $BACKUPDIR"
echo -e "SETTINGS:\t $MODIFIERS"
echo -e "-----------------------------------\n" 

confirm

# Check if backup disk is mounted
verifyBackup

size_before=$(getBackupSize)
echo -e "\nTotal backup size before backup: $(formatBytes $size_before)\n"

# Execute backup.
echo -e "Executing backup...\n"
$BACKUP_COMMAND

size_after=$(getBackupSize)
size_difference=$(expr $size_after - $size_before)

echo -e "\nTotal backup size after backup: $(formatBytes $size_after)"
echo -e "Backup size difference: $(formatBytes $size_difference)\n"

unmountBackup

echo "Backup completed successfully."
exit 0

