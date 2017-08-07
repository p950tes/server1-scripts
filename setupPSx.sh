#!/bin/bash

red='\[\033[01;31m\]'
orange='\[\e[01;38;5;202m\]'
green='\[\033[01;32m\]'
blue='\[\033[01;34m\]'
reset='\[\033[00m\]'

if [ $(id -u) -eq 0 ]; then
	str="${orange}\u@\h${reset}:${blue}\w${reset}"
	char="#"
else
	str="${green}\u@\h${reset}:${blue}\w${reset}"
	char="$"
fi

end='$(if [ $? -eq 0 ]; then printf "'${green}'"; else printf "'$red'"; fi)'"$char$reset "

export PS1='${debian_chroot:+($debian_chroot)}'"$str$end"
unset color_prompt force_color_prompt red green blue reset str char end

