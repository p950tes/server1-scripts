#!/bin/bash

MOVIESDIR=/data/media/movies
SUBSDIR=$MOVIESDIR/Subtitles
STRICT=false

function getMovieDirs {
	ls "$MOVIESDIR" | grep -v "Subtitles"
}
function removeSuffix {
	cat - | awk -F'.' 'sub(FS $NF, x)'
}
function removeLangSuffix {
	if $STRICT; then
		cat -
	else
		cat - | awk --posix '{gsub(/[\._][a-zA-Z]{2,3}$/, "", $0)}1'
	fi
}
function getMovies {
	getMovieDirs | while read dir; do
		find "$MOVIESDIR/$dir" -type f -printf "%f\n"
	done | removeSuffix | removeLangSuffix | sort | uniq
}
function getSubtitles {
	ls "$SUBSDIR" | removeSuffix | removeLangSuffix | sort | uniq
}

if [[ "$1" == "--strict" ]]; then
	STRICT=true
fi

subtitles=$(getSubtitles)
movies=$(getMovies)

comm -23 <(echo "$subtitles") <(echo "$movies")
