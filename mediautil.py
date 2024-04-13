#!/usr/bin/python3

import argparse
import os
import subprocess
from pathlib import Path
import sys
import json
import signal
import threading

signal.signal(signal.SIGINT, lambda sig, frame : sys.exit(1))

def is_valid_file(parser, arg) -> str:
    if os.path.isfile(arg):
        return arg
    parser.error("The file %s does not exist!" % arg)

def print_error(*args, **kwargs) -> None:
    print("ERROR: ", file=sys.stderr, end='')
    print(*args, file=sys.stderr, **kwargs)

def fatal(*args, **kwargs) -> None:
    print_error(*args, **kwargs)
    exit(1)

def verbose(*args, **kwargs) -> None:
    if ARGS.verbose:
        print(*args, file=sys.stderr, **kwargs)

def confirm() -> None:
    if ARGS.confirm:
        input('\nPress ENTER to continue or CTRL-C to abort\n')

def format_bytes(size: int, decimal_places=2) -> str:
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
        if size < 1024.0 or unit == 'TiB':
            break
        size /= 1024.0
    return f"{size:.{decimal_places}f} {unit}"

class FfmpegExecutor:
    args: list[str]

    def __init__(self, input_file_path: str) -> None:
        self.args = ['ffmpeg']
        if not ARGS.verbose:
            self.args.extend(['-loglevel', 'warning'])
        self.args.extend(['-nostdin', '-hide_banner'])
        self.args.extend(['-analyzeduration', '100000000'])
        self.args.extend(['-probesize', '100000000'])
        self.args.extend(['-i', input_file_path])
    
    def add_arg(self, argument: str) -> None:
        self.args.append(argument)
    
    def add_args(self, arguments: list[str]) -> None:
        self.args.extend(arguments)

    def execute(self) -> int:
        print(self)
        if ARGS.dry_run:
            print("(dry-run, not actually executing)")
            return 0
        process = subprocess.Popen(self.args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output_reader = threading.Thread(target=self.__read_output, args=(process,))
        output_reader.start()
        process.wait()
        output_reader.join()
        return process.returncode

    def __read_output(self, process):
        for line in iter(process.stdout.readline, b''):
            sys.stdout.write(line.decode(sys.stdout.encoding))
        process.stdout.close()

    def __str__(self) -> str:
        return ' '.join(self.args)

class Stream:
    type: str
    index: int
    raw: dict
    language: str
    title: str

    def __init__(self, raw: dict):
        self.type = raw.get("codec_type")
        self.index = int(raw.get("index"))
        self.raw = raw
        if 'tags' in raw:
            self.__parse_tags(raw['tags'])

    def __has_disposition(self, disposition: str) -> bool:
        if 'disposition' not in self.raw or disposition not in self.raw['disposition']:
            return False
        value = int(self.raw['disposition'][disposition])
        return value > 0
    
    def __parse_tags(self, tags: dict) -> None:
        self.language = tags.get('language')
        if not self.language:
            self.language = "unknown"

        self.title = tags.get('title')
    
    def get_size_in_bytes(self) -> int:
        if 'tags' not in self.raw:
            return None
        tags = self.raw['tags']
        numbytes_tags = [tag for tag in tags if tag.startswith('NUMBER_OF_BYTES')]
        if len(numbytes_tags) > 0:
            return int(tags.get(numbytes_tags[0]))
        else:
            return None
    
    def is_default(self) -> bool:
        return self.__has_disposition('default')
    def is_forced(self) -> bool:
        return self.__has_disposition('forced')
    def is_hearing_impaired(self) -> bool:
        return self.__has_disposition('hearing_impaired')
    def is_image_based_subtitle(self) -> bool:
        return self.raw.get('codec_name') in ['dvd_subtitle', 'dvb_subtitle', 'pgs_subtitle']

    def __str__(self) -> str:
        result = list()
        result.append("Stream #" + str(self.index))
        result.append(self.type)
        if self.type != 'video':
            result.append("(" + self.language + ")")
        
        result.append(self.raw.get('codec_name'))
        if self.raw.get('profile'):
            result.append("(" + self.raw.get('profile') + ")")

        if 'width' in self.raw:
            result.append(str(self.raw.get('width')) + "x" + str(self.raw.get('height')))
        
        if self.raw.get('channel_layout'):
            result.append(self.raw.get('channel_layout'))

        num_bytes = self.get_size_in_bytes()
        if num_bytes:
            result.append(format_bytes(num_bytes))
        
        if self.title:
            result.append("'" + self.title + "'")
        
        if self.is_default():
            result.append("(default)")
        if self.is_forced():
            result.append("(forced)")
        if self.is_hearing_impaired():
            result.append("(hi)")

        return ' '.join(result)


class MediaFile:
    path: str
    container: str
    format: dict
    streams: list[Stream]

    def __init__(self, path: str, format, streams: list[Stream]):
        self.path = path
        self.format = format
        self.container = os.path.splitext(path)[1][1:]
        self.streams = streams
    
    def get_video_streams(self) -> Stream:
        return [stream for stream in self.streams if stream.type == 'video']
    def get_audio_streams(self) -> Stream:
        return [stream for stream in self.streams if stream.type == 'audio']
    def get_subtitle_streams(self) -> Stream:
        return [stream for stream in self.streams if stream.type == 'subtitle']
    def get_other_streams(self) -> Stream:
        return [stream for stream in self.streams if stream.type not in ['video', 'audio', 'subtitle']]

    def __str__(self) -> str:
        video_streams = self.get_video_streams()
        audio_streams = self.get_audio_streams()
        subtitle_streams = self.get_subtitle_streams()
        other_streams = self.get_other_streams()
        result = list()
        if video_streams: 
            result.append("Video streams: \n" + '\n'.join(['   ' + str(s) for s in video_streams]))
        if audio_streams: 
            result.append("Audio streams: \n" + '\n'.join(['   ' + str(s) for s in audio_streams]))
        if subtitle_streams: 
            result.append("Subtitle streams: \n" + '\n'.join(['   ' + str(s) for s in subtitle_streams]))
        if other_streams: 
            result.append("Other streams: \n" + '\n'.join(['   ' + str(s) for s in other_streams]))
        
        return '\n'.join(result)

def parse_mediafile(filepath: str) -> MediaFile:
    cmd = ['ffprobe', '-hide_banner']
    cmd.extend(['-analyzeduration', '100000000', '-probesize', '100000000'])
    cmd.extend(['-of', 'json'])
    cmd.extend(['-show_streams', '-show_format'])
    cmd.extend([filepath])
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if result.returncode != 0:
        print_error(result.stderr.decode(sys.stdout.encoding))
        fatal("Failed to parse file info from %s" % filepath)

    ffprobe_output = result.stdout.decode(sys.stdout.encoding)
    if ARGS.verbose:
        print(ffprobe_output)
    data=json.loads(ffprobe_output)
    format = data['format']
    streams = [Stream(stream_data) for stream_data in data['streams']]

    # Validate indexes
    for i in range(len(streams)):
        if i != streams[i].index:
            fatal("The array index " + str(i) + " does not match the stream index " + str(streams[i].index))

    return MediaFile(filepath, format, streams)

def parse_args() -> argparse.Namespace:
    argparser = argparse.ArgumentParser(prog='Mediautil', description='Multi-purpose media editing tool')

    argparser.add_argument('files', metavar='FILE', type=lambda x: is_valid_file(argparser, x), nargs='+',  help='Input file')

    argparser.add_argument('--list', action='store_true', help='Prints information about the specified file')
    argparser.add_argument('--set-stream-language', nargs=2, metavar=('STREAM', 'LANGUAGE'), help='Sets stream language to the specified language')
    argparser.add_argument('--output-container', dest='output_container', help='Specify a new output container')
    argparser.add_argument('--delete-stream', metavar='stream', help='Deletes the specified stream', type=int)
    argparser.add_argument('--delete-audio-streams-except', metavar='stream', help='Deletes all audio streams except the one specified', type=int)
    argparser.add_argument('--delete-data-streams', help='Deletes the specified audio stream', action='store_true')
    argparser.add_argument('--delete-subtitles', dest='delete_subs', help='Deletes all subtitle streams', action='store_true')
    argparser.add_argument('--extract-subtitles', dest='extract_subs', help='Extract all subtitle streams', action='store_true')
    argparser.add_argument('-eds', '--extract-and-delete-subtitles', dest='extract_and_delete_subs', help='Extract and delete all subtitle streams', action='store_true')

    argparser.add_argument('--create-dir', action='store_true', help='Store the output in a directory with the same name as the input file')
    argparser.add_argument('-v', '--verbose', action='store_true', help='Verbose mode')
    argparser.add_argument('--dry-run', '--nono', action='store_true', help='Make no changes')
    argparser.add_argument('--no-confirm', dest='confirm', action='store_false', help='Disables confirmation dialog before executing')
    argparser.add_argument('--no-cleanup', dest='cleanup', action='store_false', help='Disables cleanup of old file')

    args = argparser.parse_args()
    if args.extract_and_delete_subs:
        args.extract_subs = True
        args.delete_subs = True
    return args

def extract_subtitles(input_file: MediaFile, destination_dir: str):
    subtitle_streams = input_file.get_subtitle_streams()
    if not subtitle_streams:
        print_error("No subtitle streams present")
        return
    subtitle_streams = [stream for stream in subtitle_streams if not stream.is_image_based_subtitle()]
    if not subtitle_streams:
        print_error("Only image based subtitle streams present, will not extract any subtitles")
        return

    inputfilename_without_extension = Path(input_file.path).stem

    for subtitle in subtitle_streams:
        output_file = resolve_new_subtitle_file_path(subtitle, inputfilename_without_extension, destination_dir)

        verbose("Extracting subtitle: " + str(subtitle))
        executor = FfmpegExecutor(input_file.path)
        executor.add_args(['-map', '0:' + str(subtitle.index)])
        executor.add_args(['-c', 'srt'])
        executor.add_arg(output_file)
        exitcode = executor.execute()
        if exitcode != 0:
            print_error("Failed to extract subtitle: " + str(subtitle))

def resolve_new_subtitle_file_path(subtitle: Stream, name: str, destination_dir: str) -> str:
    language_str = subtitle.language
    if subtitle.is_hearing_impaired():
        language_str += ".hi"
    if subtitle.is_forced():
        language_str += ".forced"

    output_base = destination_dir + "/" + name + "." + language_str
    output_file = output_base + ".srt"
    i = 0
    while os.path.exists(output_file):
        i += 1
        output_file = output_base + "." + str(i) + ".srt"
    return output_file

def process_file(input_file_path: str) -> None:

    print("\nProcessing '" + input_file_path + "'")
    input_file = parse_mediafile(input_file_path)

    print("\n" + str(input_file) + "\n")
    if ARGS.list:
        return

    if ARGS.output_container:
        output_container = ARGS.output_container
    else:
        output_container = input_file.container

    container_change = input_file.container != output_container

    inputfilename_without_extension = Path(input_file.path).stem
    working_dir = os.path.dirname(os.path.abspath(input_file.path))
    if ARGS.create_dir:
        working_dir = working_dir + "/" + inputfilename_without_extension

    working_file = working_dir + "/" + inputfilename_without_extension + ".new." + output_container
    verbose("Source file     : " + input_file.path)
    verbose("Working file    : " + working_file)
    if os.path.exists(working_file):
        fatal("Working file already exists: " + working_file)

    output_file = working_dir + "/" + inputfilename_without_extension + "." + output_container
    verbose("Destination file: " + output_file)

    if container_change and os.path.exists(output_file):
        fatal("Output file already exists: " + output_file)

    num_actions = 0
    action_list = list()

    executor = FfmpegExecutor(input_file.path)
    executor.add_args(['-c', 'copy'])
    executor.add_args(['-map', '0'])

    if ARGS.extract_subs:
        action_list.append("* Will extract all subtitles\n")

    if ARGS.set_stream_language:
        num_actions += 1
        stream_index = int(ARGS.set_stream_language[0])
        new_language = ARGS.set_stream_language[1]
        if stream_index >= len(input_file.streams):
            fatal("Stream index not found: " + str(ARGS.stream_index))
        stream_to_modify = input_file.streams[stream_index]
        if stream_to_modify.language == new_language:
            fatal("The specified stream already has '" + new_language + "' set as language: \n" + str(stream_to_modify))
        
        executor.add_args(['-metadata:s:' + str(stream_index), 'language=' + new_language])
        
        action_list.append("* Will update the following stream language to '" + new_language + "'\n"
                            + "   " + str(stream_to_modify) + "\n")

    if ARGS.delete_stream != None:
        num_actions += 1
        if ARGS.delete_stream >= len(input_file.streams):
            fatal("Stream index not found: " + str(ARGS.delete_stream))
        stream_to_delete = input_file.streams[ARGS.delete_stream]
        executor.add_args(['-map', '-0:' + str(stream_to_delete.index)])
        action_list.append("* Will delete the following stream:\n" 
                           + "   " + str(stream_to_delete) + "\n")
        
    if ARGS.delete_audio_streams_except != None:
        num_actions += 1
        if ARGS.delete_audio_streams_except >= len(input_file.audio_streams):
            fatal("Audio stream index not found: " + str(ARGS.delete_audio_streams_except))
        
        audio_streams_to_delete = [stream for stream in input_file.audio_streams if stream.index != ARGS.delete_audio_streams_except]
        action_list.append("* Will delete the following audio streams:")
        for stream in audio_streams_to_delete:
            action_list.append("   " + str(stream) + "\n")
            executor.add_args(['-map', '-0:' + str(stream.index)])

    if ARGS.delete_data_streams:
        num_actions += 1
        action_list.append("* Will delete data streams\n")
        executor.add_args(['-dn'])
        executor.add_args(['-map_chapters', '-1'])

    if ARGS.delete_subs:
        num_actions += 1
        action_list.append("* Will delete all subtitle streams\n")
        executor.add_arg('-sn')

    executor.add_arg(working_file)

    if not action_list:
        verbose("No actions specified")
        return
    
    print("\nACTIONS:\n")
    [print(action) for action in action_list]

    confirm()

    if not os.path.exists(working_dir) and not ARGS.dry_run:
        verbose("Creating working dir: " + working_dir)
        os.makedirs(working_dir)

    if ARGS.extract_subs:
        extract_subtitles(input_file, working_dir)

    if num_actions == 0:
        # the only action was to extract subs
        return
    
    returncode = executor.execute()

    if returncode != 0:
        fatal("ffmpeg execution failed with exit code " + str(returncode))

    print("\nffmpeg execution successful")

    cleanup(inputfile = input_file.path,
            workingfile = working_file, 
            outputfile = output_file)

def cleanup(inputfile: str, workingfile: str, outputfile: str) -> None:
    if ARGS.dry_run:
        return
    if not ARGS.cleanup:
        print("Cleanup disabled, leaving old file behind.")
        print("Original file: " + inputfile)
        print("Modified file: " + workingfile)
        return

    if not os.path.exists(workingfile):
        fatal(workingfile + " does not exist. Aborting cleanup")

    verbose("Deleting " + inputfile)
    os.unlink(inputfile)

    verbose("Moving " + workingfile + " -> " + outputfile)
    os.replace(workingfile, outputfile)

ARGS = parse_args()
verbose('Arguments:\n  ' + '\n  '.join(f'{k}={v}' for k, v in vars(ARGS).items() if v != None) + "\n")

if len(ARGS.files) > 1:
    print("Input files:")
    print('  ' + '\n  '.join(ARGS.files))

for file in ARGS.files:
    process_file(file)
    if len(ARGS.files) > 1:
        print("---")
