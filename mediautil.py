#!/usr/bin/python3

import argparse
import os
import subprocess
from pathlib import Path
from typing import IO
import sys
import io
import json
import signal
import threading
from dataclasses import dataclass

signal.signal(signal.SIGINT, lambda sig, frame : sys.exit(1))

# Specify how many microseconds are analyzed to probe the input. 
# A higher value will enable detecting more accurate information, but will increase latency. 
# It defaults to 5,000,000 microseconds = 5 seconds.
FFMPEG_ANALYZEDURATION=str(100_000_000)

# Set probing size in bytes, i.e. the size of the data to analyze to get stream information. 
# A higher value will enable detecting more information in case it is dispersed into the stream, but will increase latency. 
# Must be an integer not lesser than 32. It is 5000000 by default.
FFMPEG_PROBESIZE=str(100_000_000)

def is_valid_file(parser: argparse.ArgumentParser, arg: str) -> str:
    if Path(arg).is_file():
        return arg
    parser.error(f"The file {arg} does not exist!")

def print_error(*args, **kwargs) -> None:
    print("ERROR:", *args, file=sys.stderr, **kwargs)

def fatal(*args, **kwargs) -> None:
    print_error(*args, **kwargs)
    exit(1)

def is_verbose() -> bool:
    return ARGS.verbose
def verbose(*args, **kwargs) -> None:
    if is_verbose():
        print(*args, file=sys.stderr, **kwargs)
def is_debug() -> bool:
    return ARGS.debug
def debug(*args, **kwargs) -> None:
    if is_debug():
        print(*args, file=sys.stderr, **kwargs)

def confirm() -> None:
    print()
    if ARGS.confirm:
        input('Press ENTER to continue or CTRL-C to abort\n')

def format_bytes(size: int, decimal_places=2) -> str:
    modified_size = size
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
        if modified_size < 1024.0 or unit == 'TiB':
            return f"{modified_size:.{decimal_places}f} {unit}"
        modified_size /= 1024.0
    return f"{modified_size:.{decimal_places}f} TiB"

@dataclass
class CommandExecutionResult:
    args: list[str]
    stdout: str = ""
    stderr: str = ""
    returncode: int|None = None

    def get_command_as_string(self) -> str:
        return ' '.join(self.args)
    def is_success(self) -> bool:
        return self.returncode == 0
    def is_failed(self) -> bool:
        return not self.is_success()

class CommandExecutor:
    print_output: bool

    def __init__(self, print_output: bool = False) -> None:
        if is_debug():
            print_output = True
        self.print_output = print_output
    
    def execute(self, args: list[str]) -> CommandExecutionResult:
        verbose(' '.join(args))
        process = subprocess.Popen(args, 
                                   stdout=subprocess.PIPE, 
                                   stderr=subprocess.PIPE, 
                                   bufsize=1, 
                                   encoding='utf-8',
                                   errors='replace',
                                   text=True)

        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        
        stdout_reader = threading.Thread(target=self.__process_output_stream, args=(process.stdout, stdout_buffer, sys.stdout), daemon=True)
        stderr_reader = threading.Thread(target=self.__process_output_stream, args=(process.stderr, stderr_buffer, sys.stderr), daemon=True)
        stdout_reader.start()
        stderr_reader.start()
        try:
            process.wait()
        finally:
            stdout_reader.join(timeout=1.0)
            stderr_reader.join(timeout=1.0)

        verbose(f"Return code: {process.returncode}")

        return CommandExecutionResult(
            args=args,
            stdout=stdout_buffer.getvalue(),
            stderr=stderr_buffer.getvalue(),
            returncode=process.returncode
        )

    def __process_output_stream(self, output_stream: IO[str], output_buffer: io.StringIO, print_stream: IO[str]) -> None:
        try:
            for line in iter(output_stream.readline, ''):
                if self.print_output:
                    print_stream.write(line)
                    print_stream.flush()
                output_buffer.write(line)
                output_buffer.flush()
        except Exception as e:
            print_error(f"Failed to process output stream: {e}")
        finally:
            output_stream.close()

class FfmpegExecutor:
    args: list[str]

    def __init__(self, input_file_path: str) -> None:
        self.args = ['ffmpeg']
        if not is_verbose():
            self.args.extend(['-loglevel', 'warning'])
        self.args.extend(['-nostdin', '-hide_banner'])
        self.args.extend(['-analyzeduration', FFMPEG_ANALYZEDURATION])
        self.args.extend(['-probesize', FFMPEG_PROBESIZE])
        self.args.extend(['-i', input_file_path])
    
    def add_arg(self, argument: str) -> None:
        self.args.append(argument)
    
    def add_args(self, arguments: list[str]) -> None:
        self.args.extend(arguments)

    def execute(self) -> CommandExecutionResult:
        print(' '.join(self.args))
        if ARGS.dry_run:
            print("(dry-run, not actually executing)")
            return CommandExecutionResult([], returncode=0)
        executor = CommandExecutor(print_output=True)
        return executor.execute(self.args)

class Stream:
    type: str
    codec_name: str
    index: int
    raw: dict
    tags: dict
    language: str|None
    title: str|None
    filename: str|None
    mimetype: str|None
    frames: list[dict]
    closed_captions_type: str|None

    def __init__(self, raw: dict):
        self.type = raw.get("codec_type", "")
        self.codec_name = raw.get("codec_name", "")
        self.index = raw["index"]
        self.raw = raw
        self.frames = []
        self.language = None
        self.title = None
        self.filename = None
        self.mimetype = None
        self.closed_captions_type = None
        if 'tags' in raw:
            self.__parse_tags(raw['tags'])

    def __has_disposition(self, disposition: str) -> bool:
        if 'disposition' not in self.raw or disposition not in self.raw['disposition']:
            return False
        value = int(self.raw['disposition'][disposition])
        return value > 0
    
    def __parse_tags(self, tags: dict) -> None:
        self.tags = tags
        if 'language' in tags:
            self.language = tags['language']
        if 'title' in tags:
            self.title = tags['title']
        if 'filename' in tags:
            self.filename = tags['filename']
        if 'mimetype' in tags:
            self.mimetype = tags['mimetype']
    
    def digest_frame(self, frame: dict) -> None:
        self.frames.append(frame)
        if not 'side_data_list' in frame:
            return
        side_data_list = frame['side_data_list']
        for side_data in side_data_list:
            if not 'side_data_type' in side_data:
                continue
            side_data_type = side_data['side_data_type']
            if 'Closed Captions' in side_data_type or side_data_type == 'CC':
                # Mark video streams as having EIA608
                self.closed_captions_type = side_data_type

    def get_size_in_bytes(self) -> int|None:
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
        if self.__has_disposition('forced'):
            return True
        if self.title and "FORCED" in self.title.upper():
            return True
        return False
    def is_hearing_impaired(self) -> bool:
        if self.__has_disposition('hearing_impaired'):
            return True
        if self.title and "SDH" in self.title.upper():
            return True
        return False
    def is_image_based_subtitle(self) -> bool:
        return self.is_subtitle() and self.raw.get('codec_name') in ['dvd_subtitle', 'dvb_subtitle', 'pgs_subtitle', 'hdmv_pgs_subtitle']

    def has_embedded_subtitles(self) -> bool:
        if self.closed_captions_type:
            return True
        return False

    def __str__(self) -> str:
        result = list()
        result.append(f"Stream #{self.index}")
        result.append(self.type)
        if self.language and (self.is_audio() or self.is_subtitle()):
            result.append(f"({self.language})")
        
        if self.codec_name:
                result.append(self.codec_name)
        
        if self.raw.get('profile'):
            result.append(f"({self.raw.get('profile')})")

        if 'width' in self.raw:
            result.append(f"{self.raw.get('width')}x{self.raw.get('height')}")
        
        if self.raw.get('channel_layout'):
            result.append(f"{self.raw.get('channel_layout')}")

        num_bytes = self.get_size_in_bytes()
        if num_bytes:
            result.append(format_bytes(num_bytes))
        
        if self.title:
            result.append(f"'{self.title}'")
        
        if self.filename:
            result.append(f"'{self.filename}'")
        if self.mimetype:
            result.append(f"({self.mimetype})")

        if self.is_default():
            result.append("(default)")
        if self.is_forced():
            result.append("(forced)")
        if self.is_hearing_impaired():
            result.append("(hi)")
        if self.closed_captions_type:
            result.append("(Embedded subtitle bitstream: " + self.closed_captions_type + ")")

        return ' '.join(result)

class MediaFile:
    path: str
    container: str
    format: dict
    streams: list[Stream]

    def __init__(self, path: str, format, streams: list[Stream]):
        self.path = path
        self.format = format
        self.container = Path(path).suffix[1:]
        self.streams = streams
    
    def get_video_streams(self) -> list[Stream]:
        return [stream for stream in self.streams if stream.is_video()]
    def get_audio_streams(self) -> list[Stream]:
        return [stream for stream in self.streams if stream.is_audio()]
    def get_subtitle_streams(self) -> list[Stream]:
        return [stream for stream in self.streams if stream.is_subtitle()]
    def get_other_streams(self) -> list[Stream]:
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
    ffprobe_result = CommandExecutor().execute(['ffprobe', '-hide_banner', '-of', 'json',
           '-analyzeduration', FFMPEG_ANALYZEDURATION, '-probesize', FFMPEG_PROBESIZE,
           '-show_streams', '-show_format',
            # Display frame details but from the first frame only
            '-show_frames','-read_intervals', '%+#1', 
            filepath])

    if ffprobe_result.returncode != 0:
        print_error(ffprobe_result.stderr)
        fatal("Failed to parse file info from %s" % filepath)

    ffprobe = json.loads(ffprobe_result.stdout)
    
    streams = [Stream(stream_metadata) for stream_metadata in ffprobe['streams']]

    if 'frames' in ffprobe:
        for frame in ffprobe['frames']:
            if not 'stream_index' in frame:
                continue
            for stream in streams:
                if stream.index == frame['stream_index']:
                    stream.digest_frame(frame)

    # Validate indexes
    for i in range(len(streams)):
        if i != streams[i].index:
            fatal(f"The array index {i} does not match the stream index {streams[i].index}")

    return MediaFile(filepath, ffprobe['format'], streams)

def parse_args() -> argparse.Namespace:
    argparser = argparse.ArgumentParser(prog='Mediautil', description='Multi-purpose media editing tool')

    argparser.add_argument('files', metavar='FILE', type=lambda x: is_valid_file(argparser, x), nargs='+',  help='Input file')

    argparser.add_argument('--list', action='store_true', help='Prints information about the specified file')
    argparser.add_argument('--set-stream-language', nargs=2, metavar=('STREAM', 'LANGUAGE'), help='Sets stream language to the specified language')
    argparser.add_argument('--output-container', dest='output_container', help='Specify a new output container')
    argparser.add_argument('--delete-stream', metavar='stream', help='Deletes the specified stream')
    argparser.add_argument('--extract-stream', metavar='stream', help='Deletes the specified stream')
    argparser.add_argument('--delete-audio-streams-except', metavar='stream', help='Deletes all audio streams except the one specified', type=int)
    argparser.add_argument('--delete-data-streams', help='Deletes all data streams', action='store_true')
    argparser.add_argument('--delete-image-streams', help='Deletes all image streams', action='store_true')
    argparser.add_argument('--delete-subs', dest='delete_subs', help='Deletes all subtitle streams', action='store_true')
    argparser.add_argument('--extract-subs', dest='extract_subs', help='Extract all subtitle streams', action='store_true')
    argparser.add_argument('-eds', '--extract-and-delete-subs', dest='extract_and_delete_subs', help='Extract and delete all subtitle streams', action='store_true')

    argparser.add_argument('-d', '--create-dir', action='store_true', help='Store the output in a directory with the same name as the input file')
    argparser.add_argument('-v', '--verbose', action='store_true', help='Verbose mode')
    argparser.add_argument('--debug', action='store_true', help='Debug mode')
    argparser.add_argument('--dry-run', '--nono', action='store_true', help='Make no changes')
    argparser.add_argument('--no-confirm', dest='confirm', action='store_false', help='Disables confirmation dialog before executing')
    argparser.add_argument('--no-cleanup', dest='cleanup', action='store_false', help='Disables cleanup of old file')

    args = argparser.parse_args()
    if args.extract_and_delete_subs:
        args.extract_subs = True
        args.delete_subs = True
    
    if args.dry_run:
        args.confirm = False
    if args.debug:
        args.verbose = True

    if args.delete_stream:
        if "," in args.delete_stream:
            args.delete_stream = list(map(int, args.delete_stream.split(",")))
        else:
            args.delete_stream = [int(args.delete_stream)]
    if args.extract_stream:
        if "," in args.extract_stream:
            args.extract_stream = list(map(int, args.extract_stream.split(",")))
        else:
            args.extract_stream = [int(args.extract_stream)]
    
    return args

def extract_subtitles(input_file: MediaFile, destination_dir: str, subtitle_streams: list[Stream] = []) -> None:
    if not subtitle_streams:
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

        print(f"Extracting subtitle: {subtitle}")
        executor = FfmpegExecutor(input_file.path)
        executor.add_args(['-map', f'0:{subtitle.index}'])
        executor.add_args(['-c', 'srt'])
        executor.add_arg(output_file)
        result = executor.execute()
        if result.is_failed():
            print_error(f"Failed to extract subtitle: {subtitle}. \nCommand: {result.get_command_as_string()}\nResponse code: {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
            raise RuntimeError(f"Failed to extract subtitle: {subtitle}")

def resolve_new_subtitle_file_path(subtitle: Stream, name: str, destination_dir: str) -> str:
    language_str = subtitle.language
    if not language_str:
        language_str = "unknown"
    if subtitle.is_hearing_impaired():
        language_str += ".sdh"
    if subtitle.is_forced():
        language_str += ".forced"

    output_base = f"{destination_dir}/{name}.{language_str}"
    output_file = f"{output_base}.srt"
    i = 0
    while Path(output_file).exists():
        i += 1
        output_file = f"{output_base}.{i}.srt"
    return output_file

def process_file(input_file_path: str) -> None:

    print(f"\nProcessing '{input_file_path}'")
    input_file = parse_mediafile(input_file_path)

    print(f"\n{input_file}\n")
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
        action_list.append(f" * Will change container from {input_file.container} to {output_container}")

    if ARGS.extract_subs:
        action_list.append(" * Will extract all subtitles")
        image_based_subs = [stream for stream in input_file.get_subtitle_streams() if stream.is_image_based_subtitle()]
        if image_based_subs:
            action_list.append("   WARNING: The following subtitles are image based and will not be extracted:")
            for sub in image_based_subs:
                action_list.append(f"    - {sub}")

    if ARGS.set_stream_language:
        stream_index = int(ARGS.set_stream_language[0])
        new_language = ARGS.set_stream_language[1]
        if stream_index >= len(input_file.streams):
            fatal(f"Stream index not found: {stream_index}")
        stream_to_modify = input_file.streams[stream_index]
        if stream_to_modify.language == new_language:
            print(f"WARNING: The specified stream already has '{new_language}' set as language: \n{stream_to_modify}")
        else:
            num_actions += 1
            action_list.append(f" * Will update the following stream language to '{new_language}': {stream_to_modify}")
            executor.add_args([f"-metadata:s:{stream_index}", f"language={new_language}"])

    if ARGS.extract_stream != None:
        for index in ARGS.extract_stream:
            if index >= len(input_file.streams):
                fatal(f"Stream index not found: {index}")
            stream_to_extract = input_file.streams[index]
            if not stream_to_extract.is_subtitle:
                fatal("Only subtitle streams are currently supported for extractions.")
            action_list.append(f" * Will extract the following stream: {stream_to_extract}")

    if ARGS.delete_stream != None:
        for index in ARGS.delete_stream:
            if index >= len(input_file.streams):
                fatal(f"Stream index not found: {index}")
            num_actions += 1
            stream_to_delete = input_file.streams[index]
            executor.add_args(['-map', f'-0:{stream_to_delete.index}'])
            action_list.append(f" * Will delete the following stream: {stream_to_delete}")
        
    if ARGS.delete_audio_streams_except != None:
        if ARGS.delete_audio_streams_except > len(input_file.get_audio_streams()):
            fatal(f"Audio stream index not found: {ARGS.delete_audio_streams_except}")
        
        audio_streams_to_delete = [stream for stream in input_file.get_audio_streams() if stream.index != ARGS.delete_audio_streams_except]
        if audio_streams_to_delete:
            num_actions += 1
            action_list.append(" * Will delete the following audio streams:")
            for stream in audio_streams_to_delete:
                action_list.append(f"    - {stream}")
                executor.add_args(['-map', f'-0:{stream.index}'])

    if ARGS.delete_image_streams:
        image_streams_to_delete = [stream for stream in input_file.get_video_streams() if stream.is_image()]
        if image_streams_to_delete:
            num_actions += 1
            action_list.append(" * Will delete the following image video streams:")
            for stream in image_streams_to_delete:
                action_list.append(f"    - {stream}")
                executor.add_args(['-map', f'-0:{stream.index}'])

    if ARGS.delete_data_streams:
        num_actions += 1
        action_list.append(" * Will delete data streams")
        executor.add_args(['-dn'])
        executor.add_args(['-map_chapters', '-1'])
        if input_file.get_other_streams():
            action_list.append(" * Will delete the following other streams:")
            for stream in input_file.get_other_streams():
                action_list.append(f"    - {stream}")
                executor.add_args(['-map', f'-0:{stream.index}'])

    if ARGS.delete_subs:
        subtitles_detected = False

        if len(input_file.get_subtitle_streams()) > 0:
            num_actions += 1
            subtitles_detected = True
            action_list.append(" * Will delete all subtitle streams")
            executor.add_arg('-sn')
        
        if any(s.has_embedded_subtitles() for s in input_file.get_video_streams()):
            # For H.264: remove_types=6 (SEI messages containing CC)
            # For H.265: remove_types=39 (SEI messages containing CC)
            for stream in input_file.get_video_streams():
                if stream.has_embedded_subtitles():
                    if stream.codec_name == 'h264':
                        executor.add_args(['-bsf:v', 'filter_units=remove_types=6'])
                    elif stream.codec_name == 'hevc':
                        executor.add_args(['-bsf:v', 'filter_units=remove_types=39'])
                    else:
                        print_error(f"Embedded subtitle removal from {stream.codec_name} not implemented")
                        break
                    num_actions += 1
                    subtitles_detected = True
                    action_list.append(" * Will delete embedded EIA608 closed captions from video using bitstream filter")
            
        if not subtitles_detected:
            action_list.append(" * Requested deletion of all subtitle streams but none exists")

    if not action_list:
        verbose("No actions specified")
        return
    
    print("\nACTIONS:")
    for action in action_list:
        print(action)

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
        working_dir = f"{working_dir}/{inputfilename_without_extension}"

    working_file = f"{working_dir}/{inputfilename_without_extension}.new.{output_container}"
    verbose(f"Working file    : {working_file}")
    if Path(working_file).exists():
        fatal(f"Working file already exists: {working_file}")

    output_file = f"{working_dir}/{inputfilename_without_extension}.{output_container}"
    verbose(f"Destination file: {output_file}")

    if container_change and Path(output_file).exists():
        fatal(f"Output file already exists: {output_file}")

    if not Path(working_dir).exists() and not ARGS.dry_run:
        verbose(f"Creating working dir: {working_dir}")
        os.makedirs(working_dir)

    if ARGS.extract_stream:
        streams_to_extract = [input_file.streams[index] for index in ARGS.extract_stream]
        extract_subtitles(input_file, working_dir, streams_to_extract)
    if ARGS.extract_subs:
        extract_subtitles(input_file, working_dir)

    if num_actions == 0:
        # the only action was to extract subs
        return
    
    print("Performing selected actions on source file")
    executor.add_arg(working_file)
    result = executor.execute()

    if result.returncode != 0:
        fatal(f"ffmpeg execution failed with exit code {result.returncode}")

    print("\nffmpeg execution successful")

    cleanup(inputfile = input_file.path,
            workingfile = working_file, 
            outputfile = output_file)

def cleanup(inputfile: str, workingfile: str, outputfile: str) -> None:
    if ARGS.dry_run:
        return
    if not ARGS.cleanup:
        print("Cleanup disabled, leaving old file behind.")
        print(f"Original file: {inputfile}")
        print(f"Modified file: {workingfile}")
        return

    if not Path(workingfile).exists():
        fatal(f"{workingfile} does not exist. Aborting cleanup")

    verbose(f"Deleting {inputfile}")
    os.unlink(inputfile)

    verbose(f"Moving {workingfile} -> {outputfile}")
    os.replace(workingfile, outputfile)

ARGS = parse_args()
debug('Arguments:\n  ' + '\n  '.join(f'{k}={v}' for k, v in vars(ARGS).items() if v != None) + "\n")

if len(ARGS.files) > 1:
    print("Input files:")
    print('  ' + '\n  '.join(ARGS.files))

for file in ARGS.files:
    process_file(file)
    if len(ARGS.files) > 1:
        print("---")
