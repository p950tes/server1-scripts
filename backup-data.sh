#! /bin/bash

DATADISK="/mnt/data-disk"
BACKUPDISK="/mnt/backup-disk"

SRC="${DATADISK}/"
DEST="${BACKUPDISK}/backup/data-disk/"
EXCLUDE_FILE="/etc/backup-custom/exclude/exclude-data"
ON_SUCCESS_UNMOUNT_BACKUP=true
CRON=false
MODIFIERS="--archive --verbose --human-readable --delete-delay --exclude-from ${EXCLUDE_FILE}"

function verifySourceMount {
	echo "Checking if data disk [${DATADISK}] is mounted."
	mountpoint -q $DATADISK
	ismounted=$?
	if [ $ismounted -ne 0 ]; then
		echo "Data disk is not mounted."
		exit 1
	fi
}
function verifyBackupMount {

	echo "Checking if backup disk [${BACKUPDISK}] is mounted."
	mountpoint -q $BACKUPDISK
	ismounted=$?
	if [ $ismounted -ne 0 ]; then
		echo "Backup disk not mounted, attempting to mount..."
	
		mount $BACKUPDISK
		MOUNT_SUCCESS=$?
		
		if [ $MOUNT_SUCCESS -ne 0 ]; then
			echo "Failed to mount backup disk"
			exit 1
		else
			echo "Backup disk successfully mounted at ${BACKUPDISK}."
		fi
	fi
}
function unmountBackup {
	# Try to unmount backup disk
	if [ "$ON_SUCCESS_UNMOUNT_BACKUP" = true ]; then
		echo "Unmounting ${BACKUPDISK}..."
		umount $BACKUPDISK
	fi
}
function verifyDirectories {

	echo "Verifying existence of source and backup directories..."
	if [ ! -d "$SRC" -o ! -d "$DEST" ]; then
		echo "Source or backup directory does not exist!"
		exit 1
	fi
}
function ensureRoot {
	if [ "$EUID" -ne 0 ]; then
		echo "Has to be run as root"
		exit 1
	fi
}
function buildBackupCommand {
	if ! $CRON; then
		MODIFIERS+=" --progress"
	fi	

	echo "rsync ${MODIFIERS} ${SRC} ${DEST}"
}
function executeBackup {
	echo -e "Executing backup...\n"

	$BACKUP_COMMAND
}
function getBackupSize {
	du -sb "$DEST" | awk '{print $1}'
}
function formatBytes {
	echo "$(echo "$1" | numfmt --to=iec-i)B"
}

####################
##	 EXECUTION 
####################

# Ensure that user is root
ensureRoot

# Parse arguments
while [[ $# -gt 0 ]]; do
	case $1 in
		--cron)
			CRON=true
			;;
		--test)
			MODIFIERS+=" --dry-run"
			;;
	esac
	shift 1
done

BACKUP_COMMAND="$(buildBackupCommand)"
echo "$BACKUP_COMMAND"
read -p "Press [Enter] to continue."

# Check if data disk is mounted
verifySourceMount

# Check if backup disk is mounted
verifyBackupMount

# Check if directories exist.
verifyDirectories
	
size_before=$(getBackupSize)
echo -e "\nTotal backup size before backup: $(formatBytes $size_before)\n"

# Execute backup.
executeBackup

size_after=$(getBackupSize)
size_difference=$(expr $size_after - $size_before)

echo -e "\nTotal backup size after backup: $(formatBytes $size_after)"
echo -e "Backup size difference: $(formatBytes $size_difference)\n"

unmountBackup

echo "Backup completed successfully."
exit 0

