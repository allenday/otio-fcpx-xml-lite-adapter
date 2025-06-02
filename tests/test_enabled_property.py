#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the OpenTimelineIO project

import unittest
import opentimelineio as otio
import xml.etree.ElementTree as ET

from otio_fcpx_xml_lite_adapter.adapter import write_to_string, read_from_string


class EnabledPropertyTest(unittest.TestCase):
    """Test that the enabled property on OTIO clips is properly exported to FCPXML."""
    
    def setUp(self):
        """Set up test data."""
        self.rate = 24.0
        self.timeline = otio.schema.Timeline(name="Enabled Property Test")
        self.timeline.global_start_time = otio.opentime.RationalTime(0, self.rate)  # Add required frame rate
        
        # Create a video track
        video_track = otio.schema.Track(name="Video Track", kind=otio.schema.TrackKind.Video)
        self.timeline.tracks.append(video_track)
        
        # Create two clips: one enabled, one disabled
        # Enabled clip
        enabled_clip = otio.schema.Clip(
            name="Enabled Clip",
            media_reference=otio.schema.GeneratorReference(
                name="Enabled Generator",
                generator_kind="fcpx_video_placeholder",
                parameters={
                    'fcpx_ref': 'r1',
                    'fcpx_effect_name': 'Placeholder',
                    'fcpx_effect_uid': '/Applications/Final Cut Pro.app/Contents/PlugIns/Placeholder.motn'
                }
            ),
            source_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, self.rate),
                duration=otio.opentime.RationalTime(48, self.rate)  # 2 seconds
            )
        )
        enabled_clip.enabled = True
        
        # Disabled clip
        disabled_clip = otio.schema.Clip(
            name="Disabled Clip",
            media_reference=otio.schema.GeneratorReference(
                name="Disabled Generator",
                generator_kind="fcpx_video_placeholder",
                parameters={
                    'fcpx_ref': 'r1',
                    'fcpx_effect_name': 'Placeholder',
                    'fcpx_effect_uid': '/Applications/Final Cut Pro.app/Contents/PlugIns/Placeholder.motn'
                }
            ),
            source_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, self.rate),
                duration=otio.opentime.RationalTime(48, self.rate)  # 2 seconds
            )
        )
        disabled_clip.enabled = False
        
        # Add clips to track
        video_track.append(enabled_clip)
        video_track.append(disabled_clip)
    
    def test_enabled_property_export(self):
        """Test that enabled=False clips export with enabled="0" attribute."""
        # Write timeline to FCPXML string
        fcpxml_string = write_to_string(self.timeline)
        
        # Parse the XML to check attributes
        root = ET.fromstring(fcpxml_string)
        
        # Find video elements
        video_elements = root.findall('.//video')
        self.assertEqual(len(video_elements), 2, "Should have 2 video elements")
        
        # Check attributes
        enabled_video = None
        disabled_video = None
        
        for video_elem in video_elements:
            if video_elem.get('name') == 'Enabled Clip':
                enabled_video = video_elem
            elif video_elem.get('name') == 'Disabled Clip':
                disabled_video = video_elem
        
        self.assertIsNotNone(enabled_video, "Enabled video element not found")
        self.assertIsNotNone(disabled_video, "Disabled video element not found")
        
        # The enabled clip should have enabled="1" or no enabled attribute (default is enabled)
        enabled_attr = enabled_video.get('enabled')
        # FCPXML typically omits enabled attribute when it's 1/true (default)
        self.assertIn(enabled_attr, [None, '1'], "Enabled clip should have enabled='1' or no enabled attribute")
        
        # The disabled clip should have enabled="0"
        disabled_attr = disabled_video.get('enabled')
        self.assertEqual(disabled_attr, '0', "Disabled clip should have enabled='0' attribute")
    
    def test_enabled_property_roundtrip(self):
        """Test that the enabled property is preserved in a roundtrip."""
        # Write to FCPXML
        fcpxml_string = write_to_string(self.timeline)
        
        # Read back from FCPXML
        roundtrip_timeline = read_from_string(fcpxml_string)
        
        # Check that clips have the correct enabled property
        video_tracks = roundtrip_timeline.video_tracks()
        self.assertEqual(len(video_tracks), 1, "Should have 1 video track")
        
        clips = [item for item in video_tracks[0] if isinstance(item, otio.schema.Clip)]
        self.assertEqual(len(clips), 2, "Should have 2 clips")
        
        enabled_clip = None
        disabled_clip = None
        
        for clip in clips:
            if clip.name == 'Enabled Clip':
                enabled_clip = clip
            elif clip.name == 'Disabled Clip':
                disabled_clip = clip
        
        self.assertIsNotNone(enabled_clip, "Enabled clip not found in roundtrip")
        self.assertIsNotNone(disabled_clip, "Disabled clip not found in roundtrip")
        
        # Check enabled properties
        self.assertTrue(enabled_clip.enabled, "Enabled clip should have enabled=True")
        self.assertFalse(disabled_clip.enabled, "Disabled clip should have enabled=False")


if __name__ == '__main__':
    unittest.main() 