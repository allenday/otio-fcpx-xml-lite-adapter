# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the OpenTimelineIO project

import json
import os
import unittest
import unittest.mock
import xml.etree.ElementTree as ET
import opentimelineio as otio
from opentimelineio import opentime
import opentimelineio.test_utils as otio_test_utils
from otio_fcpx_xml_lite_adapter.utils import _fcpx_time_str
from otio_fcpx_xml_lite_adapter.writer import FcpXmlWriter
#from otio_fcpx_xml_lite_adapter import utils
import re
import logging
import tempfile
import subprocess

logger = logging.getLogger(__name__)

SAMPLE_XML = os.path.join(
    os.path.dirname(__file__),
    "data",
    "slutpop.fcpxml"
)

class AdapterTest(unittest.TestCase, otio_test_utils.OTIOAssertions):
    """
    The test class for the FCP X XML adapter
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.maxDiff = None

    # --- Helper Method for Test Data Generation ---
    def _generate_timeline_and_fcpxml_from_json(self, json_path):
        """
        Reads JSON beat data, creates an OTIO timeline with placeholder clips
        and markers, writes it to an FCPXML string, and returns relevant data.
        """
        with open(json_path, 'r') as f:
            beat_data = json.load(f)

        media_path = beat_data.get("path")
        if not media_path:
            self.fail("JSON data is missing the 'path' field.")
        media_url = otio.url_utils.url_from_filepath(media_path)
        expected_asset_name = os.path.basename(media_path)

        rate = 24.0
        timeline = otio.schema.Timeline(name="BabyGotBack Markers")
        timeline.global_start_time = otio.opentime.RationalTime(0, rate)

        # --- Create Audio Track --- (Lane -1)
        audio_track = otio.schema.Track(name="Audio Track", kind=otio.schema.TrackKind.Audio)
        timeline.tracks.append(audio_track)

        # Determine overall duration
        max_segment_end = max(s['end'] for s in beat_data.get('segments', [{ 'end': 0 }]))
        max_marker_time = max(beat_data.get('beats', [0]) + beat_data.get('downbeats', [0])) if beat_data.get('beats') or beat_data.get('downbeats') else 0
        max_time_sec = max(max_segment_end, max_marker_time, 1)
        timeline_duration_frames = int(max_time_sec * rate) + 1
        timeline_duration = opentime.RationalTime(timeline_duration_frames, rate)

        audio_ref = otio.schema.ExternalReference(
            target_url=media_url,
            available_range=opentime.TimeRange(start_time=otio.opentime.RationalTime(0, rate), duration=timeline_duration)
        )
        audio_clip = otio.schema.Clip(
            name="Audio Clip",
            media_reference=audio_ref,
            source_range=opentime.TimeRange(start_time=otio.opentime.RationalTime(0, rate), duration=timeline_duration)
        )
        audio_track.append(audio_clip)

        # --- Create Video Tracks for Markers --- (Lanes 1 and 2)
        downbeat_track = otio.schema.Track(name="Downbeat Sections", kind=otio.schema.TrackKind.Video)
        beat_track = otio.schema.Track(name="Beat Sections", kind=otio.schema.TrackKind.Video)
        timeline.tracks.append(downbeat_track)
        timeline.tracks.append(beat_track)

        # Generator reference details
        placeholder_effect_uid = '.../Generators.localized/Elements.localized/Placeholder.localized/Placeholder.motn'
        placeholder_effect_name = 'Placeholder'

        # --- Populate Video Tracks ---
        segments = beat_data.get('segments', [])
        downbeat_times = set(beat_data.get('downbeats', []))
        beat_times = set(beat_data.get('beats', []))

        current_downbeat_time = opentime.RationalTime(0, rate)
        current_beat_time = opentime.RationalTime(0, rate)

        for i, segment in enumerate(segments):
            seg_start_sec = segment['start']
            seg_end_sec = segment['end']
            seg_label = segment['label']

            seg_start_rt = opentime.RationalTime(seg_start_sec * rate, rate)
            seg_end_rt = opentime.RationalTime(seg_end_sec * rate, rate)

            # Quantize
            start_frame_float = seg_start_rt.to_frames(rate)
            quantized_start_frame = round(start_frame_float)
            quantized_seg_start_rt = opentime.RationalTime(value=quantized_start_frame, rate=rate)

            end_frame_float = seg_end_rt.to_frames(rate)
            quantized_end_frame = round(end_frame_float)
            quantized_seg_end_rt = opentime.RationalTime(value=quantized_end_frame, rate=rate)

            quantized_seg_duration_rt = quantized_seg_end_rt - quantized_seg_start_rt

            if quantized_seg_duration_rt <= opentime.RationalTime(0, rate):
                continue

            seg_range = opentime.TimeRange(duration=quantized_seg_duration_rt)

            placeholder_generator_ref = otio.schema.GeneratorReference(
                name=f"{seg_label} Placeholder",
                generator_kind="fcpx_video_placeholder",
                parameters={
                    'fcpx_ref': 'r_placeholder', # This hints the writer
                    'fcpx_effect_name': placeholder_effect_name,
                    'fcpx_effect_uid': placeholder_effect_uid
                }
            )

            downbeat_placeholder_clip = otio.schema.Clip(
                name=f"Downbeat Segment: {seg_label}",
                media_reference=placeholder_generator_ref,
                source_range=seg_range
            )
            beat_placeholder_clip = otio.schema.Clip(
                name=f"Beat Segment: {seg_label}",
                media_reference=placeholder_generator_ref,
                source_range=seg_range
            )

            markers_for_downbeat_clip = []
            markers_for_beat_clip = []

            for beat_time_sec in beat_times:
                if seg_start_sec <= beat_time_sec < seg_end_sec:
                    marker_time_rt = opentime.RationalTime(beat_time_sec * rate, rate)
                    marker_time_relative_to_segment = marker_time_rt - seg_start_rt
                    if marker_time_relative_to_segment < opentime.RationalTime(0, rate):
                        marker_time_relative_to_segment = opentime.RationalTime(0, rate)
                    if marker_time_relative_to_segment >= quantized_seg_duration_rt:
                         continue
                    marker = otio.schema.Marker(
                        name="Beat",
                        marked_range=opentime.TimeRange(start_time=marker_time_relative_to_segment, duration=opentime.RationalTime(0, rate)),
                        color=otio.schema.MarkerColor.BLUE
                    )
                    markers_for_beat_clip.append(marker)

            for downbeat_time_sec in downbeat_times:
                if seg_start_sec <= downbeat_time_sec < seg_end_sec:
                    marker_time_rt = opentime.RationalTime(downbeat_time_sec * rate, rate)
                    marker_time_relative_to_segment = marker_time_rt - seg_start_rt
                    if marker_time_relative_to_segment < opentime.RationalTime(0, rate):
                        marker_time_relative_to_segment = opentime.RationalTime(0, rate)
                    if marker_time_relative_to_segment >= quantized_seg_duration_rt:
                         continue
                    marker = otio.schema.Marker(
                        name="Downbeat",
                        marked_range=opentime.TimeRange(start_time=marker_time_relative_to_segment, duration=opentime.RationalTime(0, rate)),
                        color=otio.schema.MarkerColor.RED
                    )
                    markers_for_downbeat_clip.append(marker)

            if markers_for_downbeat_clip:
                downbeat_placeholder_clip.markers.extend(markers_for_downbeat_clip)
                gap_duration_downbeat = quantized_seg_start_rt - current_downbeat_time
                if gap_duration_downbeat > opentime.RationalTime(0, rate):
                    downbeat_track.append(otio.schema.Gap(source_range=opentime.TimeRange(duration=gap_duration_downbeat)))
                    current_downbeat_time += gap_duration_downbeat
                downbeat_track.append(downbeat_placeholder_clip)
                current_downbeat_time += quantized_seg_duration_rt

            if markers_for_beat_clip:
                beat_placeholder_clip.markers.extend(markers_for_beat_clip)
                gap_duration_beat = quantized_seg_start_rt - current_beat_time
                if gap_duration_beat > opentime.RationalTime(0, rate):
                    beat_track.append(otio.schema.Gap(source_range=opentime.TimeRange(duration=gap_duration_beat)))
                    current_beat_time += gap_duration_beat
                beat_track.append(beat_placeholder_clip)
                current_beat_time += quantized_seg_duration_rt

        fcpxml_string = otio.adapters.write_to_string(timeline, adapter_name="otio_fcpx_xml_lite_adapter")

        # Extract placeholder resource ID (assuming it's consistent, e.g., 'r3')
        # This is a bit brittle, relies on writer implementation detail
        effect_resource_match = re.search(
            r'<effect id="(r\d+)" name="Placeholder" uid="\.\.\./Generators\.localized/Elements\.localized/Placeholder\.localized/Placeholder\.motn"/>',
            fcpxml_string
        )
        placeholder_resource_id = effect_resource_match.group(1) if effect_resource_match else None
        if not placeholder_resource_id:
            self.fail("Could not extract placeholder_resource_id from generated FCPXML")

        return {
            "fcpxml_string": fcpxml_string,
            "timeline": timeline,
            "rate": rate,
            "media_url": media_url,
            "expected_asset_name": expected_asset_name,
            "placeholder_resource_id": placeholder_resource_id,
            "placeholder_effect_name": placeholder_effect_name,
            "placeholder_effect_uid": placeholder_effect_uid,
            "beat_times": beat_times,
            "downbeat_times": downbeat_times,
            "timeline_duration": timeline_duration
        }

    def test_json_to_fcpxml_markers(self):
        """
        Tests the generation logic: OTIO timeline structure and marker counts
        based on JSON data, using high-level regex checks on the FCPXML output.
        """
        json_path = os.path.join(os.path.dirname(__file__), 'data', 'babygotback.json')
        data = self._generate_timeline_and_fcpxml_from_json(json_path)
        fcpxml_string = data["fcpxml_string"]
        placeholder_resource_id = data["placeholder_resource_id"]
        beat_times = data["beat_times"]
        downbeat_times = data["downbeat_times"]
        media_url = data["media_url"]
        expected_asset_name = data["expected_asset_name"]

        # --- Assertions (Regex-based, focusing on counts and presence) --- #
        self.assertIn('<fcpxml version="1.13">', fcpxml_string)
        self.assertIn('<spine>', fcpxml_string)

        # Check for the single, shared Generator Effect Resource
        effect_resource_match = re.search(
            rf'<effect id="{placeholder_resource_id}" name="Placeholder" uid="\.\.\./Generators\.localized/Elements\.localized/Placeholder\.localized/Placeholder\.motn"/>',
            fcpxml_string
        )
        self.assertIsNotNone(effect_resource_match, "Could not find the shared Placeholder effect resource with expected ID")

        # Check for Audio Clip on Lane -1
        audio_clip_tag_match = re.search(r'<asset-clip[^>]*name="Audio Clip"[^>]*>', fcpxml_string)
        self.assertIsNotNone(audio_clip_tag_match, "Could not find <asset-clip name='Audio Clip'> tag")
        audio_clip_tag_full = audio_clip_tag_match.group(0)
        self.assertIn('lane="-1"', audio_clip_tag_full)
        self.assertIn('ref="r2"', audio_clip_tag_full) # Check it references the correct asset

        # Check Asset details
        self.assertIn(f'<asset id="r2" name="{expected_asset_name}"', fcpxml_string)
        self.assertIn(f'src="{media_url}"', fcpxml_string)

        # Check marker counts on Lane 1 (Downbeats)
        lane1_clips = re.findall(rf'<(video)[^>]*lane="1"[^>]*ref="{placeholder_resource_id}"[^>]*>(.*?)</\1>', fcpxml_string, re.DOTALL)
        self.assertTrue(len(lane1_clips) > 0, f"No video clips found on lane 1 referencing {placeholder_resource_id}")
        actual_downbeat_markers_in_lane1 = sum(clip_content.count('note="Downbeat"') for _, clip_content in lane1_clips)
        actual_beat_markers_in_lane1 = sum(clip_content.count('note="Beat"') for _, clip_content in lane1_clips)
        self.assertEqual(actual_downbeat_markers_in_lane1, len(downbeat_times), "Mismatch in Downbeat marker count on lane 1")
        self.assertEqual(actual_beat_markers_in_lane1, 0, "Found non-Downbeat markers on lane 1")

        # Check marker counts on Lane 2 (Beats)
        lane2_clips = re.findall(rf'<(video)[^>]*lane="2"[^>]*ref="{placeholder_resource_id}"[^>]*>(.*?)</\1>', fcpxml_string, re.DOTALL)
        self.assertTrue(len(lane2_clips) > 0, f"No video clips found on lane 2 referencing {placeholder_resource_id}")
        actual_beat_markers_in_lane2 = sum(clip_content.count('note="Beat"') for _, clip_content in lane2_clips)
        actual_downbeat_markers_in_lane2 = sum(clip_content.count('note="Downbeat"') for _, clip_content in lane2_clips)
        self.assertEqual(actual_beat_markers_in_lane2, len(beat_times), "Mismatch in Beat marker count on lane 2")
        self.assertEqual(actual_downbeat_markers_in_lane2, 0, "Found non-Beat markers on lane 2")

        # Optional: Write output for inspection (can be moved or removed)
        output_dir = os.path.join(os.path.dirname(__file__), "output")
        output_path = os.path.join(output_dir, "babygotback_markers.fcpxml") # Corrected filename
        os.makedirs(output_dir, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(fcpxml_string)
        # logger.info(f"[Test `test_json_to_fcpxml_markers`] Optional: Wrote generated FCPXML to {output_path}") # Keep logger commented

    def test_generated_fcpxml_structure(self):
        """
        Tests the detailed XML structure and attributes of the FCPXML generated
        from JSON beat data, using ElementTree for precise validation.
        """
        json_path = os.path.join(os.path.dirname(__file__), 'data', 'babygotback.json')
        data = self._generate_timeline_and_fcpxml_from_json(json_path)
        fcpxml_string = data["fcpxml_string"]
        timeline = data["timeline"]
        rate = data["rate"]
        media_url = data["media_url"]
        expected_asset_name = data["expected_asset_name"]
        placeholder_resource_id = data["placeholder_resource_id"]
        placeholder_effect_name = data["placeholder_effect_name"]
        placeholder_effect_uid = data["placeholder_effect_uid"]
        timeline_duration = data["timeline_duration"]

        # --- Detailed XML Assertions (ElementTree based) --- #
        # print("\n[INFO Test 2] Parsing generated XML for detailed assertions...")
        logger.info("[Test `test_generated_fcpxml_structure`] Parsing generated XML for detailed assertions...")
        try:
            # Remove DOCTYPE before parsing for simplicity
            xml_string_no_doctype = fcpxml_string.replace('<!DOCTYPE fcpxml>\n', '')
            root = ET.fromstring(xml_string_no_doctype)
        except ET.ParseError as e:
            self.fail(f"Failed to parse generated FCPXML: {e}\nXML content (first 1k chars):\n{fcpxml_string[:1000]}...")

        # 1. Core Structure Checks
        self.assertEqual(root.tag, 'fcpxml', "XML Root tag mismatch")
        project = root.find('./project')
        self.assertIsNotNone(project, "Missing <project> element")
        resources = project.find('./resources')
        self.assertIsNotNone(resources, "Missing <resources> element")
        sequence = project.find('./sequence')
        self.assertIsNotNone(sequence, "Missing <sequence> element")
        spine = sequence.find('./spine')
        self.assertIsNotNone(spine, "Missing <spine> element")
        container_gap = spine.find('./gap') # Assuming writer uses a root container gap
        self.assertIsNotNone(container_gap, "Missing container <gap> in spine")

        # 2. Key Element Attributes
        self.assertEqual(root.get('version'), '1.13', "fcpxml version attribute mismatch")
        self.assertEqual(project.get('name'), timeline.name, "Project name mismatch")

        seq_format_id = sequence.get('format')
        self.assertIsNotNone(seq_format_id, "Sequence missing format attribute")
        expected_seq_duration_str = _fcpx_time_str(timeline_duration)
        self.assertEqual(sequence.get('duration'), expected_seq_duration_str, "Sequence duration mismatch")
        self.assertEqual(sequence.get('tcStart'), '0s', "Sequence tcStart mismatch")
        self.assertEqual(sequence.get('audioLayout'), 'stereo', "Sequence audioLayout mismatch")
        self.assertEqual(sequence.get('audioRate'), '48k', "Sequence audioRate mismatch")

        # Check container gap attributes if present
        self.assertEqual(container_gap.get('name'), 'Timeline Container', "Container gap name mismatch") # Name added by writer
        self.assertEqual(container_gap.get('offset'), '0s', "Container gap offset mismatch")
        self.assertEqual(container_gap.get('start'), '0s', "Container gap start mismatch")
        self.assertEqual(container_gap.get('duration'), expected_seq_duration_str, "Container gap duration mismatch")

        # 3. Resource Checks
        # Format (expecting r1 based on writer logic)
        format_elem = resources.find(f'./format[@id="{seq_format_id}"]')
        self.assertIsNotNone(format_elem, f"Format resource {seq_format_id} not found")
        self.assertEqual(format_elem.get('frameDuration'), '1/24s', "Format frameDuration mismatch")
        self.assertEqual(format_elem.get('name'), 'FFVideoFormat_OTIO_24', "Format name mismatch")

        # Asset (expecting r2) - updated for new DTD structure
        asset_elem = resources.find('./asset[@id="r2"]')
        self.assertIsNotNone(asset_elem, "Asset resource r2 not found")
        self.assertEqual(asset_elem.get('name'), expected_asset_name, "Asset name mismatch")
        # DTD now uses src attribute directly, not media-rep
        self.assertEqual(asset_elem.get('src'), media_url, "Asset src mismatch")
        self.assertEqual(asset_elem.get('hasAudio'), '1', "Asset hasAudio mismatch")
        self.assertEqual(asset_elem.get('hasVideo'), '0', "Asset hasVideo mismatch")

        # Effect (using extracted ID)
        effect_elem = resources.find(f'./effect[@id="{placeholder_resource_id}"]')
        self.assertIsNotNone(effect_elem, f"Effect resource {placeholder_resource_id} not found")
        self.assertEqual(effect_elem.get('name'), placeholder_effect_name, "Effect name mismatch")
        self.assertEqual(effect_elem.get('uid'), placeholder_effect_uid, "Effect uid mismatch")

        # 4. Clips in Container Checks
        # Assuming the writer puts clips inside the root container gap
        audio_clip_elem = container_gap.find('./asset-clip[@lane="-1"]')
        self.assertIsNotNone(audio_clip_elem, "Audio asset-clip (lane -1) not found in container gap")
        self.assertEqual(audio_clip_elem.get('name'), "Audio Clip", "Audio clip name mismatch")
        self.assertEqual(audio_clip_elem.get('ref'), 'r2', "Audio clip ref mismatch")
        self.assertEqual(audio_clip_elem.get('role'), 'dialogue', "Audio clip role mismatch")  # Changed from audioRole

        video_clips_lane1 = container_gap.findall(f'./video[@lane="1"][@ref="{placeholder_resource_id}"]')
        self.assertTrue(len(video_clips_lane1) > 0, "No placeholder video clips found on lane 1 in container gap")

        video_clips_lane2 = container_gap.findall(f'./video[@lane="2"][@ref="{placeholder_resource_id}"]')
        self.assertTrue(len(video_clips_lane2) > 0, "No placeholder video clips found on lane 2 in container gap")

        # 5. Marker Attribute Checks
        all_markers = container_gap.findall('.//marker') # Find all markers within the container gap
        self.assertTrue(len(all_markers) > 0, "No markers found within the container gap")
        expected_marker_duration = _fcpx_time_str(opentime.RationalTime(1, rate)) # Should be "1/24s"
        for i, marker in enumerate(all_markers):
            # Check start time format if needed (e.g., using regex)
            # self.assertRegex(marker.get('start'), r'\\d+/\\d+s', f"Marker #{i+1} start time format incorrect")
            self.assertEqual(marker.get('duration'), expected_marker_duration,
                             f"Marker #{i+1} (note: {marker.get('note')}) has incorrect duration")
            self.assertIn(marker.get('note'), ["Beat", "Downbeat"], f"Marker #{i+1} has unexpected note: {marker.get('note')}")

        # print("[INFO Test 2] Detailed XML assertions passed.")
        logger.info("[Test `test_generated_fcpxml_structure`] Detailed XML assertions passed.")

class WriterTest(unittest.TestCase, otio_test_utils.OTIOAssertions):
    """Test the FCPXML writer with XML validation against DTD"""
    
    def setUp(self):
        self.dtd_path = os.path.join(os.path.dirname(__file__), 'dtds', 'fcpxml-1.13.dtd')
        self.maxDiff = None
    
    def _validate_xml_against_dtd(self, xml_content):
        """Validate XML content against FCPXML DTD using xmllint"""
        try:
            # Create temporary files for XML and DTD
            with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as xml_file:
                xml_file.write(xml_content)
                xml_file_path = xml_file.name
            
            # Validate using xmllint
            result = subprocess.run([
                'xmllint', '--noout', '--dtdvalid', self.dtd_path, xml_file_path
            ], capture_output=True, text=True)
            
            # Clean up
            os.unlink(xml_file_path)
            
            if result.returncode != 0:
                self.fail(f"XML validation failed against DTD:\n{result.stderr}")
            
            return True
            
        except FileNotFoundError:
            # Skip validation if xmllint is not available but warn
            print("Warning: xmllint not available - XML validation skipped")
            return True
        except Exception as e:
            self.fail(f"XML validation error: {e}")

    def test_single_video_track(self):
        """Test basic single video track export with DTD validation"""
        timeline = otio.schema.Timeline(name="Single Video Track Timeline")
        timeline.global_start_time = otio.opentime.RationalTime(0, 25)
        
        # Add video track
        video_track = otio.schema.Track(name="Video Track", kind=otio.schema.TrackKind.Video)
        timeline.tracks.append(video_track)
        
        # Add video clip
        clip_ref = otio.schema.ExternalReference(
            target_url="file:///path/to/video.mov"
        )
        clip = otio.schema.Clip(
            name="Video Clip",
            media_reference=clip_ref,
            source_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, 25),
                duration=otio.opentime.RationalTime(100, 25)
            )
        )
        video_track.append(clip)
        
        # Generate FCPXML
        writer = FcpXmlWriter(timeline)
        xml_content = writer.build_xml_string()
        
        # Validate basic structure
        root = ET.fromstring(xml_content)
        self.assertEqual(root.tag, 'fcpxml')
        self.assertEqual(root.get('version'), '1.13')
        
        # Find resources section
        project = root.find('project')
        self.assertIsNotNone(project)
        resources = project.find('resources')
        self.assertIsNotNone(resources)
        
        # Find format element
        format_elem = resources.find('format')
        self.assertIsNotNone(format_elem)
        self.assertIsNotNone(format_elem.get('frameDuration'))
        
        # Find asset element
        asset_elem = resources.find('asset')
        self.assertIsNotNone(asset_elem)
        self.assertEqual(asset_elem.get('src'), 'file:///path/to/video.mov')
        
        # Find sequence
        sequence = project.find('sequence')
        self.assertIsNotNone(sequence)
        
        # Find spine
        spine = sequence.find('spine')
        self.assertIsNotNone(spine)
        
        # Find asset-clip and verify NO frameDuration attribute
        asset_clip = spine.find('.//asset-clip')
        self.assertIsNotNone(asset_clip)
        self.assertIsNone(asset_clip.get('frameDuration'), 
                         "asset-clip should not have frameDuration attribute")
        
        # Validate against DTD
        self._validate_xml_against_dtd(xml_content)

    def test_multiple_frame_rates_no_invalid_attributes(self):
        """Test multiple frame rates don't create invalid frameDuration attributes on clips"""
        timeline = otio.schema.Timeline(name="Mixed Frame Rate Timeline")
        timeline.global_start_time = otio.opentime.RationalTime(0, 25)
        
        # Add video track
        video_track = otio.schema.Track(name="Video Track", kind=otio.schema.TrackKind.Video)
        timeline.tracks.append(video_track)
        
        # Add clips with different frame rates
        clips_data = [
            ("24fps", 24, "file:///path/to/24fps.mov"),
            ("25fps", 25, "file:///path/to/25fps.mov"),
            ("30fps", 30, "file:///path/to/30fps.mov"),
        ]
        
        for name, fps, url in clips_data:
            clip_ref = otio.schema.ExternalReference(target_url=url)
            clip = otio.schema.Clip(
                name=name,
                media_reference=clip_ref,
                source_range=otio.opentime.TimeRange(
                    start_time=otio.opentime.RationalTime(0, fps),
                    duration=otio.opentime.RationalTime(fps, fps)  # 1 second
                )
            )
            video_track.append(clip)
        
        # Generate FCPXML
        writer = FcpXmlWriter(timeline)
        xml_content = writer.build_xml_string()
        
        # Parse and validate structure
        root = ET.fromstring(xml_content)
        
        # Verify that NO asset-clip elements have frameDuration attributes
        for asset_clip in root.findall('.//asset-clip'):
            self.assertIsNone(asset_clip.get('frameDuration'),
                            f"asset-clip '{asset_clip.get('name')}' should not have frameDuration attribute")
        
        # Validate against DTD
        self._validate_xml_against_dtd(xml_content)

    def test_audio_track_validates(self):
        """Test audio track export with DTD validation"""
        timeline = otio.schema.Timeline(name="Audio Timeline")
        timeline.global_start_time = otio.opentime.RationalTime(0, 48000)
        
        # Add audio track
        audio_track = otio.schema.Track(name="Audio Track", kind=otio.schema.TrackKind.Audio)
        timeline.tracks.append(audio_track)
        
        # Add audio clip
        audio_ref = otio.schema.ExternalReference(target_url="file:///path/to/audio.wav")
        audio_clip = otio.schema.Clip(
            name="Audio Clip",
            media_reference=audio_ref,
            source_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, 48000),
                duration=otio.opentime.RationalTime(48000, 48000)
            )
        )
        audio_track.append(audio_clip)
        
        # Generate FCPXML
        writer = FcpXmlWriter(timeline)
        xml_content = writer.build_xml_string()
        
        # Basic structure validation
        root = ET.fromstring(xml_content)
        self.assertEqual(root.tag, 'fcpxml')
        
        # Validate against DTD
        self._validate_xml_against_dtd(xml_content)

    def test_empty_timeline_validates(self):
        """Test that an empty timeline still generates valid FCPXML"""
        timeline = otio.schema.Timeline(name="Empty Timeline")
        timeline.global_start_time = otio.opentime.RationalTime(0, 25)
        
        # Generate FCPXML
        writer = FcpXmlWriter(timeline)
        xml_content = writer.build_xml_string()
        
        # Basic structure validation
        root = ET.fromstring(xml_content)
        self.assertEqual(root.tag, 'fcpxml')
        
        # Validate against DTD
        self._validate_xml_against_dtd(xml_content)

    def test_fractional_frame_rates_validate(self):
        """Test that fractional frame rates like 29.97 generate valid FCPXML"""
        timeline = otio.schema.Timeline(name="Fractional Frame Rate Timeline")
        timeline.global_start_time = otio.opentime.RationalTime(0, 25)
        
        # Add video track
        video_track = otio.schema.Track(name="Video Track", kind=otio.schema.TrackKind.Video)
        timeline.tracks.append(video_track)
        
        # Add clip with 29.97 fps (30000/1001)
        from fractions import Fraction
        rate_2997 = Fraction(30000, 1001)
        
        clip_ref = otio.schema.ExternalReference(target_url="file:///path/to/2997fps.mov")
        clip = otio.schema.Clip(
            name="29.97fps Clip",
            media_reference=clip_ref,
            source_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, rate_2997),
                duration=otio.opentime.RationalTime(rate_2997, rate_2997)  # 1 second
            )
        )
        video_track.append(clip)
        
        # Generate FCPXML
        writer = FcpXmlWriter(timeline)
        xml_content = writer.build_xml_string()
        
        # Parse and validate structure
        root = ET.fromstring(xml_content)
        
        # Verify format has correct frameDuration
        format_elem = root.find('.//format')
        self.assertIsNotNone(format_elem)
        frame_duration = format_elem.get('frameDuration')
        self.assertIsNotNone(frame_duration)
        self.assertEqual(frame_duration, '1/25s')  # Timeline rate, not clip rate
        
        # Verify asset-clip has NO frameDuration
        asset_clip = root.find('.//asset-clip')
        self.assertIsNotNone(asset_clip)
        self.assertIsNone(asset_clip.get('frameDuration'),
                         "asset-clip should not have frameDuration attribute")
        
        # Validate against DTD
        self._validate_xml_against_dtd(xml_content)


if __name__ == '__main__':
    unittest.main()
