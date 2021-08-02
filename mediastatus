#!/usr/bin/python

from __future__ import print_function
import os
import subprocess
from prettytable import PrettyTable

ROOTDIR = "/data/media"
MOVIESDIR = ROOTDIR + "/movies"
SERIESDIR = ROOTDIR + "/series"

class MediaDir:
    def __init__(self, path):
        self.path = path
    def getName(self):
        return os.path.basename(self.path)
    def getSize(self):
        return subprocess.check_output(["du", "-sh", self.path]).split()[0]
    def getNumFiles(self):
        numFiles = 0
        for currentDir, subDirs, files in os.walk(self.path):
            for filename in files:
                if not (filename.endswith(".srt") or filename.endswith(".sub")):
                    numFiles += 1
        return str(numFiles)

def ls(path):
    return sorted(os.walk(path).next()[1])

def movieSummary():
    print("+-------------------------------------+")
    print("|            MOVIE SUMMARY            |")

    table = PrettyTable(["Genre", "Movies", "Size"])
    table.align["Genre"] = "l"
    table.align["Movies"] = "r"
    table.align["Size"] = "r"
 
    for directory in ls(MOVIESDIR):
        if directory == "Subtitles":
            continue
        movieDir = MediaDir(MOVIESDIR + "/" + directory)
        table.add_row([movieDir.getName(), movieDir.getNumFiles(), movieDir.getSize()])

    moviesDir = MediaDir(MOVIESDIR)
    table.add_row(["==================", "======", "====="])
    table.add_row(["TOTAL", moviesDir.getNumFiles(), moviesDir.getSize()])

    print(table)

def seriesSummary():
    print("+-------------------------------------+")
    print("|           SERIES SUMMARY            |")

    table = PrettyTable(["Data", "Value"])
    table.align["Data"] = "l"
    table.align["Value"] = "r"
    
    seriesDir = MediaDir(SERIESDIR)
    table.add_row(["Number of series", len(ls(seriesDir.path))])
    table.add_row(["Number of episodes         ", seriesDir.getNumFiles()])
    table.add_row(["Total size", seriesDir.getSize()])

    print(table)

movieSummary()
seriesSummary()
