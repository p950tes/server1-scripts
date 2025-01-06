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

# Specify how many microseconds are analyzed to probe the input. 
# A higher value will enable detecting more accurate information, but will increase latency. 
# It defaults to 5,000,000 microseconds = 5 seconds.
FFMPEG_ANALYZEDURATION=str(100_000_000)

# Set probing size in bytes, i.e. the size of the data to analyze to get stream information. 
# A higher value will enable detecting more information in case it is dispersed into the stream, but will increase latency. 
# Must be an integer not lesser than 32. It is 5000000 by default.
FFMPEG_PROBESIZE=str(100_000_000)

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
    print()
    if ARGS.confirm:
        input('Press ENTER to continue or CTRL-C to abort\n')

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
        self.args.extend(['-analyzeduration', FFMPEG_ANALYZEDURATION])
        self.args.extend(['-probesize', FFMPEG_PROBESIZE])
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
    codec_name: str
    index: int
    raw: dict
    tags: dict = dict()
    language: str = "unknown"
    title: str = ""
    filename: str = ""
    mimetype: str = ""

    def __init__(self, raw: dict):
        self.type = raw.get("codec_type")
        self.codec_name = raw.get("codec_name")
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
        self.tags = tags
        if tags.get('language'):
            self.language = tags.get('language')
        if tags.get('title'):
            self.title = tags.get('title')
        if tags.get('filename'):
            self.filename = tags.get('filename')
        if tags.get('mimetype'):
            self.mimetype = tags.get('mimetype')
    
    def get_size_in_bytes(self) -> int:
        if 'tags' not in self.raw:
            return None
        tags = self.raw['tags']
        numbytes_tags = [tag for tag in tags if tag.startswith('NUMBER_OF_BYTES')]
        if len(numbytes_tags) > 0:
            return int(tags.get(numbytes_tags[0]))
        else:
            return None
    
    def is_video(self) -> bool:
        return self.type == 'video'
    def is_audio(self) -> bool:
        return self.type == 'audio'
    def is_subtitle(self) -> bool:
        return self.type == 'subtitle'
    def is_unknown_type(self) -> bool:
        return self.type not in ['video', 'audio', 'subtitle']
    
    def is_image(self) -> bool:
        return self.codec_name in ['mjpeg', 'png']
    
    def is_default(self) -> bool:
        return self.__has_disposition('default')
    def is_forced(self) -> bool:
        return self.__has_disposition('forced') or "FORCED" in self.title.upper()
    def is_hearing_impaired(self) -> bool:
        return self.__has_disposition('hearing_impaired') or "SDH" in self.title.upper()
    def is_image_based_subtitle(self) -> bool:
        return self.is_subtitle() and self.raw.get('codec_name') in ['dvd_subtitle', 'dvb_subtitle', 'pgs_subtitle', 'hdmv_pgs_subtitle']

    def __str__(self) -> str:
        result = list()
        result.append("Stream #" + str(self.index))
        result.append(self.type)
        if self.language and (self.is_audio() or self.is_subtitle()):
            result.append("(" + self.language + ")")
        
        if self.codec_name:
                result.append(self.codec_name)
        
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
        
        if self.filename:
            result.append("'" + self.filename + "'")
        if self.mimetype:
            result.append("(" + self.mimetype + ")")

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
        return [stream for stream in self.streams if stream.is_video()]
    def get_audio_streams(self) -> Stream:
        return [stream for stream in self.streams if stream.is_audio()]
    def get_subtitle_streams(self) -> Stream:
        return [stream for stream in self.streams if stream.is_subtitle()]
    def get_other_streams(self) -> Stream:
        return [stream for stream in self.streams if stream.is_unknown_type()]

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
    cmd.extend(['-analyzeduration', FFMPEG_ANALYZEDURATION, '-probesize', FFMPEG_PROBESIZE])
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
    argparser.add_argument('--delete-stream', metavar='stream', help='Deletes the specified stream')
    argparser.add_argument('--delete-audio-streams-except', metavar='stream', help='Deletes all audio streams except the one specified', type=int)
    argparser.add_argument('--delete-data-streams', help='Deletes all data streams', action='store_true')
    argparser.add_argument('--delete-image-streams', help='Deletes all image streams', action='store_true')
    argparser.add_argument('--delete-subs', dest='delete_subs', help='Deletes all subtitle streams', action='store_true')
    argparser.add_argument('--extract-subs', dest='extract_subs', help='Extract all subtitle streams', action='store_true')
    argparser.add_argument('-eds', '--extract-and-delete-subs', dest='extract_and_delete_subs', help='Extract and delete all subtitle streams', action='store_true')

    argparser.add_argument('-d', '--create-dir', action='store_true', help='Store the output in a directory with the same name as the input file')
    argparser.add_argument('-v', '--verbose', action='store_true', help='Verbose mode')
    argparser.add_argument('--dry-run', '--nono', action='store_true', help='Make no changes')
    argparser.add_argument('--no-confirm', dest='confirm', action='store_false', help='Disables confirmation dialog before executing')
    argparser.add_argument('--no-cleanup', dest='cleanup', action='store_false', help='Disables cleanup of old file')

    args = argparser.parse_args()
    if args.extract_and_delete_subs:
        args.extract_subs = True
        args.delete_subs = True
    
    if args.dry_run:
        args.confirm = False

    if args.delete_stream:
        if "," in args.delete_stream:
            args.delete_stream = list(map(int, args.delete_stream.split(",")))
        else:
            args.delete_stream = [args.delete_stream]
    
    return args

def extract_subtitles(input_file: MediaFile, destination_dir: str):
    subtitle_streams = input_file.get_subtitle_streams()
    if not subtitle_streams:
        print("WARNING: No subtitle streams present")
        return
    subtitle_streams = [stream for stream in subtitle_streams if not stream.is_image_based_subtitle()]
    if not subtitle_streams:
        print("WARNING: Only image based subtitle streams present, will not extract any subtitles")
        return

    inputfilename_without_extension = Path(input_file.path).stem

    for subtitle in subtitle_streams:
        output_file = resolve_new_subtitle_file_path(subtitle, inputfilename_without_extension, destination_dir)

        print("Extracting subtitle: " + str(subtitle))
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
        language_str += ".sdh"
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

    num_actions = 0
    action_list = list()

    executor = FfmpegExecutor(input_file.path)
    executor.add_args(['-c', 'copy'])
    executor.add_args(['-map', '0'])

    if container_change:
        num_actions += 1
        action_list.append(" * Will change container from " + input_file.container + " to " + output_container)

    if ARGS.extract_subs:
        action_list.append(" * Will extract all subtitles")
        image_based_subs = [stream for stream in input_file.get_subtitle_streams() if stream.is_image_based_subtitle()]
        if image_based_subs:
            action_list.append("   WARNING: The following subtitles are image based and will not be extracted:")
            for sub in image_based_subs:
                action_list.append("    - " + str(sub))

    if ARGS.set_stream_language:
        stream_index = int(ARGS.set_stream_language[0])
        new_language = ARGS.set_stream_language[1]
        if stream_index >= len(input_file.streams):
            fatal("Stream index not found: " + str(ARGS.stream_index))
        stream_to_modify = input_file.streams[stream_index]
        if stream_to_modify.language == new_language:
            fatal("The specified stream already has '" + new_language + "' set as language: \n" + str(stream_to_modify))
        
        num_actions += 1
        action_list.append(" * Will update the following stream language to '" + new_language + "'" + "   " + str(stream_to_modify))
        
        executor.add_args(['-metadata:s:' + str(stream_index), 'language=' + new_language])

    if ARGS.delete_stream != None:
        for index in ARGS.delete_stream:
            if index >= len(input_file.streams):
                fatal("Stream index not found: " + str(index))
            num_actions += 1
            stream_to_delete = input_file.streams[index]
            executor.add_args(['-map', '-0:' + str(stream_to_delete.index)])
            action_list.append(" * Will delete the following stream:" + "   " + str(stream_to_delete))
        
    if ARGS.delete_audio_streams_except != None:
        if ARGS.delete_audio_streams_except > len(input_file.get_audio_streams()):
            fatal("Audio stream index not found: " + str(ARGS.delete_audio_streams_except))
        
        audio_streams_to_delete = [stream for stream in input_file.get_audio_streams() if stream.index != ARGS.delete_audio_streams_except]
        if audio_streams_to_delete:
            num_actions += 1
            action_list.append(" * Will delete the following audio streams:")
            for stream in audio_streams_to_delete:
                action_list.append("    - " + str(stream))
                executor.add_args(['-map', '-0:' + str(stream.index)])

    if ARGS.delete_image_streams:
        image_streams_to_delete = [stream for stream in input_file.get_video_streams() if stream.is_image()]
        if image_streams_to_delete:
            num_actions += 1
            action_list.append(" * Will delete the following image video streams:")
            for stream in image_streams_to_delete:
                action_list.append("    - " + str(stream))
                executor.add_args(['-map', '-0:' + str(stream.index)])

    if ARGS.delete_data_streams:
        num_actions += 1
        action_list.append(" * Will delete data streams")
        executor.add_args(['-dn'])
        executor.add_args(['-map_chapters', '-1'])

    if ARGS.delete_subs:
        if len(input_file.get_subtitle_streams()) > 0:
            num_actions += 1
            action_list.append(" * Will delete all subtitle streams")
            executor.add_arg('-sn')
        else:
            action_list.append(" * Requested deletion of all subtitle streams but none exists")

    if not action_list:
        verbose("No actions specified")
        return
    
    print("\nACTIONS:")
    [print(action) for action in action_list]

    option_list = []
    if ARGS.dry_run:     option_list.append(" * Dry-run mode, will not perform any actions")
    if ARGS.create_dir:  option_list.append(" * Will create a new directory with the same name as the video file") 
    if not ARGS.cleanup: option_list.append(" * Cleanup disabled, will leave the source file behind, unmodified")

    if option_list:
        print("\nOPTIONS:")
        [print(option) for option in option_list]

    confirm()

    inputfilename_without_extension = Path(input_file.path).stem
    
    working_dir = os.path.dirname(os.path.abspath(input_file.path))
    if ARGS.create_dir:
        working_dir = working_dir + "/" + inputfilename_without_extension

    working_file = working_dir + "/" + inputfilename_without_extension + ".new." + output_container
    verbose("Working file    : " + working_file)
    if os.path.exists(working_file):
        fatal("Working file already exists: " + working_file)

    output_file = working_dir + "/" + inputfilename_without_extension + "." + output_container
    verbose("Destination file: " + output_file)

    if container_change and os.path.exists(output_file):
        fatal("Output file already exists: " + output_file)


    if not os.path.exists(working_dir) and not ARGS.dry_run:
        verbose("Creating working dir: " + working_dir)
        os.makedirs(working_dir)

    if ARGS.extract_subs:
        extract_subtitles(input_file, working_dir)

    if num_actions == 0:
        # the only action was to extract subs
        return
    
    print("Performing selected actions on source file")
    executor.add_arg(working_file)
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
