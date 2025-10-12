#!/usr/bin/python3

import argparse
from pathlib import Path
import sys
from typing import Callable, Final, List, Optional
from enum import Enum

try:
    import regex as re  # Use the enhanced regex module
except ImportError:
    print("Error: the 'regex' module is required. Install it with 'pip install regex'.", file=sys.stderr)
    sys.exit(1)

BASE_DIR: Final[Path]
DRY_RUN: Final[bool]

class Language(Enum):
    ENGLISH = ("eng", "en", "english")
    SWEDISH = ("swe", "sv", "swedish", "svenska")
    SPANISH = ("spa", "es", "spanish", "español")

    def __init__(self, *representations: str) -> None:
        self.representations = [a.lower() for a in representations]
        self.output_representation = self.representations[0]

    def __repr__(self):
        return f"Language(name='{self.name}', abbreviations='{self.representations}')"

    def matches(self, search_string: str) -> bool:
        return search_string.lower() in self.representations
    
    @staticmethod
    def parse(search_string: str) -> Optional["Language"]:
        for language in Language:
            if language.matches(search_string):
                return language
        return None

class SubtitleFile:

    FILENAME_SPLIT_REGEX = re.compile(r"[^\p{L}0-9]+", flags=re.UNICODE)

    path: Path
    tree: List[str]
    language: Optional[Language]
    forced: bool
    hi: bool

    def __init__(self, path: Path) -> None:
        self.path = path
        self.tree = self.__resolve_tree(path)
        self.language = None
        self.forced = False
        self.hi = False
        self.__resolve_optional()
    
    @staticmethod
    def __resolve_tree(path: Path) -> List[str]:
        try:
            relative_path = path.relative_to(BASE_DIR)
            return list(relative_path.parent.parts)
        except ValueError:
            # file is not inside BASE_DIR (or resolution mismatch) — return empty list
            print(f"WARNING: Failed to resolve relative parts of {path}")
            return []

    def __resolve_optional(self) -> None:
        filename = self.path.stem
        parts = [part for part in self.FILENAME_SPLIT_REGEX.split(filename) if part]
        
        for part in reversed(parts):
            if not self.forced and part == "forced":
                self.forced = True
                continue
            if not self.hi and part in ["hi", "sdh"]:
                self.hi = True
                continue
            if not self.language:
                language = Language.parse(part)
                if language:
                    self.language = language
                    continue
    
    def create_file_suffix(self) -> str:
        result = []
        if self.language:
            result.append(self.language.output_representation)
        if self.hi:
            result.append("hi")
        if self.forced:
            result.append("forced")

        base = ".".join(result)
        return f"{base}{self.path.suffix}"

    def name_contains(self, search_string: str, case_sensitive: bool = True) -> bool:
        if case_sensitive:
            return search_string in self.path.stem
        return search_string.lower() in self.path.stem.lower()

    def tree_contains(self, search_string: str, case_sensitive: bool = True) -> bool:
        if case_sensitive:
            return search_string in self.tree
        
        return search_string.lower() in [element.lower() for element in self.tree]

    def __repr__(self) -> str:
        lang_repr = self.language.name if self.language else None
        return f"SubtitleFile(path={self.path!s}, language={lang_repr!r}, tree_len={len(self.tree)})"

class VideoFile:

    EPISODE_REGEX = re.compile(r'\b(?:S\d{1,3}E\d{1,3}|\d{1,3}x\d{1,3})\b', re.IGNORECASE)
    # EPISODE_REGEX = re.compile(r'(?i)(S\d{1,4}E\d{1,3}|\d{1,4}X\d{1,3})')

    path: Path
    is_episode: bool
    subtitle_files: list[SubtitleFile]

    def __init__(self, path: Path) -> None:
        self.path = path
        self.is_episode = self.__is_episode(path)
        self.subtitle_files = []
    
    def __repr__(self) -> str:
        return f"VideoFile(path={self.path!s})"
    
    @staticmethod
    def __is_episode(path: Path) -> bool:
        return bool(VideoFile.EPISODE_REGEX.search(path.stem))
    
    def resolve_subtitle_target_dir(self) -> Path:
        if self.is_episode:
            # Subtitles directory under video file directory
            return self.path.parent / "Subtitles"
        else:
            # Same directory as video file
            return self.path.parent

class FileResolver:

    def find_video_files(self) -> List[VideoFile]:
        found_files: List[Path] = self.find_files("*.mkv", "*.mp4", "*.avi", "*.mpg")
        return [VideoFile(file) for file in found_files]
    
    def find_subtitle_files(self) -> List[SubtitleFile]:
        found_files: List[Path] = self.find_files("*.srt", "*.sub")
        return [SubtitleFile(file) for file in found_files]
    
    def find_files(self, *patterns: str) -> List[Path]:
        results: List[Path] = []
        for pattern in patterns:
            results.extend(file for file in BASE_DIR.rglob(pattern) if file.is_file())
        return results

class SubtitleMatcher:
    def __init__(self, video_files: list[VideoFile]) -> None:
        self.video_files = video_files

    def find_match(self, subtitle: SubtitleFile) -> Optional[VideoFile]:
        if len(self.video_files) == 1:
            return self.video_files[0]
        
        predicates = [
            lambda video: subtitle.name_contains(video.path.stem),
            lambda video: subtitle.name_contains(video.path.stem, case_sensitive=False),
            lambda video: subtitle.tree_contains(video.path.stem),
            lambda video: subtitle.tree_contains(video.path.stem, case_sensitive=False),
        ]

        for predicate in predicates:
            for video in self.video_files:
                if predicate(video):
                    return video
        return None

def main() -> None:
    args = parse_command_line_args()
    
    global BASE_DIR
    BASE_DIR = args.directory.resolve()

    global DRY_RUN
    DRY_RUN = args.dry_run
    # DRY_RUN = True

    resolver: FileResolver = FileResolver()
    subtitle_files: List[SubtitleFile] = resolver.find_subtitle_files()
    video_files: List[VideoFile] = resolver.find_video_files()

    if len(video_files) == 0:
        print("No video files found")
        sys.exit(1)
    if len(subtitle_files) == 0:
        print("No subtitle files found")
        sys.exit(1)

    match_subtitles_with_videos(video_files, subtitle_files)
    rearrange_subtitle_files(video_files)

def parse_command_line_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Arrange subtitle files in directory.")
    parser.add_argument("directory", type=Path, help="Directory to process.")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run")

    return parser.parse_args()

def match_subtitles_with_videos(video_files: list[VideoFile], subtitle_files: list[SubtitleFile]) -> None:
    matcher = SubtitleMatcher(video_files)
    for subtitle in subtitle_files:
        matching_video = matcher.find_match(subtitle)
        if matching_video:
            matching_video.subtitle_files.append(subtitle)
        else:
            print(f"Failed to find matching video for subtitle: {subtitle}")

def rearrange_subtitle_files(video_files: list[VideoFile]) -> None:
    for video_file in video_files:
        target_directory = video_file.resolve_subtitle_target_dir()
        target_directory.mkdir(exist_ok=True)

        for subtitle_file in video_file.subtitle_files:
            if not subtitle_file.language:
                print(f"Ignoring subtitle file: {subtitle_file.path}")
                continue

            target_filename = f"{video_file.path.stem}.{subtitle_file.create_file_suffix()}"
            destination = target_directory / target_filename
            if subtitle_file.path.resolve() == destination.resolve():
                # Already in the correct place with correct name, skip
                print(f"Skipping already correctly placed file: {destination}")
                continue

            # move the subtitle file to the target_dir
            move_file(subtitle_file.path, target_directory, target_filename)

def move_file(source_file: Path, target_dir: Path, target_filename: str) -> None:
    base = Path(target_filename).stem
    ext = Path(target_filename).suffix
    destination = target_dir / f"{base}{ext}"

    # Incremental suffix if file exists
    counter = 1
    while destination.exists():
        destination = target_dir / f"{base}.{counter}{ext}"
        counter += 1
    
    if DRY_RUN:
        print(f"[DRY-RUN] {source_file.relative_to(BASE_DIR)} -> {destination.relative_to(BASE_DIR)}")
    else:
        print(f"Moving {source_file.relative_to(BASE_DIR)} -> {destination.relative_to(BASE_DIR)}")
        source_file.rename(destination)

main()
