#!/usr/bin/python

import argparse
from datetime import datetime, timedelta
import re
import subprocess
import time

LOGPATH = "/var/log/sftp.log"
FILTERS = [": opendir ", ": closedir ", ": close "]

DATETIME_PATTERN = re.compile("^\d+-\d+-\d+ \d+:\d+:\d+")
USER_PATTERN = re.compile("session opened for local user ([\w\.]+) from \[")
SESSIONID_PATTERN = re.compile("\[(\d+)\]")
TYPE_PATTERN = re.compile("\[\d+\]: (\w+) ")
DETAILS_PATTERN = re.compile("\[\d+\]: \w+ \"(.+)\"")

SESSIONS_DICT = dict()
SESSIONS_LIST = list()

class LogEntry:
    def __init__(self, line):
        self.line = line

    def getUser(self):
        return self.__getMatch(USER_PATTERN)
    def getTime(self):
        return self.__getMatch(DATETIME_PATTERN)
    def getSessionId(self):
        return self.__getMatch(SESSIONID_PATTERN)

    def getType(self):
        if ": session opened " in self.line:
            return "sessionOpen"
        elif ": session closed " in self.line:
            return "sessionClose"
        else:
            return self.__getMatch(TYPE_PATTERN)
    
    def getDetails(self):
        return self.__getMatch(DETAILS_PATTERN)

    def __getMatch(self, pattern):
        matches = pattern.findall(self.line)
        if len(matches) > 0:
            return matches[0]
        return ""

class Session:
    start = ""
    end = ""
    user = ""
    def __init__(self, sessionId):
        self.id = sessionId
        self.userActions = list()
    def addUserAction(self, time, actionType, details):
        self.userActions.append(UserAction(time, actionType, details))

    def createSummary(self):
        result =  "%s [%s] %s - %s\n" % (self.user, self.id, self.start, self.end)
        for action in self.userActions:
            result += "[" + action.time + "] " + action.type + " [" + action.details + "]\n"
        return result

class UserAction:
    def __init__(self, time, aType, details):
        self.time = time
        self.type = aType
        self.details = details


def processLogFile():
    with open(LOGPATH, "r") as logfile:
        for line in logfile:
            if not ARGS.date or line.startswith(ARGS.date):
                if any(filtr in line for filtr in FILTERS):
                    continue
                processLine(line)

def processLine(line):
    entry = LogEntry(line)
    sessionId = entry.getSessionId()
    if not sessionId:
        print("WARNING: Failed to get sessionId from line, will skip: \n" + line)
        return
    
    session = getSession(sessionId)

    tType = entry.getType()
    time = entry.getTime()

    if tType == "sessionOpen":
        session.user = entry.getUser()
        session.start = time
    elif tType == "sessionClose":
        session.end = time
    elif tType == "open":
        session.addUserAction(time, tType, entry.getDetails())
    
def getSession(sessionId):
    if sessionId in SESSIONS_DICT:
        return SESSIONS_DICT[sessionId]
    else:
        newSession = Session(sessionId)
        SESSIONS_DICT[sessionId] = newSession
        SESSIONS_LIST.append(newSession)
        return newSession

def getSessionList():
    return SESSIONS_LIST
def sessionsFound():
    if len(getSessionList()) > 0:
        return True
    else:
        return False

def createSummary():
    sessionList = getSessionList()
    if ARGS.date:
        result = "Summary " + ARGS.date
    else:
        result = "Summary"

    numSessions = str(len(sessionList))
    result += " (" + numSessions + " sessions)\n\n"
    
    for session in sessionList:
        result += session.createSummary() + "\n"
    return result

def parseArguments():
    global ARGS
    
    parser = argparse.ArgumentParser(description='Process SFTP log.')

    parser.add_argument("-q", '--quiet', action="store_true", help="Suppress any output to STDOUT")
    parser.add_argument("-m", '--mail', help="Sends the parsing results to the specified email address")
    
    dategroup = parser.add_mutually_exclusive_group(required = False)
    dategroup.add_argument("-d", "--date", type=lambda d: datetime.strftime(datetime.strptime(d, "%Y-%m-%d"), "%F"), help="Only parse logs from DATE")
    dategroup.add_argument("--today", action="store_const", dest="date", const=datetime.now().strftime("%F"), help="Parse logs from today")
    dategroup.add_argument("--yesterday", action="store_const", dest="date", const=(datetime.now() - timedelta(days=1)).strftime("%F"), help="Parse logs from yesterday")

    parser.set_defaults(quiet=False)
    ARGS = parser.parse_args()

def sendEmail(emailContents):
    subject = "server1 SFTP Summary"
    if ARGS.date:
        subject += " " + ARGS.date

    mailProcess = subprocess.Popen(["mailx", "-s " + subject, ARGS.mail], stdin=subprocess.PIPE)
    mailProcess.communicate(emailContents)


#--------------------

parseArguments()
processLogFile()
summary = createSummary()

if sessionsFound():
    exitCode = 0
    if ARGS.mail:
        sendEmail(summary)
else:
    exitCode = 1

if not ARGS.quiet:
    print(summary)

exit(exitCode)

