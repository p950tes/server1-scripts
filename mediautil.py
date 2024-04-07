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
    if ARGS.dry_run:
        print("Dry-run. Exiting.")
        exit(0)
    if ARGS.confirm:
        input('\nPress ENTER to continue or CTRL-C to abort\n')

def format_bytes(size: int, decimal_places=2) -> str:
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
        if size < 1024.0 or unit == 'TiB':
            break
        size /= 1024.0
    return f"{size:.{decimal_places}f} {unit}"

class ProcessExecutor:
    def execute(self, args: list):
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output_reader = threading.Thread(target=self.__read_output, args=(process,))
        output_reader.start()
        process.wait()
        output_reader.join()
        return process.returncode

    def __read_output(self, process):
        for line in iter(process.stdout.readline, b''):
            sys.stdout.write(line.decode(sys.stdout.encoding))
        process.stdout.close()

class Stream:
    def __init__(self, type_index: int, raw: dict):
        self.type = raw.get("codec_type")
        self.type_index = type_index
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
    
    def is_image_based_subtitle(self) -> bool:
        return self.raw.get('codec_name') in ['dvd_subtitle', 'dvb_subtitle', 'pgs_subtitle']

    def __str__(self) -> str:
        result = list()
        result.append("Stream #" + str(self.type_index))
        if self.language:
            result.append("(" + self.language + ")")
        elif self.type != 'video':
            result.append("(unknown)")
        
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
        
        if self.__has_disposition('default'):
            result.append("(default)")
        if self.__has_disposition('forced'):
            result.append("(forced)")
        if self.__has_disposition('hearing_impaired'):
            result.append("(hi)")

        return ' '.join(result)


class MediaFile:
    def __init__(self, path: str, format, video_streams: list[Stream], audio_streams: list[Stream], subtitle_streams: list[Stream], other_streams: list[Stream]):
        self.path = path
        self.format = format
        self.container = os.path.splitext(path)[1][1:]
        self.video_streams = video_streams
        self.audio_streams = audio_streams
        self.subtitle_streams = subtitle_streams
        self.other_streams = other_streams
    
    @staticmethod
    def parse(filepath):
        cmd = ['ffprobe', '-hide_banner']
        cmd.extend(['-analyzeduration', '100000000', '-probesize', '100000000'])
        cmd.extend(['-of', 'json'])
        cmd.extend(['-show_streams', '-show_format'])
        cmd.extend([filepath])
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if result.returncode != 0:
            print_error(result.stderr.decode(sys.stdout.encoding))
            fatal("Failed to parse file info from %s" % filepath)

        data=json.loads(result.stdout.decode(sys.stdout.encoding))
        format = data['format']
        video_streams = list()
        audio_streams = list()
        subtitle_streams = list()
        other_streams = list()

        for stream in data['streams']:

            match stream['codec_type']:
                case 'video':
                    video_streams.append(Stream(len(video_streams), stream))
                case 'audio':
                    audio_streams.append(Stream(len(audio_streams), stream))
                case 'subtitle':
                    subtitle_streams.append(Stream(len(subtitle_streams), stream))
                case _:
                    other_streams.append(Stream(len(other_streams), stream))

        return MediaFile(filepath, format, video_streams, audio_streams, subtitle_streams, other_streams)
    
    def __str__(self) -> str:
        result = list()
        result.append("Video streams: \n" + '\n'.join(['   ' + str(s) for s in self.video_streams]))
        result.append("Audio streams: \n" + '\n'.join(['   ' + str(s) for s in self.audio_streams]))
        if len(self.subtitle_streams) > 0: 
            result.append("Subtitle streams: \n" + '\n'.join(['   ' + str(s) for s in self.subtitle_streams]))
        if len(self.other_streams) > 0: 
            result.append("Other streams: \n" + '\n'.join(['   ' + str(s) for s in self.other_streams]))
        
        return '\n'.join(result)

def parse_args() -> argparse.Namespace:
    argparser = argparse.ArgumentParser(prog='Mediautil', description='Multi-purpose media editing tool')

    argparser.add_argument('files', metavar='FILE', type=lambda x: is_valid_file(argparser, x), nargs='+',  help='Input file')

    argparser.add_argument('--list', action='store_true', help='Prints information about the specified file')
    argparser.add_argument('--set-audio-lang', nargs=2, metavar=('STREAM', 'LANGUAGE'), help='Sets audio language to the specified language')
    argparser.add_argument('--output-container', dest='output_container', help='Specify a new output container')
    argparser.add_argument('--delete-audio-stream', metavar='stream', help='Deletes the specified audio stream', type=int)
    argparser.add_argument('--delete-audio-streams-except', metavar='stream', help='Deletes all audio streams except the one specified', type=int)
    argparser.add_argument('--delete-data-streams', help='Deletes the specified audio stream', action='store_true')
    argparser.add_argument('--delete-subtitle', help='Deletes the specified subtitle stream', type=int)
    argparser.add_argument('--delete-subtitles', help='Deletes all subtitle streams', action='store_true')

    argparser.add_argument('--create-dir', action='store_true', help='Store the output in a directory with the same name as the input file')
    argparser.add_argument('-v', '--verbose', action='store_true', help='Verbose mode')
    argparser.add_argument('--dry-run', '--nono', action='store_true', help='Make no changes')
    argparser.add_argument('--no-confirm', dest='confirm', action='store_false', help='Disables confirmation dialog before executing')
    argparser.add_argument('--no-cleanup', dest='cleanup', action='store_false', help='Disables cleanup of old file')

    return argparser.parse_args()

def process_file(input_file_path: str) -> None:

    print("\nProcessing '" + input_file_path + "'")
    input_file = MediaFile.parse(input_file_path)

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

    print("\nACTIONS:\n")

    if ARGS.delete_audio_stream and ARGS.delete_audio_streams_except:
        fatal("Only one of --delete_audio_stream and --delete_audio_streams_except can be specified")

    ffmpeg_args = ['ffmpeg']
    if not ARGS.verbose:
        ffmpeg_args.extend(['-loglevel', 'warning'])
    ffmpeg_args.extend(['-nostdin', '-hide_banner'])
    ffmpeg_args.extend(['-analyzeduration', '100000000', '-probesize', '100000000'])
    ffmpeg_args.extend(['-i', input_file.path])
    ffmpeg_args.extend(['-c', 'copy'])
    ffmpeg_args.extend(['-map', '0'])

    if ARGS.delete_audio_stream != None:
        if ARGS.delete_audio_stream >= len(input_file.audio_streams):
            fatal("Audio stream index not found: " + str(ARGS.delete_audio_stream))
        audio_stream_to_delete = input_file.audio_streams[ARGS.delete_audio_stream]
        ffmpeg_args.extend(['-map', '-0:a:' + str(ARGS.delete_audio_stream)])
        print("* Will delete the following audio stream:")
        print("   " + str(audio_stream_to_delete) + "\n")
        
    if ARGS.delete_audio_streams_except != None:
        if ARGS.delete_audio_streams_except >= len(input_file.audio_streams):
            fatal("Audio stream index not found: " + str(ARGS.delete_audio_streams_except))
        
        audio_streams_to_delete = [stream for stream in input_file.audio_streams if stream.type_index != ARGS.delete_audio_streams_except]
        print("* Will delete the following audio streams:")
        for stream in audio_streams_to_delete:
            print("   " + str(stream) + "\n")
            ffmpeg_args.extend(['-map', '-0:a:' + str(stream.type_index)])

    if ARGS.set_audio_lang:
        audio_track_index = int(ARGS.set_audio_lang[0])
        new_language = ARGS.set_audio_lang[1]
        if audio_track_index >= len(input_file.audio_streams):
            fatal("Audio stream index not found: " + str(audio_track_index))
        stream_to_modify = input_file.audio_streams[audio_track_index]
        if stream_to_modify.language == new_language:
            fatal("The specified audio stream already has '" + new_language + "' set as language: \n" + str(stream_to_modify))
        
        ffmpeg_args.extend(['-metadata:s:a:' + str(audio_track_index), 'language=' + new_language])
        
        print("* Will update the following audio stream language to '" + new_language + "'")
        print("   " + str(stream_to_modify) + "\n")

    if ARGS.delete_data_streams:
        print("* Will delete data streams\n")
        ffmpeg_args.extend(['-dn'])
        ffmpeg_args.extend(['-map_chapters', '-1'])

    if ARGS.delete_subtitles:
        print("* Will delete all subtitle streams\n")
        ffmpeg_args.append('-sn')

    if ARGS.delete_subtitle != None:
        if ARGS.delete_subtitle >= len(input_file.subtitle_streams):
            fatal("Subtitle stream index not found: " + str(ARGS.delete_subtitle))
        subtitle_stream_to_delete = input_file.subtitle_streams[ARGS.delete_subtitle]
        ffmpeg_args.extend(['-map', '-0:s:' + str(ARGS.delete_subtitle)])
        print("* Will delete the following subtitle stream:")
        print("   " + str(subtitle_stream_to_delete) + "\n")

    ffmpeg_args.append(working_file)

    confirm()

    if not os.path.exists(working_dir):
        verbose("Creating working dir: " + working_dir)
        os.makedirs(working_dir)
    
    executor = ProcessExecutor()
    print(' '.join(ffmpeg_args))
    returncode = executor.execute(ffmpeg_args)

    if returncode != 0:
        fatal("ffmpeg execution failed")

    print("\nffmpeg execution successful")

    cleanup(inputfile = input_file.path,
            workingfile = working_file, 
            outputfile = output_file)

def cleanup(inputfile: str, workingfile: str, outputfile: str) -> None:
    if not ARGS.cleanup:
        print("Cleanup disabled, leaving old file behind.")
        print("Original file: " + inputfile)
        print("Modified file: " + workingfile)
        exit(0)

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
    print("---")
