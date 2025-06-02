# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the OpenTimelineIO project

import opentimelineio as otio
import xml.etree.ElementTree as ET
from fractions import Fraction
import os
import logging
# Import shared utilities
from otio_fcpx_xml_lite_adapter.utils import _parse_fcpx_time, _to_rational_time

logger = logging.getLogger(__name__)

class FcpXmlReader:
    """Handles the conversion of an FCPXML string to an OTIO Timeline."""

    def __init__(self, input_str: str):
        # print("[Reader] Initializing FcpXmlReader")
        logger.info("Initializing FcpXmlReader")
        try:
            self.root = ET.fromstring(input_str)
        except ET.ParseError as e:
            raise otio.exceptions.OTIOError(f"Error parsing XML: {e}")

        self.fcpxml_version = self.root.tag == 'fcpxml' and self.root.get('version')
        if not self.fcpxml_version:
            raise otio.exceptions.OTIOError("Not a valid FCPXML document (missing <fcpxml> root or version).")
        # print(f"[Reader] Parsing FCPXML version: {self.fcpxml_version}")
        logger.info(f"Parsing FCPXML version: {self.fcpxml_version}")

        # Handle both old and new FCPXML structures
        # Current DTD structure: fcpxml > (resources?, project)
        # Old structure: fcpxml > (resources, library > event > project > sequence)
        
        self.project_root = self.root.find('project')
        if self.project_root is not None:
            # Current DTD-compliant structure: resources at fcpxml root level
            self.resources_root = self.root.find('resources')
            self.sequence_element = self.project_root.find('sequence')
            logger.info("Using current DTD-compliant structure (fcpxml > resources, project)")
        else:
            # Old structure
            self.resources_root = self.root.find('resources')
            self.library_root = self.root.find('library')
            if self.library_root is None:
                raise otio.exceptions.OTIOError("No <library> or <project> element found in FCPXML.")
            
            # Find the first sequence to process
            self.sequence_element = self.library_root.find('.//sequence')
            logger.info("Using legacy structure (fcpxml > library > event > project)")
        
        if self.sequence_element is None:
            raise otio.exceptions.OTIOError("No <sequence> element found in FCPXML.")

        # Parsed resources
        self.formats = {}
        self.assets = {}
        self.effects = {}

        # Timeline attributes
        self.seq_name = "Untitled Sequence"
        self.global_rate = 24 # Default
        self.global_start_time = otio.opentime.RationalTime(0, self.global_rate)
        self.timeline = None

        # Parsed items organized by lane
        self.items_by_lane = {}

        # Initial setup calls
        self._parse_resources()
        self._parse_sequence_info()
        self._create_timeline()

    def _parse_resources(self):
        """Parses format, asset, and effect elements from the resources block."""
        # print("[Reader] Parsing resources")
        logger.info("Parsing resources")
        if self.resources_root is None:
            # print("[Reader] Warning: No <resources> block found.")
            logger.warning("No <resources> block found.")
            return

        for fmt in self.resources_root.findall('format'):
            fmt_id = fmt.get('id')
            if fmt_id: self.formats[fmt_id] = fmt
        for asset in self.resources_root.findall('asset'):
            asset_id = asset.get('id')
            if asset_id: self.assets[asset_id] = asset
        for effect in self.resources_root.findall('effect'):
            effect_id = effect.get('id')
            if effect_id: self.effects[effect_id] = effect
        # print(f"[Reader] Found: {len(self.formats)} formats, {len(self.assets)} assets, {len(self.effects)} effects")
        logger.info(f"Found: {len(self.formats)} formats, {len(self.assets)} assets, {len(self.effects)} effects")

    def _parse_sequence_info(self):
        """Parses top-level sequence attributes like name, rate, start time."""
        # print("[Reader] Parsing sequence info")
        logger.info("Parsing sequence info")
        self.seq_name = self.sequence_element.get('name', 'Untitled Sequence')
        seq_format_id = self.sequence_element.get('format')
        seq_tc_start_str = self.sequence_element.get('tcStart', '0s')

        if not seq_format_id or seq_format_id not in self.formats:
            raise otio.exceptions.OTIOError(f"Sequence format '{seq_format_id}' not found in resources.")

        seq_format = self.formats[seq_format_id]
        frame_duration_str = seq_format.get('frameDuration')
        if not frame_duration_str:
            raise otio.exceptions.OTIOError(f"Format '{seq_format_id}' has no frameDuration.")

        try:
            rate_fraction = 1 / _parse_fcpx_time(frame_duration_str)
            self.global_rate = float(rate_fraction)
            if self.global_rate.is_integer(): self.global_rate = int(self.global_rate)
            # else: print(f"[Reader] Warning: Non-integer rate {self.global_rate} derived.")
            else: logger.warning(f"Non-integer rate {self.global_rate} derived from frameDuration.")
        except Exception as e:
            raise otio.exceptions.OTIOError(f"Could not parse frameDuration '{frame_duration_str}': {e}")

        start_time_frac = _parse_fcpx_time(seq_tc_start_str)
        self.global_start_time = _to_rational_time(start_time_frac, self.global_rate)
        # print(f"[Reader] Sequence: '{self.seq_name}', Rate: {self.global_rate}, Start: {self.global_start_time}")
        logger.info(f"Sequence: '{self.seq_name}', Rate: {self.global_rate}, Start: {self.global_start_time}")

    def _create_timeline(self):
        """Initializes the OTIO Timeline object."""
        # print("[Reader] Creating timeline object")
        logger.info("Creating timeline object")
        self.timeline = otio.schema.Timeline(name=self.seq_name, global_start_time=self.global_start_time)
        self.timeline.metadata['fcpx_version'] = self.fcpxml_version

    def _process_spine_elements(self, container_element, parent_offset_rt):
        """Recursively processes elements within a container (spine or gap)."""
        for element in container_element:
            tag = element.tag
            name = element.get('name', f'Untitled {tag}')
            offset_str = element.get('offset')
            duration_str = element.get('duration')
            start_str = element.get('start', '0s') # Clip's start within its source media
            lane_str = element.get('lane')

            offset_frac = _parse_fcpx_time(offset_str)
            duration_frac = _parse_fcpx_time(duration_str)
            start_frac = _parse_fcpx_time(start_str)

            if duration_frac is None or duration_frac <= 0:
                # print(f"[Reader] Warning: Skipping element '{name}' with invalid duration '{duration_str}'.")
                logger.warning(f"Skipping element '{name}' with invalid duration '{duration_str}'.")
                continue

            item_seq_start_rt = parent_offset_rt + _to_rational_time(offset_frac if offset_frac is not None else Fraction(0), self.global_rate)
            duration_rt = _to_rational_time(duration_frac, self.global_rate)
            timeline_range = otio.opentime.TimeRange(item_seq_start_rt, duration_rt)

            lane = 0
            if lane_str is not None:
                try: lane = int(lane_str)
                # except ValueError: print(f"[Reader] Warning: Invalid lane '{lane_str}' for '{name}'. Using 0.")
                except ValueError: logger.warning(f"Invalid lane '{lane_str}' for '{name}'. Using 0.")
            if lane not in self.items_by_lane: self.items_by_lane[lane] = []

            otio_item = None
            item_metadata = {'fcpx_tag': tag}

            # --- Create OTIO Item based on tag ---
            if tag == 'asset-clip':
                otio_item = self._create_otio_asset_clip(element, name, start_frac, duration_rt, item_metadata)
            elif tag == 'gap':
                # print(f"[Reader] Processing items inside gap '{name}' starting at {item_seq_start_rt}")
                logger.debug(f"Processing items inside gap '{name}' starting at {item_seq_start_rt}")
                self._process_spine_elements(element, item_seq_start_rt) # Recurse
                continue # Don't add gap item itself yet
            elif tag == 'title':
                otio_item = self._create_otio_title(element, name, duration_rt, item_metadata)
            elif tag == 'video':
                otio_item = self._create_otio_video_placeholder(element, name, duration_rt, item_metadata)
            else:
                # print(f"[Reader] Warning: Unhandled element type '{tag}' in spine: '{name}'. Treating as Gap.")
                logger.warning(f"Unhandled element type '{tag}' in spine: '{name}'. Treating as Gap.")
                otio_item = otio.schema.Gap(name=name, source_range=otio.opentime.TimeRange(duration=duration_rt))

            if otio_item:
                otio_item.metadata.update(item_metadata)
                self.items_by_lane[lane].append((timeline_range, otio_item))

    def _create_otio_asset_clip(self, element, name, start_frac, duration_rt, item_metadata):
        """Creates an OTIO Clip from an <asset-clip> element."""
        ref_id = element.get('ref')
        media_ref = None

        if ref_id and ref_id in self.assets:
            asset = self.assets[ref_id]
            # Handle both current DTD structure and legacy formats
            # Current DTD structure: <asset><media-rep src="..."/></asset>
            # Legacy structure: <asset src="...">
            media_url = asset.get('src')  # Try legacy structure first
            if not media_url:
                # Fall back to current DTD structure
                media_rep = asset.find('./media-rep')
                media_url = media_rep.get('src') if media_rep is not None else None
            
            asset_start_frac = _parse_fcpx_time(asset.get('start', '0s'))
            asset_dur_frac = _parse_fcpx_time(asset.get('duration'))
            available_range = None
            if asset_dur_frac is not None:
                ar_start = _to_rational_time(asset_start_frac, self.global_rate)
                ar_dur = _to_rational_time(asset_dur_frac, self.global_rate)
                available_range = otio.opentime.TimeRange(ar_start, ar_dur)
            if media_url:
                media_ref = otio.schema.ExternalReference(target_url=media_url, available_range=available_range)
            else:
                media_ref = otio.schema.MissingReference(name=f"Missing_{ref_id}", available_range=available_range)
        else:
            media_ref = otio.schema.MissingReference(name=f"Missing_{ref_id or 'Unknown'}")

        clip_media_start_rt = _to_rational_time(start_frac, self.global_rate)
        clip_source_range = otio.opentime.TimeRange(start_time=clip_media_start_rt, duration=duration_rt)
        otio_clip = otio.schema.Clip(name=name, media_reference=media_ref, source_range=clip_source_range)

        # Handle enabled attribute
        enabled_attr = element.get('enabled')
        if enabled_attr is not None:
            # Set enabled property based on FCPXML attribute ('0' = False, '1' or other = True)
            otio_clip.enabled = enabled_attr != '0'
        # If no enabled attribute, keep default (True)

        # Add markers
        self._add_markers_to_clip(element, otio_clip, start_frac)
        return otio_clip

    def _add_markers_to_clip(self, element, otio_clip, clip_start_frac):
         """Adds markers from an FCPXML element to an OTIO Clip."""
         clip_media_start_rt = _to_rational_time(clip_start_frac, self.global_rate)
         for marker_elem in element.findall('marker'):
            m_start_str = marker_elem.get('start')
            m_dur_str = marker_elem.get('duration')
            m_value = marker_elem.get('value')
            m_note = marker_elem.get('note')
            m_start_frac = _parse_fcpx_time(m_start_str)
            m_dur_frac = _parse_fcpx_time(m_dur_str)
            if m_start_frac is None or m_dur_frac is None: continue

            marked_start_rt = _to_rational_time(m_start_frac, self.global_rate)
            marked_dur_rt = _to_rational_time(m_dur_frac, self.global_rate)
            marked_range_start_in_media = clip_media_start_rt + marked_start_rt
            marked_range = otio.opentime.TimeRange(marked_range_start_in_media, marked_dur_rt)
            marker = otio.schema.Marker(name=m_value, marked_range=marked_range)
            if m_note: marker.metadata['fcp_note'] = m_note
            # Add completed status if present (map to metadata?)
            completed = marker_elem.get('completed')
            if completed is not None: marker.metadata['fcpx_completed'] = completed
            otio_clip.markers.append(marker)

    def _create_otio_title(self, element, name, duration_rt, item_metadata):
        """Creates an OTIO Clip with GeneratorReference from a <title> element."""
        effect_id = element.get('ref')
        text_elem = element.find('./text/text-style')
        text_content = text_elem.text if text_elem is not None else name
        params = {'text': text_content}
        if effect_id:
            params['fcpx_ref'] = effect_id
            if effect_id in self.effects:
                fx = self.effects[effect_id]
                params['fcpx_effect_name'] = fx.get('name')
                params['fcpx_effect_uid'] = fx.get('uid')
        media_ref = otio.schema.GeneratorReference(name=name, generator_kind="fcpx_title", parameters=params)
        clip_source_range = otio.opentime.TimeRange(start_time=otio.opentime.RationalTime(0, self.global_rate), duration=duration_rt)
        otio_item = otio.schema.Clip(name=name, media_reference=media_ref, source_range=clip_source_range)
        
        # Handle enabled attribute
        enabled_attr = element.get('enabled')
        if enabled_attr is not None:
            # Set enabled property based on FCPXML attribute ('0' = False, '1' or other = True)
            otio_item.enabled = enabled_attr != '0'
        # If no enabled attribute, keep default (True)
        
        self._add_markers_to_clip(element, otio_item, Fraction(0)) # Titles have 0 start frac
        return otio_item

    def _create_otio_video_placeholder(self, element, name, duration_rt, item_metadata):
        """Creates an OTIO Clip with GeneratorReference from a <video> element."""
        ref_id = element.get('ref')
        params = {}
        if ref_id:
            params['fcpx_ref'] = ref_id
            if ref_id in self.effects:
                fx = self.effects[ref_id]
                params['fcpx_effect_name'] = fx.get('name')
                params['fcpx_effect_uid'] = fx.get('uid')
        media_ref = otio.schema.GeneratorReference(name=name, generator_kind="fcpx_video_placeholder", parameters=params)
        clip_source_range = otio.opentime.TimeRange(start_time=otio.opentime.RationalTime(0, self.global_rate), duration=duration_rt)
        otio_item = otio.schema.Clip(name=name, media_reference=media_ref, source_range=clip_source_range)
        
        # Handle enabled attribute
        enabled_attr = element.get('enabled')
        if enabled_attr is not None:
            # Set enabled property based on FCPXML attribute ('0' = False, '1' or other = True)
            otio_item.enabled = enabled_attr != '0'
        # If no enabled attribute, keep default (True)
        
        self._add_markers_to_clip(element, otio_item, Fraction(0)) # Placeholders have 0 start frac
        return otio_item

    def _parse_spine(self):
        """Parses the main <spine> element to populate items_by_lane."""
        # print("[Reader] Parsing spine")
        logger.info("Parsing spine")
        spine = self.sequence_element.find('spine')
        if spine is None:
            logger.warning("No <spine> found in sequence. Timeline will be empty.")
            return

        # Initial call starts with the sequence's global start time as the base offset
        self._process_spine_elements(spine, self.global_start_time)

    def _build_timeline_tracks(self):
        """Builds OTIO Tracks from the items_by_lane dictionary."""
        print("[Reader] Building timeline tracks from parsed lanes")
        stack = otio.schema.Stack()
        self.timeline.tracks = stack
        sorted_lanes = sorted(self.items_by_lane.keys())

        for lane in sorted_lanes:
            lane_items_sorted = sorted(self.items_by_lane[lane], key=lambda x: x[0].start_time)
            if not lane_items_sorted: continue

            # Infer track kind
            track_kind = otio.schema.TrackKind.Video
            if lane < 0: track_kind = otio.schema.TrackKind.Audio
            # Could refine based on first item's asset type if needed

            track = otio.schema.Track(name=f"Lane_{lane}", kind=track_kind)
            track_cursor = self.global_start_time

            for item_range, item in lane_items_sorted:
                gap_duration = item_range.start_time - track_cursor
                if gap_duration > otio.opentime.RationalTime(0, self.global_rate):
                    track.append(otio.schema.Gap(source_range=otio.opentime.TimeRange(duration=gap_duration)))

                # Adjust item source range duration to match timeline usage?
                # No, keep original source_range. The timeline range is implicitly handled by position.
                try:
                    track.append(item)
                    track_cursor = item_range.end_time_exclusive()
                except Exception as e:
                    print(f"[Reader] Error appending item '{item.name}' to track '{track.name}': {e}. Skipping.")
                    track_cursor = max(track_cursor, item_range.end_time_exclusive())

            stack.append(track)
        logger.info(f"[Reader] Built {len(stack)} tracks.")

    def build_timeline(self) -> otio.schema.Timeline:
        """Builds and returns the final OTIO Timeline object."""
        self._parse_spine()
        self._build_timeline_tracks()
        return self.timeline 